import { defineStore } from 'pinia'
import { ref } from 'vue'
import { dashboardApi, tracesApi } from '../api'

export const useDashboardStore = defineStore('dashboard', () => {
  const stats = ref(null)
  const trends = ref(null)
  const tracesSummary = ref(null)
  const loading = ref(false)
  const error = ref(null)

  async function fetchStats() {
    try {
      stats.value = await dashboardApi.getStats()
    } catch (e) {
      error.value = e.message
    }
  }

  async function fetchTrends(timeRange = '24h') {
    try {
      trends.value = await dashboardApi.getTrends(timeRange)
    } catch (e) {
      error.value = e.message
    }
  }

  async function fetchTracesSummary() {
    try {
      tracesSummary.value = await tracesApi.getSummary()
    } catch (e) {
      error.value = e.message
    }
  }

  async function fetchAll(timeRange = '24h') {
    loading.value = true
    error.value = null
    await Promise.all([
      fetchStats(),
      fetchTrends(timeRange),
      fetchTracesSummary(),
    ])
    loading.value = false
  }

  return {
    stats,
    trends,
    tracesSummary,
    loading,
    error,
    fetchStats,
    fetchTrends,
    fetchTracesSummary,
    fetchAll,
  }
})
