<template>
  <div>
    <PageHeader :breadcrumbs="breadcrumbs" @refresh="fetchData" />

    <n-spin :show="!trace">
      <template v-if="trace">
        <!-- 追踪概览 -->
        <n-card size="small" style="margin-bottom: 20px;">
          <n-space align="center" :size="20">
            <n-tag :type="statusType(trace.status)" size="medium" round>{{ statusLabel(trace.status) }}</n-tag>
            <n-text>{{ t('traceDetail.workflow') }}: <n-text strong>{{ trace.workflow_id }}</n-text></n-text>
            <n-text>{{ t('traceDetail.duration') }}:
              <n-text strong :type="durColor(trace.duration_ms)">{{ formatDuration(trace.duration_ms) }}</n-text>
            </n-text>
            <n-text>{{ t('traceDetail.startedAt') }}: <n-text strong>{{ formatDateTime(trace.start_time) }}</n-text></n-text>
            <n-text v-if="trace.thread_id" depth="3" style="font-size: 12px; font-family: monospace;">
              {{ t('traceDetail.thread') }}: {{ trace.thread_id.length > 20 ? trace.thread_id.slice(0, 20) + '...' : trace.thread_id }}
            </n-text>
          </n-space>
        </n-card>

        <!-- Token 统计 -->
        <div v-if="totalTokens > 0" class="stat-grid" style="margin-bottom: 20px;">
          <n-card size="small">
            <n-statistic :label="t('traceDetail.totalTokens')">
              <template #default><n-text strong>{{ formatTokens(totalTokens) }}</n-text></template>
            </n-statistic>
          </n-card>
          <n-card size="small">
            <n-statistic :label="t('traceDetail.inputTokens')">
              <template #default><n-text type="info">{{ formatTokens(totalPromptTokens) }}</n-text></template>
              <template #suffix>
                <n-text depth="3" style="font-size: 12px; margin-left: 4px;">
                  {{ totalTokens ? ((totalPromptTokens / totalTokens) * 100).toFixed(0) + '%' : '' }}
                </n-text>
              </template>
            </n-statistic>
          </n-card>
          <n-card size="small">
            <n-statistic :label="t('traceDetail.outputTokens')">
              <template #default><n-text type="success">{{ formatTokens(totalCompletionTokens) }}</n-text></template>
              <template #suffix>
                <n-text depth="3" style="font-size: 12px; margin-left: 4px;">
                  {{ totalTokens ? ((totalCompletionTokens / totalTokens) * 100).toFixed(0) + '%' : '' }}
                </n-text>
              </template>
            </n-statistic>
          </n-card>
          <n-card size="small">
            <n-statistic :label="t('traceDetail.llmCalls')" :value="llmCallCount" />
          </n-card>
        </div>

        <!-- 执行路径 -->
        <n-card v-if="trace.node_logs?.length" size="small" style="margin-bottom: 16px;">
          <template #header><n-text strong style="font-size: 13px;">{{ t('traceDetail.executionPath') }}</n-text></template>
          <n-space :size="6" align="center" :wrap="true">
            <n-tag size="small" type="success" round>__start__</n-tag>
            <template v-for="node in trace.node_logs" :key="node.id">
              <n-text depth="3" style="font-size: 11px;">→</n-text>
              <n-tooltip>
                <template #trigger>
                  <n-tag size="small" :type="nodeTagType(node)" round style="cursor: pointer;" @click="selectNode(node)">
                    {{ node.name || node.id }}
                  </n-tag>
                </template>
                {{ node.node_type }} · {{ statusLabel(node.status) }} · {{ formatDuration(node.duration_ms) }}
              </n-tooltip>
            </template>
            <n-text depth="3" style="font-size: 11px;">→</n-text>
            <n-tag size="small" :type="trace.status === 'success' ? 'success' : 'error'" round>__end__</n-tag>
          </n-space>
        </n-card>

        <!-- 执行时间线 -->
        <n-card size="small" style="margin-bottom: 16px;">
          <template #header><n-text strong style="font-size: 13px;">{{ t('traceDetail.executionTimeline') }}</n-text></template>
          <n-timeline>
            <n-timeline-item type="info" :title="t('traceDetail.workflowStart')" :time="formatTime(trace.start_time)" />

            <n-timeline-item v-for="node in trace.node_logs" :key="node.id"
              :type="nodeTimelineType(node)"
              style="cursor: pointer;" @click="selectNode(node)">
              <template #header>
                <n-space :size="8" align="center">
                  <n-text strong style="font-size: 13px;">{{ node.name || node.id }}</n-text>
                  <n-tag :type="statusType(node.status)" size="tiny" round>{{ statusLabel(node.status) }}</n-tag>
                  <n-text :type="durColor(node.duration_ms)" style="font-size: 12px; font-weight: 600;">
                    {{ formatDuration(node.duration_ms) }}
                  </n-text>
                </n-space>
              </template>
              <div style="display: flex; flex-direction: column; gap: 6px;">
                <n-progress type="line" :percentage="durPercent(node.duration_ms)"
                  :status="durProgressStatus(node.duration_ms)"
                  :show-indicator="false" :height="3" style="max-width: 200px;" />
                <n-space :size="16" style="font-size: 12px;">
                  <n-text depth="3">{{ t('traceDetail.type') }}: <n-text code style="font-size: 11px;">{{ node.node_type }}</n-text></n-text>
                  <template v-if="getLLMLogs(node).length">
                    <n-text depth="3">{{ t('traceDetail.llmCount', { count: getLLMLogs(node).length }) }}</n-text>
                    <n-text depth="3">{{ t('traceDetail.token') }}: <n-text strong style="font-size: 12px;">{{ formatTokens(getNodeTotalTokens(node)) }}</n-text></n-text>
                  </template>
                </n-space>
              </div>
            </n-timeline-item>

            <n-timeline-item :type="trace.status === 'success' ? 'success' : 'error'" :time="formatTime(trace.end_time)">
              <template #header>
                <n-space :size="8" align="center">
                  <n-text strong style="font-size: 13px;">{{ t('traceDetail.workflowEnd') }}</n-text>
                  <n-tag :type="statusType(trace.status)" size="tiny" round>{{ statusLabel(trace.status) }}</n-tag>
                  <n-text depth="3" style="font-size: 12px;">{{ t('traceDetail.totalDuration') }}: {{ formatDuration(trace.duration_ms) }}</n-text>
                </n-space>
              </template>
            </n-timeline-item>
          </n-timeline>
        </n-card>

        <!-- 输入数据 -->
        <n-card v-if="trace.input_data" size="small" style="margin-bottom: 16px;">
          <template #header>
            <n-space align="center" :size="8">
              <n-text strong style="font-size: 13px;">{{ t('traceDetail.inputData') }}</n-text>
              <n-tag size="tiny" :bordered="false">JSON</n-tag>
            </n-space>
          </template>
          <n-code :code="JSON.stringify(trace.input_data, null, 2)" language="json" />
        </n-card>

        <!-- 错误信息 -->
        <n-alert v-if="trace.error" type="error" :title="t('traceDetail.errorInfo')" style="margin-bottom: 16px;">
          <pre style="margin: 0; white-space: pre-wrap; font-size: 12px;">{{ trace.error }}</pre>
        </n-alert>

        <!-- 用户输出 -->
        <n-card v-if="trace.output_data?.answer" size="small" style="margin-bottom: 16px;">
          <template #header>
            <n-space align="center" :size="8">
              <n-text strong style="font-size: 13px;">{{ t('traceDetail.output') }}</n-text>
              <n-tag size="tiny" :bordered="false" type="success">{{ t('traceDetail.userVisible') }}</n-tag>
            </n-space>
          </template>
          <div style="white-space: pre-wrap; font-size: 13px; line-height: 1.6;">{{ trace.output_data.answer }}</div>
        </n-card>

        <!-- 输出数据 -->
        <n-card v-if="trace.output_data" size="small" style="margin-bottom: 16px;">
          <template #header>
            <n-space align="center" :size="8">
              <n-text strong style="font-size: 13px;">{{ t('traceDetail.outputData') }}</n-text>
              <n-tag size="tiny" :bordered="false">JSON</n-tag>
            </n-space>
          </template>
          <n-code :code="JSON.stringify(trace.output_data, null, 2)" language="json" />
        </n-card>
      </template>
    </n-spin>

    <!-- 节点详情抽屉 -->
    <n-drawer v-model:show="drawerVisible" :width="drawerWidth" placement="right">
      <div :style="resizeHandleStyle" @mousedown="onResizeMouseDown" />
      <n-drawer-content :title="t('traceDetail.nodeDetailTitle', { name: selectedNode?.name || selectedNode?.id || '' })" :native-scrollbar="false">
        <template v-if="selectedNode">
          <!-- 节点概览 -->
          <n-card size="small" style="margin-bottom: 16px;">
            <n-space align="center" :size="16">
              <n-tag :type="statusType(selectedNode.status)" size="medium" round>{{ statusLabel(selectedNode.status) }}</n-tag>
              <n-text>{{ t('traceDetail.type') }}: <n-text code>{{ selectedNode.node_type }}</n-text></n-text>
              <n-text>{{ t('traceDetail.duration') }}:
                <n-text strong :type="durColor(selectedNode.duration_ms)">{{ formatDuration(selectedNode.duration_ms) }}</n-text>
              </n-text>
            </n-space>
            <n-progress type="line" :percentage="durPercent(selectedNode.duration_ms)"
              :status="durProgressStatus(selectedNode.duration_ms)"
              :show-indicator="false" :height="4" style="margin-top: 8px;" />
          </n-card>

          <!-- LLM 调用 -->
          <template v-if="getLLMLogs(selectedNode).length">
            <n-space align="center" :size="8" style="margin-bottom: 8px;">
              <n-text strong style="font-size: 13px;">{{ t('traceDetail.llmCalls') }}</n-text>
              <n-tag size="tiny" :bordered="false">{{ t('traceDetail.callCount', { count: getLLMLogs(selectedNode).length }) }}</n-tag>
            </n-space>
            <n-card v-for="(llmLog, idx) in getLLMLogs(selectedNode)" :key="llmLog.id" size="small" style="margin-bottom: 10px;">
              <template #header>
                <n-space justify="space-between" align="center" style="width: 100%;">
                  <n-space :size="8" align="center">
                    <n-text v-if="getLLMLogs(selectedNode).length > 1" depth="3" style="font-size: 12px;">{{ t('traceDetail.callNumber', { count: idx + 1 }) }}</n-text>
                    <n-text code style="font-size: 12px;">{{ llmLog.model_id }}</n-text>
                  </n-space>
                  <n-text :type="durColor(llmLog.latency_ms)" style="font-size: 12px; font-weight: 600;">
                    {{ formatDuration(llmLog.latency_ms) }}
                  </n-text>
                </n-space>
              </template>
              <n-grid :cols="3" :x-gap="12">
                <n-gi>
                  <n-text depth="3" style="font-size: 11px; display: block;">{{ t('traceDetail.input') }}</n-text>
                  <n-text type="info" strong>{{ formatTokens(llmLog.prompt_tokens) }}</n-text>
                </n-gi>
                <n-gi>
                  <n-text depth="3" style="font-size: 11px; display: block;">{{ t('traceDetail.output') }}</n-text>
                  <n-text type="success" strong>{{ formatTokens(llmLog.completion_tokens) }}</n-text>
                </n-gi>
                <n-gi>
                  <n-text depth="3" style="font-size: 11px; display: block;">{{ t('traceDetail.total') }}</n-text>
                  <n-text strong>{{ formatTokens(llmLog.total_tokens) }}</n-text>
                </n-gi>
              </n-grid>
              <template v-if="llmLog.metadata?.tool_calls?.length">
                <n-divider style="margin: 10px 0 8px;" />
                <n-space align="center" :size="8" style="margin-bottom: 6px;">
                  <n-text depth="3" style="font-size: 12px;">{{ t('traceDetail.toolCalls') }}</n-text>
                  <n-tag size="tiny" :bordered="false">{{ llmLog.metadata.tool_calls.length }}</n-tag>
                </n-space>
                <div v-for="(tc, tcIdx) in llmLog.metadata.tool_calls" :key="tc.id || tcIdx" class="tool-call-card" :class="getToolResultStatus(llmLog, tc)">
                  <div class="tool-call-header">
                    <span class="tool-call-index">#{{ tcIdx + 1 }}</span>
                    <n-text strong style="font-size: 13px; font-family: monospace;">{{ tc.name }}</n-text>
                    <n-tag v-if="getToolResult(llmLog, tc)" :type="getToolResultStatus(llmLog, tc) === 'error' ? 'error' : 'success'" size="tiny" round>
                      {{ getToolResultStatus(llmLog, tc) === 'error' ? t('traceDetail.status.error') : t('traceDetail.status.success') }}
                    </n-tag>
                  </div>
                  <div class="tool-call-section call-section">
                    <div class="tool-section-label">
                      <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 10 20 15 15 20"/><path d="M4 4v7a4 4 0 0 0 4 4h12"/></svg>
                      {{ t('traceDetail.callArguments') }}
                    </div>
                    <n-code :code="tc.arguments || '{}'" language="json" style="font-size: 12px;" />
                  </div>
                  <div v-if="getToolResult(llmLog, tc)" class="tool-call-section result-section" :class="getToolResultStatus(llmLog, tc)">
                    <div class="tool-section-label">
                      <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 10 4 15 9 20"/><path d="M20 4v7a4 4 0 0 1-4 4H4"/></svg>
                      {{ t('traceDetail.returnResult') }}
                    </div>
                    <n-code :code="truncateResult(getToolResult(llmLog, tc).result)" style="max-height: 300px; overflow-y: auto; font-size: 12px;" />
                  </div>
                </div>
              </template>
            </n-card>
          </template>

          <!-- 输入输出 -->
          <n-card v-if="selectedNode.input_data" size="small" style="margin-bottom: 10px;">
            <template #header>
              <n-space align="center" :size="8">
                <n-text strong style="font-size: 13px;">{{ t('traceDetail.input') }}</n-text>
                <n-tag size="tiny" :bordered="false">JSON</n-tag>
              </n-space>
            </template>
            <n-code :code="JSON.stringify(selectedNode.input_data, null, 2)" language="json" />
          </n-card>
          <n-card v-if="selectedNode.output_data" size="small" style="margin-bottom: 10px;">
            <template #header>
              <n-space align="center" :size="8">
                <n-text strong style="font-size: 13px;">{{ t('traceDetail.output') }}</n-text>
                <n-tag size="tiny" :bordered="false">JSON</n-tag>
              </n-space>
            </template>
            <n-code :code="JSON.stringify(selectedNode.output_data, null, 2)" language="json" />
          </n-card>
          <n-alert v-if="selectedNode.error" type="error" :title="t('traceDetail.error')" style="margin-bottom: 10px;">
            <pre style="margin: 0; white-space: pre-wrap; font-size: 12px;">{{ selectedNode.error }}</pre>
          </n-alert>
        </template>
      </n-drawer-content>
    </n-drawer>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import {
  NCard, NGrid, NGi, NStatistic, NSpace, NTag, NText, NSpin, NProgress, NTooltip,
  NTimeline, NTimelineItem, NCode, NAlert, NDrawer, NDrawerContent,
  NDivider,
} from 'naive-ui'
import PageHeader from '../components/PageHeader.vue'
import { tracesApi } from '../api'
import { durationBarPercent, formatDuration, formatDateTime, formatTokens } from '../composables/useFormatters'
import { useResizableDrawer } from '../composables/useResizableDrawer'
import { withReadinessRetry } from '../utils/eventualConsistency'

