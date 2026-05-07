/**
 * API 服务层 - 统一管理所有后端 API 调用
 */
import axios from 'axios'

// 生产环境使用相对路径，开发环境使用代理
const api = axios.create({
  baseURL: '/admin',
  timeout: 30000,
})

// Token 管理
let adminToken = localStorage.getItem('admin_token') || ''

export function setAdminToken(token) {
  adminToken = token
  if (token) localStorage.setItem('admin_token', token)
  else localStorage.removeItem('admin_token')
  window.dispatchEvent(new CustomEvent('admin-auth-updated'))
}

export function getAdminToken() {
  return adminToken
}

export function clearAdminToken() {
  adminToken = ''
  localStorage.removeItem('admin_token')
  window.dispatchEvent(new CustomEvent('admin-auth-updated'))
}

export function notifyAdminAuthRequired() {
  clearAdminToken()
  window.dispatchEvent(new CustomEvent('admin-auth-required'))
}

export function requireAdminToken() {
  const token = getAdminToken()
  if (!token) {
    notifyAdminAuthRequired()
    return ''
  }
  return token
}

export function getAdminAuthHeaders(extraHeaders = {}) {
  const token = requireAdminToken()
  if (!token) return null
  return {
    ...extraHeaders,
    Authorization: `Bearer ${token}`,
  }
}

export function handleAdminFetchAuthError(response) {
  if (response?.status === 401) {
    notifyAdminAuthRequired()
    return true
  }
  return false
}

function handleAdminAuthError(error) {
  console.error('API Error:', error.response?.data || error.message)
  if (error.response?.status === 401) {
    notifyAdminAuthRequired()
  }
  return Promise.reject(error)
}

