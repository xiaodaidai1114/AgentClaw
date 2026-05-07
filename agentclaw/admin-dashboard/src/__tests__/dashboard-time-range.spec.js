import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, shallowMount } from '@vue/test-utils'

import Dashboard from '../views/Dashboard.vue'
import { tracesApi, workflowsApi } from '../api'

const routerMocks = vi.hoisted(() => ({
  route: { query: {} },
  push: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRoute: () => routerMocks.route,
  useRouter: () => ({ push: routerMocks.push }),
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key) => key }),
}))

vi.mock('../api', () => ({
  tracesApi: {
    getSummary: vi.fn(async () => ({
      total: 3,
      success: 2,
      error: 1,
      avg_duration_ms: 1200,
      running: 0,
    })),
    list: vi.fn(async () => ({ traces: [] })),
  },
  workflowsApi: {
    list: vi.fn(async () => ({ workflows: [] })),
  },
}))

function rangeHours(params) {
  return (new Date(params.end_time).getTime() - new Date(params.start_time).getTime()) / (60 * 60 * 1000)
}

describe('Dashboard time range selector', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-05-06T12:00:00.000Z'))
    routerMocks.route.query = {}
    routerMocks.push.mockClear()
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('applies the selected time range to summary and recent trace requests', async () => {
    const wrapper = shallowMount(Dashboard, {
      global: {
        stubs: {
          PageHeader: {
            name: 'PageHeader',
            props: ['title', 'showTimeSelector', 'defaultTime'],
            emits: ['time-change', 'refresh'],
            template: '<div />',
          },
        },
      },
    })

    await flushPromises()

    expect(rangeHours(tracesApi.getSummary.mock.calls.at(-1)[0])).toBe(24)
    expect(workflowsApi.list).toHaveBeenCalledWith({ include_builtin: true, time_range: '24h' })

    await wrapper.findComponent({ name: 'PageHeader' }).vm.$emit('time-change', '7d')
    await flushPromises()

    const summaryParams = tracesApi.getSummary.mock.calls.at(-1)[0]
    const traceParams = tracesApi.list.mock.calls.at(-1)[0]

    expect(rangeHours(summaryParams)).toBe(7 * 24)
    expect(workflowsApi.list.mock.calls.at(-1)[0]).toMatchObject({
      include_builtin: true,
      time_range: '7d',
    })
    expect(traceParams).toMatchObject({
      limit: 5,
      include_internal: false,
      start_time: summaryParams.start_time,
      end_time: summaryParams.end_time,
    })
  })
})