const route = useRoute()
const { t, locale } = useI18n()
const traceId = computed(() => route.params.id)
const trace = ref(null)
const selectedNode = ref(null)
const drawerVisible = ref(false)
const { drawerWidth, resizeHandleStyle, onResizeMouseDown } = useResizableDrawer({ initial: 720, min: 400, max: 1200 })
const breadcrumbs = computed(() => ([
  { text: t('traceDetail.dashboard'), to: '/dashboard?tab=traces' },
  { text: `${traceId.value.substring(0, 18)}...` },
]))

const totalTokens = computed(() => (trace.value?.llm_logs || []).reduce((s, l) => s + (l.total_tokens || 0), 0))
const totalPromptTokens = computed(() => (trace.value?.llm_logs || []).reduce((s, l) => s + (l.prompt_tokens || 0), 0))
const totalCompletionTokens = computed(() => (trace.value?.llm_logs || []).reduce((s, l) => s + (l.completion_tokens || 0), 0))
const llmCallCount = computed(() => trace.value?.llm_logs?.length || 0)

const statusType = (s) => ({ success: 'success', error: 'error', running: 'info', timeout: 'warning' }[s] || 'default')
const statusLabel = (s) => ({
  success: t('traceDetail.status.success'),
  error: t('traceDetail.status.error'),
  running: t('traceDetail.status.running'),
  timeout: t('traceDetail.status.timeout'),
  cancelled: t('traceDetail.status.cancelled'),
}[s] || s)
const nodeTagType = (node) => node.status === 'error' ? 'error' : 'success'
const nodeTimelineType = (node) => {
  if (node.status === 'error') return 'error'
  if (node.node_type === 'llm' || node.node_type === 'llmnode') return 'success'
  return 'info'
}

