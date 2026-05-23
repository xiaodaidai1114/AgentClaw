const DEFAULT_READINESS_RETRY_DELAYS = [120, 260, 520, 900]

export function isEventuallyConsistentReadError(error) {
  const status = Number(error?.response?.status || 0)
  if (status === 404 || status === 409) return true
  const code = error?.response?.data?.code || error?.response?.data?.detail?.code
  return code === 'WORKFLOW_NOT_FOUND' || code === 'NOT_FOUND'
}

function sleep(ms) {
  if (!ms) return Promise.resolve()
  return new Promise(resolve => setTimeout(resolve, ms))
}

export async function withReadinessRetry(operation, options = {}) {
  const delays = Array.isArray(options.delays) ? options.delays : DEFAULT_READINESS_RETRY_DELAYS
  let lastError = null
  for (let attempt = 0; attempt <= delays.length; attempt += 1) {
    try {
      return await operation()
    } catch (error) {
      lastError = error
      if (!isEventuallyConsistentReadError(error) || attempt >= delays.length) {
        throw error
      }
      await sleep(Number(delays[attempt] || 0))
    }
  }
  throw lastError
}
