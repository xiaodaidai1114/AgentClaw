import { defineStore } from 'pinia'
import { ref } from 'vue'
import { tracesApi } from '../api'

export const useTracesStore = defineStore('traces', () => {
  const traces = ref([])
  const total = ref(0)
  const currentTrace = ref(null)
  const timeline = ref([])
  const summary = ref(null)
  const loading = ref(false)
  const error = ref(null)

  async function fetchTraces(params = {}) {
    loading.value = true
    error.value = null
    try {
      const res = await tracesApi.list(params)
      traces.value = res.traces
      total.value = res.total
    } catch (e) {
      error.value = e.message
    } finally {
      loading.value = false
    }
  }

  async function fetchTrace(id) {
    loading.value = true
    error.value = null
    try {
      currentTrace.value = await tracesApi.get(id)
    } catch (e) {
      error.value = e.message
    } finally {
      loading.value = false
    }
  }

  async function fetchTimeline(id) {
    try {
      const res = await tracesApi.getTimeline(id)
      timeline.value = res.events
    } catch (e) {
      error.value = e.message
    }
  }

  async function fetchSummary() {
    try {
      summary.value = await tracesApi.getSummary()
    } catch (e) {
      error.value = e.message
    }
  }

  return {
    traces,
    total,
    currentTrace,
    timeline,
    summary,
    loading,
    error,
    fetchTraces,
    fetchTrace,
    fetchTimeline,
    fetchSummary,
  }
})