// 基于平均耗时动态计算颜色阈值
const avgNodeDuration = computed(() => {
  const nodes = trace.value?.node_logs || []
  if (!nodes.length) return 0
  const total = nodes.reduce((s, n) => s + (n.duration_ms || 0), 0)
  return total / nodes.length
})

function durColor(ms) {
  if (ms == null) return 'default'
  const avg = avgNodeDuration.value || 1
  if (ms < avg * 0.5) return 'success'
  if (ms < avg * 1.5) return 'default'
  if (ms < avg * 2.5) return 'warning'
  return 'error'
}

function durPercent(ms) {
  return durationBarPercent(ms, (trace.value?.node_logs || []).map(n => n.duration_ms))
}

function durProgressStatus(ms) {
  const c = durColor(ms)
  return c === 'default' ? undefined : c
}

function formatTime(val) {
  if (!val) return '-'
  return new Date(val).toLocaleTimeString(locale.value || undefined, { hour12: false })
}

function getLLMLogs(node) {
  if (!trace.value?.llm_logs) return []
  return trace.value.llm_logs.filter(log => log.node_log_id === node.id)
}

function getNodeTotalTokens(node) {
  return getLLMLogs(node).reduce((s, l) => s + (l.total_tokens || 0), 0)
}

function getToolResult(llmLog, tc) {
  const results = llmLog.metadata?.tool_results
  if (!results) return null
  return results.find(r => r.id === tc.id) || results.find(r => r.name === tc.name) || null
}

