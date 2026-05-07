<template>
  <div>
    <PageHeader :breadcrumbs="[{ text: t('workflows.title'), to: '/workflows' }, { text: workflowId }]" @refresh="fetchData">
      <template #actions>
        <n-button size="small" @click="router.push(`/workflows/${workflowId}/config`)">{{ t('workflowDetail.configure') }}</n-button>
        <n-button type="success" size="small" @click="router.push(`/workflows/${workflowId}/chat`)">{{ t('common.experience') }}</n-button>
        <n-button type="primary" size="small" @click="router.push(`/workflows/${workflowId}/debug`)">{{ t('common.debug') }}</n-button>
        <n-button v-if="!isBuiltinWorkflow" size="small" @click="copyChatLink">{{ t('common.share') }}</n-button>
        <n-select v-model:value="timeRange" :options="timeOptions" style="width: 140px;" size="small" @update:value="fetchStats" />
      </template>
    </PageHeader>

    <!-- 工作流概览 -->
    <n-card size="small" style="margin-bottom: 20px;">
      <n-space align="center" :size="20">
        <n-text strong style="font-size: 15px;">{{ workflow?.name || workflowId }}</n-text>
        <n-tag size="small" round>v{{ workflow?.version || '-' }}</n-tag>
        <n-text depth="3" style="font-size: 13px;">{{ t('workflowDetail.nodesCount', { count: workflow?.nodes?.length || 0 }) }}</n-text>
        <n-text v-if="workflow?.description" depth="3" style="font-size: 13px;">{{ workflow.description }}</n-text>
        <n-text code style="font-size: 12px;">{{ workflow?.id }}</n-text>
      </n-space>
    </n-card>

    <!-- 统计卡片 -->
    <div class="stat-grid" style="margin-bottom: 20px;">
      <n-card size="small">
        <n-statistic :label="t('workflowDetail.executions')" :value="stats?.total_count || 0" />
      </n-card>
      <n-card size="small">
        <n-statistic :label="t('workflowDetail.successRate')">
          <template #default>
            <n-text :type="successRateType">{{ stats?.success_rate != null ? stats.success_rate.toFixed(1) + '%' : '-' }}</n-text>
          </template>
        </n-statistic>
      </n-card>
      <n-card size="small">
        <n-statistic :label="t('workflowDetail.avgDuration')">
          <template #default>{{ formatDuration(stats?.avg_duration_ms) }}</template>
        </n-statistic>
      </n-card>
      <n-card size="small">
        <n-statistic :label="t('workflowDetail.p95Duration')">
          <template #default>{{ formatDuration(stats?.p95_duration_ms) }}</template>
        </n-statistic>
      </n-card>
      <n-card size="small">
        <n-statistic label="累计点赞" :value="workflow?.like_count || 0" />
      </n-card>
      <n-card size="small">
        <n-statistic label="累计点踩" :value="workflow?.dislike_count || 0" />
      </n-card>
    </div>

    <!-- 工作流可视化 -->
    <n-card size="small" style="margin-bottom: 20px;">
      <template #header><n-text strong style="font-size: 13px;">{{ t('workflowDetail.structure') }}</n-text></template>
      <template #header-extra>
        <n-text depth="3" style="font-size: 13px;">{{ t('workflowDetail.clickNode') }}</n-text>
      </template>
      <WorkflowGraph
        v-if="workflow?.nodes?.length"
        :nodes="workflow.nodes"
        :edges="workflow.edges || []"
        :node-order="workflow.node_order || []"
        @node-click="showNodeDetail"
      />
      <n-empty v-else :description="t('workflowDetail.noNodes')" style="padding: 60px 0;" />
    </n-card>

    <!-- 执行历史 -->
    <n-card size="small">
      <template #header><n-text strong style="font-size: 13px;">{{ t('workflowDetail.history') }}</n-text></template>
      <template #header-extra>
        <n-button text type="primary" @click="router.push(`/dashboard?tab=traces&workflow_id=${workflowId}`)">{{ t('common.viewAll') }}</n-button>
      </template>
      <n-data-table
        :columns="traceColumns"
        :data="recentTraces"
        :bordered="false"
        size="small"
        :row-key="row => row.id"
        :row-props="traceRowProps"
      />
    </n-card>

    <!-- 节点详情 Drawer -->
    <n-drawer v-model:show="drawerVisible" :width="drawerWidth" placement="right">
      <div :style="resizeHandleStyle" @mousedown="onResizeMouseDown" />
      <n-drawer-content :title="`${selectedNode?.id || ''} ${t('workflowDetail.node')}`" :native-scrollbar="false">
        <n-card size="small" style="margin-bottom: 16px;">
          <n-space align="center" :size="16">
            <n-tag :type="isLLMNode(selectedNode) ? 'success' : 'info'" size="medium" round>
              {{ getNodeTypeLabel(selectedNode) }}
            </n-tag>
            <n-text strong>{{ selectedNode?.id }}</n-text>
          </n-space>
        </n-card>

        <n-descriptions :column="1" label-placement="left" bordered size="small">
          <n-descriptions-item :label="t('workflowDetail.type')">
            <n-text code>{{ getNodeTypeLabel(selectedNode) }}</n-text>
          </n-descriptions-item>
          <n-descriptions-item v-if="selectedNodeStats?.avg_duration_ms" label="平均耗时">
            {{ formatDuration(selectedNodeStats.avg_duration_ms) }}
          </n-descriptions-item>
        </n-descriptions>

        <template v-if="isLLMNode(selectedNode)">
          <n-divider />
          <n-space align="center" :size="8" style="margin-bottom: 8px;">
            <n-text strong style="font-size: 13px;">{{ t('workflowDetail.model') }}</n-text>
          </n-space>
          <n-select
            v-model:value="selectedModelId"
            :options="modelOptions"
            @update:value="modelChanged = true"
          />
          <n-space v-if="modelChanged" justify="end" style="margin-top: 12px;">
            <n-button size="small" @click="cancelModelChange">{{ $t('common.cancel') }}</n-button>
            <n-button size="small" type="primary" @click="saveModelChange">{{ $t('common.save') }}</n-button>
          </n-space>
        </template>
      </n-drawer-content>
    </n-drawer>
  </div>
