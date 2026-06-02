<template>
  <div class="dashboard-page">
    <PageHeader
      :title="t('dashboard.title')"
      :show-time-selector="currentTab === 'overview'"
      :default-time="timeRange"
      @time-change="handleTimeChange"
      @refresh="handleRefresh"
    />

    <n-tabs :value="currentTab" type="line" animated style="margin-bottom: 16px;" @update:value="handleTabChange">
      <n-tab-pane name="overview" :tab="t('dashboard.overview')">
        <div class="overview-toolbar">
          <n-space class="overview-toolbar-space" justify="space-between" align="center">
            <n-text depth="3">{{ t('dashboard.statsScope') }}</n-text>
            <n-select
              v-model:value="agentScope"
              :options="scopeOptions"
              size="small"
              style="width: 160px;"
              @update:value="handleScopeChange"
            />
          </n-space>
        </div>

        <div class="stat-grid" style="margin-bottom: 20px;">
          <n-card size="small"><n-statistic :label="t('dashboard.workflowCount')" :value="stats?.workflow_count || 0" /></n-card>
          <n-card size="small"><n-statistic :label="t('dashboard.executionInRange', { range: selectedTimeRangeLabel })" :value="stats?.execution_count || 0" /></n-card>
          <n-card size="small">
            <n-statistic :label="t('dashboard.successRateInRange', { range: selectedTimeRangeLabel })">
              <template #default>
                <n-text :type="getSuccessRateType(stats?.success_rate)">{{ formatPercent(stats?.success_rate) }}</n-text>
              </template>
            </n-statistic>
          </n-card>
          <n-card size="small"><n-statistic :label="t('dashboard.avgDurationInRange', { range: selectedTimeRangeLabel })" :value="formatDuration(stats?.avg_duration_ms)" /></n-card>
        </div>

        <n-card :title="t('dashboard.workflowOverview')" size="small" style="margin-bottom: 20px;">
          <template #header-extra>
            <n-button text type="primary" @click="openWorkflowList">
              {{ agentScope === 'builtin' ? t('dashboard.openBuiltin') : t('common.viewAll') }}
            </n-button>
          </template>
          <div v-if="workflowPageTabs.length > 1" class="workflow-page-tabs">
            <button
              v-for="tab in workflowPageTabs"
              :key="tab.name"
              :class="['workflow-page-tab', { active: workflowPage === tab.name }]"
              @click="handleWorkflowPageChange(tab.name)"
            >
              {{ tab.label }}
            </button>
          </div>
          <div class="table-scroll">
            <n-data-table :columns="workflowColumns" :data="pagedWorkflows" :bordered="false" size="small" scroll-x="max-content" />
          </div>
        </n-card>

        <n-card :title="t('dashboard.recentRuns')" size="small">
          <template #header-extra>
            <n-button text type="primary" @click="router.push('/dashboard?tab=traces')">{{ t('common.viewAll') }}</n-button>
          </template>
          <div class="table-scroll">
            <n-data-table :columns="traceColumns" :data="recentTraces" :bordered="false" size="small" scroll-x="max-content" />
          </div>
        </n-card>
      </n-tab-pane>
      <n-tab-pane name="traces" :tab="t('dashboard.traces')">
        <Traces :embedded="true" :key="`${route.fullPath}:${traceRefreshKey}`" />
      </n-tab-pane>
    </n-tabs>
  </div>
</template>

<script setup>
import { h, ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  NCard, NStatistic, NText, NButton, NTag, NDataTable, NTabs, NTabPane, NSpace, NSelect,
} from 'naive-ui'
import PageHeader from '../components/PageHeader.vue'
import Traces from './Traces.vue'
import { workflowsApi, tracesApi } from '../api'
import { formatDuration, formatDateTime } from '../composables/useFormatters'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const BUILTIN_WORKFLOW_ID = '__builtin__'
const WORKFLOW_PAGE_SIZE = 4

const stats = ref(null)
const workflows = ref([])
const recentTraces = ref([])
const traceRefreshKey = ref(0)
const agentScope = ref('all')
const workflowPage = ref('0')
const timeRange = ref('24h')

const scopeOptions = computed(() => [
  { label: t('dashboard.allAgents'), value: 'all' },
  { label: t('dashboard.builtinAgents'), value: 'builtin' },
])