function getToolResultStatus(llmLog, tc) {
  const result = getToolResult(llmLog, tc)
  if (!result) return 'pending'
  const text = String(result.result || '').toLowerCase().slice(0, 300)
  if (['[tool_failed', '[error]', 'traceback', 'execution failed', 'tool_error', '[timeout]'].some(h => text.includes(h))) return 'error'
  return 'success'
}

function truncateResult(text, maxLen = 3000) {
  if (!text) return ''
  if (text.length <= maxLen) return text
  return text.substring(0, maxLen) + `\n... (${t('traceDetail.truncated', { count: text.length })})`
}

function selectNode(node) {
  selectedNode.value = node
  drawerVisible.value = true
}

async function fetchData() {
  try {
    trace.value = await withReadinessRetry(() => tracesApi.get(traceId.value))
  } catch (e) {
    console.error('Failed to fetch trace:', e)
  }
}

onMounted(fetchData)
</script>

<style scoped>
.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}

/* Tool call cards in drawer */
.tool-call-card {
  margin-bottom: 12px;
  border-radius: 8px;
  border: 1px solid #e5e7eb;
  border-left: 3px solid #3b82f6;
  overflow: hidden;
  background: #fafbfc;
}

.tool-call-card.error {
  border-left-color: #ef4444;
}

.tool-call-card.success {
  border-left-color: #10b981;
}

.tool-call-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: #f3f4f6;
  border-bottom: 1px solid #e5e7eb;
}

.tool-call-index {
  font-size: 11px;
  font-weight: 600;
  color: #6b7280;
  font-family: monospace;
}

.tool-call-section {
  padding: 8px 12px;
}

.tool-section-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  font-weight: 600;
  margin-bottom: 6px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.call-section .tool-section-label {
  color: #3b82f6;
}

.result-section {
  border-top: 1px dashed #e5e7eb;
  background: #f0fdf4;
}

.result-section .tool-section-label {
  color: #10b981;
}

.result-section.error {
  background: #fef2f2;
}

.result-section.error .tool-section-label {
  color: #ef4444;
}

@media (max-width: 1200px) {
  .stat-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 640px) {
  .stat-grid {
    grid-template-columns: 1fr;
  }
}
</style>
