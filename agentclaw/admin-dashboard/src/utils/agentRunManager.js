const FINISHED_RUN_TTL_MS = 30 * 1000
const timerHost = typeof window !== 'undefined' ? window : globalThis

function cloneValue(value) {
  if (value === undefined) return undefined
  if (typeof structuredClone === 'function') {
    try {
      return structuredClone(value)
    } catch (error) {
      // Fall through to JSON cloning for plain runtime snapshots.
    }
  }
  return JSON.parse(JSON.stringify(value))
}

class AgentRunManager {
  constructor() {
    this.runs = new Map()
  }

  makeKey({ isPublicMode = false, workflowId, conversationId }) {
    const source = isPublicMode ? 'public' : 'admin'
    return `${source}:${workflowId || ''}:${conversationId || ''}`
  }

  startRun(key, { abort, snapshot } = {}) {
    if (!key) return null
    const existing = this.runs.get(key)
    if (existing?.cleanupTimer) timerHost.clearTimeout(existing.cleanupTimer)
    const run = existing || {
      key,
      subscribers: new Set(),
      abort: null,
      snapshot: null,
      status: 'running',
      cleanupTimer: null,
    }
    run.abort = typeof abort === 'function' ? abort : null
    run.snapshot = cloneValue({ ...(snapshot || {}), isStreaming: true })
    run.status = 'running'
    run.cleanupTimer = null
    this.runs.set(key, run)
    this.notify(run)
    return run
  }

  hasActiveRun(key) {
    return this.runs.get(key)?.status === 'running'
  }

  getSnapshot(key) {
    const run = this.runs.get(key)
    return run?.snapshot ? cloneValue(run.snapshot) : null
  }

  updateRun(key, snapshot) {
    const run = this.runs.get(key)
    if (!run) return null
    run.snapshot = cloneValue(snapshot || {})
    this.notify(run)
    return run.snapshot
  }

  finishRun(key, snapshot) {
    const run = this.runs.get(key)
    if (!run) return
    run.snapshot = cloneValue({ ...(snapshot || run.snapshot || {}), isStreaming: false })
    run.status = 'finished'
    run.abort = null
    this.notify(run)
    if (run.cleanupTimer) timerHost.clearTimeout(run.cleanupTimer)
    run.cleanupTimer = timerHost.setTimeout(() => {
      if (this.runs.get(key) === run && run.status === 'finished') {
        this.runs.delete(key)
      }
    }, FINISHED_RUN_TTL_MS)
  }

  async abortRun(key) {
    const run = this.runs.get(key)
    if (!run) return false
    if (run.abort) await run.abort()
    return true
  }

  subscribe(key, callback) {
    const run = this.runs.get(key)
    if (!run || typeof callback !== 'function') return () => {}
    run.subscribers.add(callback)
    if (run.snapshot) callback(cloneValue(run.snapshot))
    return () => {
      const current = this.runs.get(key)
      current?.subscribers.delete(callback)
    }
  }

  notify(run) {
    const snapshot = run.snapshot ? cloneValue(run.snapshot) : null
    for (const callback of run.subscribers) {
      callback(snapshot)
    }
  }

  clear() {
    for (const run of this.runs.values()) {
      if (run.cleanupTimer) timerHost.clearTimeout(run.cleanupTimer)
    }
    this.runs.clear()
  }
}

export const agentRunManager = new AgentRunManager()