const currentTab = computed(() => route.query.tab === 'traces' ? 'traces' : 'overview')
const selectedTimeRangeLabel = computed(() => {
  if (timeRange.value === '7d') return t('pageHeader.time7d')
  if (timeRange.value === '30d') return t('pageHeader.time30d')
  return t('pageHeader.time24h')
})
const workflowPageTabs = computed(() => {
  const total = workflows.value.length
  const pages = Math.ceil(total / WORKFLOW_PAGE_SIZE)
  return Array.from({ length: pages }, (_, idx) => {
    const start = idx * WORKFLOW_PAGE_SIZE + 1
    const end = Math.min(total, start + WORKFLOW_PAGE_SIZE - 1)
    return {
      name: String(idx),
      label: `${start}-${end}`,
    }
  })
})
const pagedWorkflows = computed(() => {
  const pageIndex = Number(workflowPage.value) || 0
  const start = pageIndex * WORKFLOW_PAGE_SIZE
  return workflows.value.slice(start, start + WORKFLOW_PAGE_SIZE)
})

function formatPercent(val) {
  if (val == null) return '-'
  return `${Number(val).toFixed(1)}%`
}

function getSuccessRateType(rate) {
  if (rate == null) return 'default'
  if (rate >= 95) return 'success'
  if (rate >= 90) return 'warning'
  return 'error'
}

const workflowColumns = computed(() => [
  {
    title: t('dashboard.agent'), key: 'id',
    render: (row) => h('div', null, [
      h('div', { style: 'display: flex; align-items: center; gap: 6px;' }, [
        h('span', { style: 'font-weight: 500;' }, row.name || row.id),
        row.is_builtin
          ? h(NTag, { size: 'tiny', type: 'warning', bordered: false }, { default: () => t('dashboard.builtin') })
          : null,
      ]),
      h('div', { style: 'font-size: 12px; color: var(--text-secondary);' }, row.id),
    ]),
  },
  {
    title: t('dashboard.version'), key: 'version', width: 80,
    render: (row) => h(NTag, { size: 'tiny', bordered: false }, { default: () => row.version }),
  },
  { title: t('dashboard.nodeCount'), key: 'node_count', width: 80 },
  {
    title: t('dashboard.executionInRange', { range: selectedTimeRangeLabel.value }), key: 'exec_count', width: 120,
    render: (row) => row.stats_24h?.execution_count || 0,
  },
  {
    title: t('dashboard.feedback'), key: 'feedback', width: 120,
    render: (row) => `👍 ${row.like_count || 0} / 👎 ${row.dislike_count || 0}`,
  },
  {
    title: t('dashboard.successRateInRange', { range: selectedTimeRangeLabel.value }), key: 'success_rate', width: 130,
    render: (row) => {
      const rate = row.stats_24h?.success_rate
      return h(NText, { type: getSuccessRateType(rate) }, { default: () => formatPercent(rate) })
    },
  },
  {
    title: t('dashboard.avgDurationInRange', { range: selectedTimeRangeLabel.value }), key: 'avg_duration', width: 130,
    render: (row) => formatDuration(row.stats_24h?.avg_duration_ms),
  },
  {
    title: t('dashboard.actions'), key: 'actions', width: 80,
    render: (row) => h(NButton, { text: true, type: 'primary', size: 'small', onClick: () => openWorkflowDetail(row) },
      { default: () => t('common.detail') }),
  },
])

const traceColumns = computed(() => [
  {
    title: t('dashboard.traceId'), key: 'id', width: 150,
    render: (row) => h('code', { style: 'font-size: 12px;' }, row.id.substring(0, 12) + '...'),
  },
  { title: t('dashboard.agent'), key: 'workflow_id' },
  {
    title: t('dashboard.status'), key: 'status', width: 90,
    render: (row) => {
      const typeMap = { success: 'success', error: 'error', running: 'info', timeout: 'warning' }
      return h(NTag, { type: typeMap[row.status] || 'default', size: 'small', round: true }, { default: () => row.status })
    },
  },
  {
    title: t('dashboard.avgDuration'), key: 'duration_ms', width: 90,
    render: (row) => formatDuration(row.duration_ms),
  },
  {
    title: t('dashboard.startTime'), key: 'start_time', width: 170,
    render: (row) => formatDateTime(row.start_time),
  },
  {
    title: t('dashboard.actions'), key: 'actions', width: 80,
    render: (row) => h(NButton, { text: true, type: 'primary', size: 'small', onClick: () => router.push(`/traces/${row.id}`) },
      { default: () => t('common.detail') }),
  },
])