// 请求拦截器 - 添加 Authorization header
api.interceptors.request.use(
  (config) => {
    if (adminToken) {
      config.headers.Authorization = `Bearer ${adminToken}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

// 响应拦截器
api.interceptors.response.use(
  (response) => response.data,
  handleAdminAuthError
)

export default api

// Dashboard API
export const dashboardApi = {
  getStats: () => api.get('/dashboard/stats'),
  getTrends: (timeRange = '24h') => api.get('/dashboard/trends', { params: { time_range: timeRange } }),
}

// Workflows API
export const workflowsApi = {
  list: (params) => api.get('/workflows', { params }),
  get: (id) => api.get(`/workflows/${id}`),
  getStats: (id, params) => api.get(`/workflows/${id}/stats`, { params }),
  getTrends: (id, timeRange = '24h') => api.get(`/workflows/${id}/trends`, { params: { time_range: timeRange } }),
  updateNodeModel: (workflowId, nodeName, modelId) => 
    api.put(`/workflows/${workflowId}/nodes/${nodeName}/model`, { model_id: modelId }),
  // 工具配置
  getToolConfig: (workflowId) => api.get(`/workflows/${workflowId}/tool-config`),
  updateToolConfig: (workflowId, config) => api.put(`/workflows/${workflowId}/tool-config`, config),
  resetToolConfig: (workflowId) => api.post(`/workflows/${workflowId}/tool-config/reset`),
}

export const executionApi = {
  compressContext: (workflowId, conversationId) => axios.post('/api/workflow/compress', { workflow_id: workflowId, conversation_id: conversationId }, {
    headers: getAdminAuthHeaders() || {},
  }).then(response => response.data),
}

// Traces API
export const tracesApi = {
  getSummary: (params) => api.get('/traces/summary', { params }),
  list: (params) => api.get('/traces', { params }),
  get: (id) => api.get(`/traces/${id}`),
  getTimeline: (id) => api.get(`/traces/${id}/timeline`),
}

// Models API
export const modelsApi = {
  list: () => api.get('/models'),
  getAvailable: () => api.get('/models/available'),
}

// Prompts API
export const promptsApi = {
  list: (workflowId) => api.get(`/prompts/${workflowId}`),
  get: (workflowId, key) => api.get(`/prompts/${workflowId}/${key}`),
  update: (workflowId, key, content) => api.put(`/prompts/${workflowId}/${key}`, { content }),
  reset: (workflowId, key) => api.post(`/prompts/${workflowId}/${key}/reset`),
  getHistory: (workflowId, key, limit = 10) => 
    api.get(`/prompts/${workflowId}/${key}/history`, { params: { limit } }),
  rollback: (workflowId, key, version) => 
    api.post(`/prompts/${workflowId}/${key}/rollback`, { version }),
  preview: (workflowId, content, variables) => 
    api.post(`/prompts/${workflowId}/preview`, { content, variables }),
}

// Debug API
export const debugApi = {
  // 会话管理
  listSessions: () => api.get('/debug/sessions'),
  createSession: (workflowId, conversationId = null) => 
    api.post('/debug/sessions', { workflow_id: workflowId, conversation_id: conversationId }),
  getSession: (sessionId) => api.get(`/debug/sessions/${sessionId}`),
  deleteSession: (sessionId) => api.delete(`/debug/sessions/${sessionId}`),
  
  // State schema
  getStateSchema: (workflowId) => api.get(`/debug/workflows/${workflowId}/schema`),
  
  // 断点管理
  listBreakpoints: (sessionId) => api.get(`/debug/sessions/${sessionId}/breakpoints`),
  addBreakpoint: (sessionId, nodeName, type = 'before', condition = null) => 
    api.post(`/debug/sessions/${sessionId}/breakpoints`, { node_id: nodeName, type, condition }),
  removeBreakpoint: (sessionId, breakpointId) => 
    api.delete(`/debug/sessions/${sessionId}/breakpoints/${breakpointId}`),
  toggleBreakpoint: (sessionId, breakpointId) => 
    api.post(`/debug/sessions/${sessionId}/breakpoints/${breakpointId}/toggle`),
  
  // 调试控制
  resume: (sessionId, modifiedState = null) => 
    api.post(`/debug/sessions/${sessionId}/resume`, modifiedState ? { state: modifiedState } : null),
  step: (sessionId) => api.post(`/debug/sessions/${sessionId}/step`),
  stop: (sessionId) => api.post(`/debug/sessions/${sessionId}/stop`),
  
  // 状态管理
  getState: (sessionId) => api.get(`/debug/sessions/${sessionId}/state`),
  updateState: (sessionId, state) => api.put(`/debug/sessions/${sessionId}/state`, { state }),
  
  // 调试运行
  debugRun: (workflowId, inputData, conversationId = null, breakpoints = []) => 
    api.post('/debug/run', { workflow_id: workflowId, input_data: inputData, conversation_id: conversationId, breakpoints }),
}

// Conversations API (对话历史)
export const conversationsApi = {
  list: (workflowId, pageSize = 50, source = 'admin') => api.get(`/conversations/${workflowId}`, { params: { page: 1, page_size: pageSize, source } }),
  create: (workflowId, title = null, source = 'admin') => api.post('/conversations', { workflow_id: workflowId, title, source }),
  get: (workflowId, conversationId) => api.get(`/conversations/${workflowId}/${conversationId}`),
  update: (workflowId, conversationId, data) => api.put(`/conversations/${workflowId}/${conversationId}`, data),
  delete: (workflowId, conversationId) => api.delete(`/conversations/${workflowId}/${conversationId}`),
  // 反馈 API
  submitFeedback: (workflowId, conversationId, messageIndex, feedback) => 
    api.post(`/conversations/${workflowId}/${conversationId}/feedback`, { message_index: messageIndex, feedback }),
  getFeedback: (workflowId, conversationId) => 
    api.get(`/conversations/${workflowId}/${conversationId}/feedback`),
}

// 公开 API 实例（不需要认证，用于分享页面）
const publicApi = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

const publicSessionHeaders = { 'X-AgentClaw-Public-Session': '1' }

publicApi.interceptors.response.use(
  (response) => response.data,
  (error) => {
    console.error('Public API Error:', error.response?.data || error.message)
    return Promise.reject(error)
  }
)

const authenticatedPublicApi = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

authenticatedPublicApi.interceptors.request.use(
  (config) => {
    if (adminToken) {
      config.headers.Authorization = `Bearer ${adminToken}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

authenticatedPublicApi.interceptors.response.use(
  (response) => response.data,
  handleAdminAuthError
)

// Tasks API (任务管理)
export const tasksApi = {
  list: (workflowId = null) => api.get('/tasks', { params: workflowId ? { workflow_id: workflowId } : {} }),
  cancel: (taskId, reason = '用户中止') => api.post(`/tasks/${taskId}/cancel`, { reason }),
  cleanup: () => api.delete('/tasks/cleanup'),
}

// Channels API (渠道管理)
export const channelsApi = {
  list: (params) => api.get('/channels', { params }),
  get: (id) => api.get(`/channels/${id}`),
  create: (data) => api.post('/channels', data),
  update: (id, data) => api.put(`/channels/${id}`, data),
  delete: (id) => api.delete(`/channels/${id}`),
  restart: (id) => api.post(`/channels/${id}/restart`),
  // 凭据验证
  probe: (data) => api.post('/channels/probe', data),
  // 飞书扫码设置
  feishuSetup: () => api.post('/channels/feishu/setup'),
  feishuSetupStatus: (sessionId) => api.get(`/channels/feishu/setup/${sessionId}`),
  feishuSetupInput: (sessionId, input) => api.post(`/channels/feishu/setup/${sessionId}/input`, { input }),
  feishuSetupCleanup: (sessionId) => api.delete(`/channels/feishu/setup/${sessionId}`),
  // 日志
  getLogs: (id, params) => api.get(`/channels/${id}/logs`, { params }),
  getAllLogs: (params) => api.get('/channels/logs', { params }),
  getLogStats: (params) => api.get('/channels/logs/stats', { params }),
}

// KnowledgeBase API
export const knowledgebaseApi = {
  list: () => api.get('/knowledgebases'),
  get: (id) => api.get(`/knowledgebases/${id}`),
  create: (data) => api.post('/knowledgebases', data),
  update: (id, data) => api.put(`/knowledgebases/${id}`, data),
  delete: (id) => api.delete(`/knowledgebases/${id}`),
  listDocuments: (knowledgebaseId) => api.get(`/knowledgebases/${knowledgebaseId}/documents`),
  getDocument: (knowledgebaseId, documentId) => api.get(`/knowledgebases/${knowledgebaseId}/documents/${documentId}`),
  downloadDocument: (knowledgebaseId, documentId) => api.get(`/knowledgebases/${knowledgebaseId}/documents/${documentId}/download`, { responseType: 'blob' }),
  uploadDocument: (knowledgebaseId, formData) => api.post(`/knowledgebases/${knowledgebaseId}/documents/upload`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }),
  importDocument: (knowledgebaseId, data) => api.post(`/knowledgebases/${knowledgebaseId}/documents/import`, data),
  reindexDocument: (knowledgebaseId, documentId) => api.post(`/knowledgebases/${knowledgebaseId}/documents/${documentId}/reindex`),
  replaceDocument: (knowledgebaseId, documentId, formData) => api.post(`/knowledgebases/${knowledgebaseId}/documents/${documentId}/replace`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }),
  deleteDocument: (knowledgebaseId, documentId) => api.delete(`/knowledgebases/${knowledgebaseId}/documents/${documentId}`),
  search: (knowledgebaseId, data) => api.post(`/knowledgebases/${knowledgebaseId}/search`, data),
  listSearchLogs: (knowledgebaseId, limit = 50) => api.get(`/knowledgebases/${knowledgebaseId}/search-logs`, { params: { limit } }),
  createSearchLog: (knowledgebaseId, data) => api.post(`/knowledgebases/${knowledgebaseId}/search-logs`, data),
  clearSearchLogs: (knowledgebaseId) => api.delete(`/knowledgebases/${knowledgebaseId}/search-logs`),
  listChunks: (knowledgebaseId, documentId) => api.get(`/knowledgebases/${knowledgebaseId}/documents/${documentId}/chunks`),
  createChunk: (knowledgebaseId, documentId, data) => api.post(`/knowledgebases/${knowledgebaseId}/documents/${documentId}/chunks`, data),
  updateChunk: (knowledgebaseId, documentId, chunkId, data) => api.put(`/knowledgebases/${knowledgebaseId}/documents/${documentId}/chunks/${chunkId}`, data),
  deleteChunk: (knowledgebaseId, documentId, chunkId) => api.delete(`/knowledgebases/${knowledgebaseId}/documents/${documentId}/chunks/${chunkId}`),
}

export async function uploadKnowledgebaseDocuments(knowledgebaseId, files, onProgress = null) {
  const queue = Array.isArray(files) ? files : Array.from(files || [])
  const results = []
  for (let index = 0; index < queue.length; index += 1) {
    const file = queue[index]
    const formData = new FormData()
    formData.append('file', file)
    const result = await knowledgebaseApi.uploadDocument(knowledgebaseId, formData)
    results.push(result)
    onProgress?.({ index: index + 1, total: queue.length, file, result })
  }
  return results
}

// Settings API (系统配置)
export const settingsApi = {
  getGlobal: () => api.get('/settings/global'),
  getEnv: () => api.get('/settings/env'),
  updateEnv: (data) => api.put('/settings/env', data),
  getModelsConfig: () => api.get('/settings/models'),
  updateModelsConfig: (data) => api.put('/settings/models', data),
  updateGlobal: (data) => api.put('/settings/global', data),
  getInfra: (section) => api.get(`/settings/infra/${section}`),
  updateInfra: (section, data) => api.put(`/settings/infra/${section}`, data),
  getWorkflow: (workflowId) => api.get(`/settings/workflows/${workflowId}`),
  updateWorkflow: (workflowId, data) => api.put(`/settings/workflows/${workflowId}`, data),
  resetWorkflowField: (workflowId, field) => api.post(`/settings/workflows/${encodeURIComponent(workflowId)}/fields/${encodeURIComponent(field)}/reset`),
  getNode: (workflowId, nodeId) => api.get(`/settings/workflows/${workflowId}/nodes/${nodeId}`),
  updateNode: (workflowId, nodeId, data) => api.put(`/settings/workflows/${workflowId}/nodes/${nodeId}`, data),
  resetNodeField: (workflowId, nodeId, field) => api.post(`/settings/workflows/${encodeURIComponent(workflowId)}/nodes/${encodeURIComponent(nodeId)}/fields/${encodeURIComponent(field)}/reset`),
}

// Scheduler API (定时任务)
export const schedulerApi = {
  listJobs: (params) => authenticatedPublicApi.get('/scheduler/jobs', { params }),
  getJob: (id) => authenticatedPublicApi.get(`/scheduler/jobs/${id}`),
  createJob: (data) => authenticatedPublicApi.post('/scheduler/jobs', data),
  updateJob: (id, data) => authenticatedPublicApi.put(`/scheduler/jobs/${id}`, data),
  deleteJob: (id) => authenticatedPublicApi.delete(`/scheduler/jobs/${id}`),
  pauseJob: (id) => authenticatedPublicApi.post(`/scheduler/jobs/${id}/pause`),
  resumeJob: (id) => authenticatedPublicApi.post(`/scheduler/jobs/${id}/resume`),
  triggerJob: (id) => authenticatedPublicApi.post(`/scheduler/jobs/${id}/trigger`),
  webhookTrigger: (jobId, data) => publicApi.post(`/scheduler/jobs/${jobId}/webhook`, data),
  listExecutions: (jobId, params) => authenticatedPublicApi.get(`/scheduler/jobs/${jobId}/executions`, { params }),
  getExecution: (jobId, execId) => authenticatedPublicApi.get(`/scheduler/jobs/${jobId}/executions/${execId}`),
}

export const publicWorkflowsApi = {
  get: (workflowId, shareToken = '') => publicApi.get(`/public/workflows/${encodeURIComponent(workflowId)}`, { params: { share_token: shareToken } }),
  openSession: (workflowId, shareToken = '') => publicApi.post(`/public/workflows/${encodeURIComponent(workflowId)}/session`, null, { params: { share_token: shareToken }, withCredentials: true }),
}

// 公开的 Conversations API（用于分享页面）
export const publicConversationsApi = {
  list: (workflowId, pageSize = 50, source = 'public', shareToken = '') => publicApi.get(`/conversations/${encodeURIComponent(workflowId)}`, { params: { page: 1, page_size: pageSize, source, share_token: shareToken }, headers: publicSessionHeaders, withCredentials: true }),
  create: (workflowId, title = null, source = 'public', shareToken = '') => publicApi.post('/conversations', { workflow_id: workflowId, title, source, share_token: shareToken }, { headers: publicSessionHeaders, withCredentials: true }),
  get: (workflowId, conversationId, shareToken = '') => publicApi.get(`/conversations/${encodeURIComponent(workflowId)}/${encodeURIComponent(conversationId)}`, { params: { share_token: shareToken }, headers: publicSessionHeaders, withCredentials: true }),
  update: (workflowId, conversationId, data, shareToken = '') => publicApi.put(`/conversations/${encodeURIComponent(workflowId)}/${encodeURIComponent(conversationId)}`, data, { params: { share_token: shareToken }, headers: publicSessionHeaders, withCredentials: true }),
  delete: (workflowId, conversationId, shareToken = '') => publicApi.delete(`/conversations/${encodeURIComponent(workflowId)}/${encodeURIComponent(conversationId)}`, { params: { share_token: shareToken }, headers: publicSessionHeaders, withCredentials: true }),
  // 反馈 API
  submitFeedback: (workflowId, conversationId, messageIndex, feedback, shareToken = '') =>
    publicApi.post(`/conversations/${encodeURIComponent(workflowId)}/${encodeURIComponent(conversationId)}/feedback`, { message_index: messageIndex, feedback }, { params: { share_token: shareToken }, headers: publicSessionHeaders, withCredentials: true }),
  getFeedback: (workflowId, conversationId, shareToken = '') =>
    publicApi.get(`/conversations/${encodeURIComponent(workflowId)}/${encodeURIComponent(conversationId)}/feedback`, { params: { share_token: shareToken }, headers: publicSessionHeaders, withCredentials: true }),
}
