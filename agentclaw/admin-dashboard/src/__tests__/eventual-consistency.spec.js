import { describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import {
  isEventuallyConsistentReadError,
  withReadinessRetry,
} from '../utils/eventualConsistency'

describe('eventual consistency retry helpers', () => {
  it('treats transient not-found read errors as retryable', () => {
    expect(isEventuallyConsistentReadError({ response: { status: 404 } })).toBe(true)
    expect(isEventuallyConsistentReadError({ response: { status: 409 } })).toBe(true)
    expect(isEventuallyConsistentReadError({ response: { status: 500 } })).toBe(false)
    expect(isEventuallyConsistentReadError({ response: { status: 401 } })).toBe(false)
  })

  it('retries a newly created resource read until it becomes available', async () => {
    const operation = vi.fn()
      .mockRejectedValueOnce({ response: { status: 404 } })
      .mockResolvedValueOnce({ id: 'turtle_soup' })

    const result = await withReadinessRetry(operation, { delays: [0, 0] })

    expect(result).toEqual({ id: 'turtle_soup' })
    expect(operation).toHaveBeenCalledTimes(2)
  })

  it('does not retry non-readiness errors', async () => {
    const error = { response: { status: 500 } }
    const operation = vi.fn().mockRejectedValue(error)

    await expect(withReadinessRetry(operation, { delays: [0, 0] })).rejects.toBe(error)
    expect(operation).toHaveBeenCalledTimes(1)
  })

  it('waits for newly imported templates before opening the chat page', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/views/TemplateLibrary.vue'), 'utf8')
    const waitIndex = source.indexOf('await waitForImportedWorkflow(result.workflow_id)')
    const openIndex = source.indexOf('openWorkflow({ ...app, workflow_id: result.workflow_id, registered: true })')

    expect(source).toContain('withReadinessRetry')
    expect(source).toContain('workflowsApi.get(workflowId)')
    expect(waitIndex).toBeGreaterThan(-1)
    expect(openIndex).toBeGreaterThan(waitIndex)
  })

  it('applies readiness retry to destination-page resource reads', () => {
    const expected = [
      ['src/views/AgentChat.vue', 'withReadinessRetry'],
      ['src/views/WorkflowDetail.vue', 'withReadinessRetry'],
      ['src/views/WorkflowConfig.vue', 'withReadinessRetry'],
      ['src/views/WorkflowDebug.vue', 'withReadinessRetry'],
      ['src/views/KnowledgebaseDetail.vue', 'withReadinessRetry'],
      ['src/views/KnowledgebaseSearch.vue', 'withReadinessRetry'],
      ['src/views/KnowledgebaseDocumentDetail.vue', 'withReadinessRetry'],
      ['src/views/SchedulerDetail.vue', 'withReadinessRetry'],
      ['src/views/TraceDetail.vue', 'withReadinessRetry'],
      ['src/views/Settings.vue', 'withReadinessRetry'],
      ['src/views/scheduler/JobFormModal.vue', 'withReadinessRetry'],
    ]

    for (const [path, marker] of expected) {
      const source = readFileSync(resolve(process.cwd(), path), 'utf8')
      expect(source, `${path} should use readiness retry`).toContain(marker)
    }
  })
})