function getTimeRangeHours(range) {
  if (range === '7d') return 7 * 24
  if (range === '30d') return 30 * 24
  return 24
}

function buildTimeWindowParams() {
  const end = new Date()
  const start = new Date(end.getTime() - getTimeRangeHours(timeRange.value) * 60 * 60 * 1000)
  return {
    start_time: start.toISOString(),
    end_time: end.toISOString(),
  }
}

function buildSummaryParams(timeWindow = buildTimeWindowParams()) {
  const params = {
    ...timeWindow,
    include_internal: false,
  }
  if (agentScope.value === 'builtin') {
    params.workflow_id = BUILTIN_WORKFLOW_ID
  }
  return params
}

function buildTraceParams(timeWindow = buildTimeWindowParams()) {
  const params = { limit: 5, include_internal: false, ...timeWindow }
  if (agentScope.value === 'builtin') {
    params.workflow_id = BUILTIN_WORKFLOW_ID
  }
  return params
}

function filterWorkflows(items) {
  if (agentScope.value === 'builtin') {
    return items.filter(wf => wf.id === BUILTIN_WORKFLOW_ID || wf.is_builtin)
  }
  return items
}

function openWorkflowDetail(row) {
  if (row.id === BUILTIN_WORKFLOW_ID || row.is_builtin) {
    router.push('/builtin')
    return
  }
  router.push(`/workflows/${row.id}`)
}

function openWorkflowList() {
  if (agentScope.value === 'builtin') {
    router.push('/builtin')
    return
  }
  router.push('/workflows')
}

function handleScopeChange() {
  workflowPage.value = '0'
  fetchData()
}

function handleWorkflowPageChange(page) {
  workflowPage.value = page
}

async function fetchData() {
  try {
    const timeWindow = buildTimeWindowParams()
    const [summaryRes, workflowsRes, tracesRes] = await Promise.all([
      tracesApi.getSummary(buildSummaryParams(timeWindow)),
      workflowsApi.list({ include_builtin: true, time_range: timeRange.value }),
      tracesApi.list(buildTraceParams(timeWindow)),
    ])

    const scopedWorkflows = filterWorkflows(workflowsRes.workflows || [])
    const success = summaryRes?.success || 0
    const error = summaryRes?.error || 0
    const completed = success + error

    stats.value = {
      workflow_count: scopedWorkflows.length,
      execution_count: summaryRes?.total || 0,
      success_rate: completed > 0 ? (success / completed * 100) : 0,
      avg_duration_ms: summaryRes?.avg_duration_ms,
      running_count: summaryRes?.running || 0,
    }
    workflows.value = scopedWorkflows
    if (!workflowPageTabs.value.find(tab => tab.name === workflowPage.value)) {
      workflowPage.value = '0'
    }
    recentTraces.value = tracesRes.traces || []
  } catch (e) {
    console.error('Failed to fetch dashboard data:', e)
  }
}

function handleTimeChange(value) {
  timeRange.value = value || '24h'
  workflowPage.value = '0'
  fetchData()
}

function handleRefresh() {
  if (currentTab.value === 'traces') {
    traceRefreshKey.value += 1
    return
  }
  fetchData()
}

function handleTabChange(tab) {
  if (tab === 'traces') {
    router.push({ path: '/dashboard', query: { ...route.query, tab: 'traces' } })
    return
  }
  router.push({ path: '/dashboard' })
}

onMounted(fetchData)
</script>

<style scoped>
.overview-toolbar {
  margin-bottom: 16px;
}

.dashboard-page {
  min-width: 0;
}

.overview-toolbar-space {
  width: 100%;
  min-width: 0;
}

.table-scroll {
  width: 100%;
  min-width: 0;
  overflow-x: auto;
}

.workflow-page-tabs {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border-color, #eceff3);
  overflow-x: auto;
}

.workflow-page-tab {
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 500;
  padding: 8px 12px;
  border-radius: 8px;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.2s ease;
}

.workflow-page-tab:hover {
  color: var(--text-color, #101828);
  background: rgba(16, 24, 40, 0.04);
}

.workflow-page-tab.active {
  color: var(--primary-color, #18a058);
  background: rgba(24, 160, 88, 0.10);
}

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

@media (max-width: 1024px) {
  .overview-toolbar-space {
    align-items: stretch !important;
  }

  .overview-toolbar-space :deep(.n-text) {
    min-width: 0;
    overflow-wrap: anywhere;
  }

  .overview-toolbar-space :deep(.n-select) {
    width: 100% !important;
  }
}
</style>
