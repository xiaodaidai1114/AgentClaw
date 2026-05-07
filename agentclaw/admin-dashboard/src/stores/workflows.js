import { defineStore } from 'pinia'
import { ref } from 'vue'
import { workflowsApi, modelsApi } from '../api'

export const useWorkflowsStore = defineStore('workflows', () => {
  const workflows = ref([])
  const currentWorkflow = ref(null)
  const currentStats = ref(null)
  const currentTrends = ref(null)
  const availableModels = ref([])
  const defaultModelId = ref('')
  const loading = ref(false)
  const error = ref(null)

  async function fetchWorkflows() {
    loading.value = true
    error.value = null
    try {
      const res = await workflowsApi.list()
      workflows.value = res.workflows
    } catch (e) {
      error.value = e.message
    } finally {
      loading.value = false
    }
  }

  async function fetchWorkflow(id) {
    loading.value = true
    error.value = null
    try {
      const res = await workflowsApi.get(id)
      currentWorkflow.value = res.workflow
      currentStats.value = res.stats
    } catch (e) {
      error.value = e.message
    } finally {
      loading.value = false
    }
  }

  async function fetchTrends(id, timeRange = '24h') {
    try {
      currentTrends.value = await workflowsApi.getTrends(id, timeRange)
    } catch (e) {
      error.value = e.message
    }
  }

  async function fetchAvailableModels() {
    try {
      const res = await modelsApi.getAvailable()
      availableModels.value = res.models
      defaultModelId.value = res.default_model_id || ''
    } catch (e) {
      error.value = e.message
    }
  }

  async function updateNodeModel(workflowId, nodeName, modelId) {
    try {
      await workflowsApi.updateNodeModel(workflowId, nodeName, modelId)
      // 刷新工作流数据
      await fetchWorkflow(workflowId)
      return { success: true }
    } catch (e) {
      error.value = e.message
      return { success: false, message: e.message }
    }
  }

  return {
    workflows,
    currentWorkflow,
    currentStats,
    currentTrends,
    availableModels,
    defaultModelId,
    loading,
    error,
    fetchWorkflows,
    fetchWorkflow,
    fetchTrends,
    fetchAvailableModels,
    updateNodeModel,
  }
})