</template>

<script setup>
import { h, ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  NCard, NStatistic, NTag, NText, NButton, NSelect, NProgress,
  NDescriptions, NDescriptionsItem, NSpace,
  NDataTable, NDrawer, NDrawerContent, NDivider, NEmpty, useMessage,
} from 'naive-ui'
import PageHeader from '../components/PageHeader.vue'
import WorkflowGraph from '../components/WorkflowGraph.vue'
import { workflowsApi, tracesApi, modelsApi, settingsApi } from '../api'
import { localizeBuiltinWorkflow } from '../utils/builtinWorkflowI18n'
import { durationBarPercent, formatDuration, formatDateTime } from '../composables/useFormatters'
import { useResizableDrawer } from '../composables/useResizableDrawer'
import { toConversationModelOptions } from '../utils/models'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const { t } = useI18n()
const workflowId = computed(() => route.params.id)

const workflow = ref(null)
const workflowSettings = ref(null)
const stats = ref(null)
const recentTraces = ref([])
const availableModels = ref([])
const defaultModelId = ref('')
const timeRange = ref('24h')

const timeOptions = computed(() => [
  { label: t('pageHeader.time24h'), value: '24h' },
  { label: t('pageHeader.time7d'), value: '7d' },
  { label: t('pageHeader.time30d'), value: '30d' },
])

// Node detail drawer
const drawerVisible = ref(false)
const { drawerWidth, resizeHandleStyle, onResizeMouseDown } = useResizableDrawer({ initial: 420, min: 320, max: 900 })
const selectedNode = ref(null)
const selectedNodeStats = ref(null)
const selectedModelId = ref('')
const originalModelId = ref('')
const modelChanged = ref(false)

const modelOptions = computed(() => toConversationModelOptions(availableModels.value))
const isBuiltinWorkflow = computed(() => workflowId.value === '__builtin__' || !!workflow.value?.is_builtin)
const publicShareEnabled = computed(() => !!(workflowSettings.value?.public_share_enabled ?? workflow.value?.public_share_enabled))
const publicShareToken = computed(() => workflowSettings.value?.public_share_token || workflow.value?.public_share_token || '')

const successRateType = computed(() => {
  const rate = stats.value?.success_rate
  if (rate == null) return 'default'
  if (rate >= 95) return 'success'
  if (rate >= 80) return 'default'
  if (rate >= 60) return 'warning'
  return 'error'
})

const statusMap = computed(() => ({
  success: t('traces.success'),
  error: t('traces.failed'),
  completed: t('traces.success'),
  failed: t('traces.failed'),
  running: t('traces.running'),
  cancelled: t('traces.cancelled'),
  timeout: t('traces.timeout'),
}))
const statusTypeMap = { success: 'success', completed: 'success', error: 'error', failed: 'error', running: 'info', cancelled: 'warning', timeout: 'warning' }

function durColor(ms) {
  if (ms == null) return 'default'
  const avg = stats.value?.avg_duration_ms || 1
  if (ms < avg * 0.5) return 'success'
  if (ms < avg * 1.5) return 'default'
  if (ms < avg * 2.5) return 'warning'
  return 'error'
}

function durPercent(ms) {
  return durationBarPercent(ms, recentTraces.value.map(t => t.duration_ms))
}

// Trace table columns
const traceColumns = computed(() => [
  {
    title: t('dashboard.traceId'),
    key: 'id',
    width: 170,
    render: (row) => h('a', {
      style: 'font-family: monospace; font-size: 12px; cursor: pointer; color: var(--primary); text-decoration: none;',
      onClick: () => router.push(`/traces/${row.id}`)
    }, row.id?.substring(0, 16) + '...'),
  },
  {
    title: t('dashboard.status'),
    key: 'status',
    width: 90,
    render: (row) => h(NTag, {
      type: statusTypeMap[row.status] || 'default',
      size: 'small',
      round: true,
    }, { default: () => statusMap.value[row.status] || row.status }),
  },
  {
    title: t('workflowDetail.avgDuration'),
    key: 'duration_ms',
    width: 130,
    render: (row) => {
      const dur = row.duration_ms
      const type = durColor(dur)
      return h('div', { style: 'display: flex; flex-direction: column; gap: 2px;' }, [
        h(NText, { type, style: 'font-size: 12px; font-weight: 600;' }, { default: () => formatDuration(dur) }),
        h(NProgress, {
          type: 'line', percentage: durPercent(dur),
          status: type === 'default' ? undefined : type,
          showIndicator: false, height: 3,
        }),
      ])
    },
  },
  {
    title: t('workflowDetail.startTime'),
    key: 'start_time',
    width: 160,
    render: (row) => formatDateTime(row.start_time),
  },
  {
    title: t('dashboard.actions'),
    key: 'actions',
    width: 80,
    render: (row) => h(NButton, {
      text: true, type: 'primary', size: 'small',
      onClick: () => router.push(`/traces/${row.id}`),
    }, () => t('common.detail')),
  },
])

function traceRowProps(row) {
  return {
    style: 'cursor: pointer;',
    onClick: () => router.push(`/traces/${row.id}`),
  }
}

async function fetchData() {
  try {
    const res = await workflowsApi.get(workflowId.value)
    workflow.value = localizeBuiltinWorkflow(res.workflow, t)
    stats.value = res.stats
    try {
      workflowSettings.value = await settingsApi.getWorkflow(workflowId.value)
    } catch {
      workflowSettings.value = null
    }
  } catch (e) {
    console.error('Failed to fetch workflow:', e)
  }
}

async function fetchStats() {
  try {
    stats.value = await workflowsApi.getStats(workflowId.value, { time_range: timeRange.value })
  } catch (e) {
    console.error('Failed to fetch stats:', e)
  }
}

async function fetchRecentTraces() {
  try {
    const res = await tracesApi.list({ workflow_id: workflowId.value, limit: 5 })
    recentTraces.value = res.traces || []
  } catch (e) {
    console.error('Failed to fetch traces:', e)
  }
}

async function fetchModels() {
  try {
    const res = await modelsApi.getAvailable()
    availableModels.value = res.models || []
    defaultModelId.value = res.default_model_id || ''
  } catch (e) {
    console.error('Failed to fetch models:', e)
  }
}

function showNodeDetail(node) {
  selectedNode.value = node
  selectedModelId.value = node.model_id || defaultModelId.value
  originalModelId.value = node.model_id || defaultModelId.value
  modelChanged.value = false
  selectedNodeStats.value = null
  drawerVisible.value = true
}

function isLLMNode(node) {
  if (!node) return false
  return (node.type?.toLowerCase() || '').includes('llm')
}

function getNodeTypeLabel(node) {
  if (!node) return ''
  const type = node.type?.toLowerCase() || ''
  if (type.includes('llm')) return 'LLM'
  if (type.includes('human')) return 'Human'
  if (type.includes('function')) return 'Function'
  return 'Function'
}

async function saveModelChange() {
  if (!selectedNode.value || !modelChanged.value) return
  try {
    await workflowsApi.updateNodeModel(workflowId.value, selectedNode.value.name || selectedNode.value.id, selectedModelId.value)
    selectedNode.value.model_id = selectedModelId.value
    originalModelId.value = selectedModelId.value
    modelChanged.value = false
    message.success('模型切换成功')
  } catch (e) {
    message.error('模型切换失败')
  }
}

function cancelModelChange() {
  selectedModelId.value = originalModelId.value
  modelChanged.value = false
}

function copyChatLink() {
  if (isBuiltinWorkflow.value) {
    message.warning(t('workflowDetail.builtinShareDisabled'))
    return
  }
  if (!publicShareEnabled.value || !publicShareToken.value) {
    message.warning(t('workflowDetail.publicShareDisabled'))
    return
  }
  const route = router.resolve({ name: 'PublicAgent', params: { id: workflowId.value }, query: { share_token: publicShareToken.value } })
  const url = `${window.location.origin}${route.href}`
  navigator.clipboard.writeText(url).then(() => {
    message.success('访问链接已复制')
  }).catch(() => {
    message.info(url)
  })
}

onMounted(() => {
  fetchData()
  fetchRecentTraces()
  fetchModels()
})
</script>

<style scoped>
.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
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
