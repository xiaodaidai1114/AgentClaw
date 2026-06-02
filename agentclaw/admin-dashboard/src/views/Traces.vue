<template>
  <div class="traces-page">
    <PageHeader v-if="!embedded" :title="t('traces.title')" @refresh="fetchAll" />

    <!-- 统计摘要 -->
    <div class="stat-grid" style="margin-bottom: 20px;">
      <n-card size="small">
        <n-statistic :label="t('traces.total')" :value="summary?.total || 0" />
      </n-card>
      <n-card size="small">
        <n-statistic :label="t('traces.success')">
          <template #default><n-text type="success">{{ summary?.success || 0 }}</n-text></template>
          <template #suffix>
            <n-text depth="3" style="font-size: 12px; margin-left: 4px;">
              {{ summary?.total ? ((summary.success / summary.total) * 100).toFixed(0) + '%' : '' }}
            </n-text>
          </template>
        </n-statistic>
      </n-card>
      <n-card size="small">
        <n-statistic :label="t('traces.failed')">
          <template #default><n-text type="error">{{ summary?.error || 0 }}</n-text></template>
        </n-statistic>
      </n-card>
      <n-card size="small">
        <div class="token-stat">
          <n-text depth="3" class="token-stat__label">{{ t('traces.tokenUsage') }}</n-text>
          <div class="token-stat__total">{{ formatTokens(summary?.total_tokens ?? 0) }}</div>
          <div class="token-stat__meta">
            <n-text depth="3">{{ t('traces.input') }} <n-text type="info" strong>{{ formatTokens(summary?.prompt_tokens ?? 0) }}</n-text></n-text>
            <n-text depth="3">{{ t('traces.output') }} <n-text type="success" strong>{{ formatTokens(summary?.completion_tokens ?? 0) }}</n-text></n-text>
          </div>
        </div>
      </n-card>
      <n-card size="small">
        <n-statistic :label="t('traces.avgDuration')" :value="formatDuration(summary?.avg_duration_ms)" />
      </n-card>
    </div>

    <!-- 过滤器 -->
    <n-card class="trace-filter-card" size="small" style="margin-bottom: 16px;">
      <n-space class="trace-filter-space" :size="12" align="center" wrap>
        <n-select v-model:value="filters.workflow_id" :options="workflowOptions" :placeholder="t('dashboard.allAgents')"
          clearable filterable style="width: 180px;" size="small" @update:value="applyFilters" />
        <n-select v-model:value="filters.status" :options="statusOptions" :placeholder="t('dashboard.status')"
          clearable style="width: 140px;" size="small" @update:value="applyFilters" />
        <n-date-picker v-model:value="filters.time_range" type="datetimerange" :placeholder="t('dashboard.startTime')"
          clearable size="small" style="width: 360px;" @update:value="applyFilters" />
        <n-button size="small" @click="resetFilters">{{ t('common.reset') }}</n-button>
        <n-text v-if="total > 0" depth="3" style="font-size: 13px;">{{ t('common.totalItems', { count: total }) }}</n-text>
      </n-space>
    </n-card>

    <!-- 表格 -->
    <n-card class="trace-table-card">
      <div class="table-scroll">
        <n-data-table :columns="columns" :data="traces" :loading="loading" :bordered="false"
          :row-key="row => row.id" size="small" :row-props="rowProps" scroll-x="max-content" />
      </div>
      <n-pagination
        v-if="total > 0"
        class="trace-pagination"
        v-model:page="page"
        :page-size="limit"
        :item-count="total"
        show-quick-jumper
        :page-sizes="[20, 50, 100]"
        show-size-picker
        @update:page="changePage"
        @update:page-size="changePageSize"
      />
    </n-card>
  </div>
</template>

<script setup>
import { h, ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  NCard, NStatistic, NSpace, NButton, NSelect, NText,
  NDatePicker, NDataTable, NPagination, NTag, NProgress,
} from 'naive-ui'
import PageHeader from '../components/PageHeader.vue'
import { tracesApi, workflowsApi } from '../api'
import { durationBarPercent, formatDateTime, formatDuration, formatTokens } from '../composables/useFormatters'

defineProps({
  embedded: { type: Boolean, default: false },
})

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

const traces = ref([])
const summary = ref(null)
const workflows = ref([])
const loading = ref(false)
const total = ref(0)
const page = ref(1)
const limit = ref(20)

const filters = ref({
  workflow_id: null,
  status: null,
  time_range: null,
})

const workflowOptions = computed(() =>
  workflows.value.map(wf => ({
    label: wf.id === '__builtin__' || wf.is_builtin
      ? `${wf.name || wf.id} (${t('dashboard.builtin')})`
      : (wf.name || wf.id),
    value: wf.id,
  }))
)

const statusOptions = computed(() => [
  { label: t('traces.success'), value: 'success' },
  { label: t('traces.failed'), value: 'error' },
  { label: t('traces.timeout'), value: 'timeout' },
])

const statusMap = computed(() => ({
  success: t('traces.success'),
  error: t('traces.failed'),
  timeout: t('traces.timeout'),
  running: t('traces.running'),
  cancelled: t('traces.cancelled'),
}))
const statusTypeMap = { success: 'success', error: 'error', timeout: 'warning', running: 'info' }

// 基于 summary 平均耗时动态计算颜色
const avgDuration = computed(() => summary.value?.avg_duration_ms || 0)

function durColor(ms) {
  if (ms == null) return 'default'
  const avg = avgDuration.value || 1
  if (ms < avg * 0.5) return 'success'
  if (ms < avg * 1.5) return 'default'
  if (ms < avg * 2.5) return 'warning'
  return 'error'
}

function durPercent(ms) {
  return durationBarPercent(ms, traces.value.map(t => t.duration_ms))
}

const columns = computed(() => [
  {
    title: t('dashboard.traceId'),
    key: 'id',
    width: 170,
    render: (row) => h('a', {
      style: 'font-family: monospace; font-size: 12px; cursor: pointer; color: var(--primary); text-decoration: none;',
      onClick: () => router.push(`/traces/${row.id}`)
    }, row.id.substring(0, 16) + '...')
  },
  {
    title: t('workflows.title'),
    key: 'workflow_id',
    width: 160,
    ellipsis: { tooltip: true },
    render: (row) => h(NText, { strong: true, style: 'font-size: 13px;' }, { default: () => row.workflow_id }),
  },
  {
    title: t('dashboard.status'),
    key: 'status',
    width: 90,
    render: (row) => h(NTag, {
      type: statusTypeMap[row.status] || 'default',
      size: 'small',
      round: true,
    }, { default: () => statusMap.value[row.status] || row.status })
  },
  {
    title: t('traces.avgDuration'),
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
    }
  },
  {
    title: t('traces.token'),
    key: 'total_tokens',
    width: 180,
    render: (row) => {
      const totalTokens = row.total_tokens ?? 0
      const promptTokens = row.prompt_tokens ?? 0
      const completionTokens = row.completion_tokens ?? 0
      return h('div', null, [
        h(NText, { strong: true, style: 'font-size: 13px;' }, { default: () => formatTokens(totalTokens) }),
        h(NText, { depth: 3, style: 'font-size: 11px; margin-left: 4px;' },
          { default: () => t('traces.tokenBreakdown', {
            input: formatTokens(promptTokens),
            output: formatTokens(completionTokens),
          }) }),
      ])
    }
  },
  {
    title: t('dashboard.startTime'),
    key: 'start_time',
    width: 160,
    render: (row) => {
      return formatDateTime(row.start_time)
    }
  },
  {
    title: t('dashboard.actions'),
    key: 'actions',
    width: 80,
    render: (row) => h(NButton, {
      text: true, type: 'primary', size: 'small',
      onClick: () => router.push(`/traces/${row.id}`)
    }, { default: () => t('common.detail') })
  }
])

function rowProps(row) {
  return {
    style: 'cursor: pointer;',
    onClick: () => router.push(`/traces/${row.id}`),
  }
}

function buildQueryParams(includePagination = false) {
  const params = {}
  if (includePagination) {
    params.page = page.value
    params.limit = limit.value
  }
  if (filters.value.workflow_id) params.workflow_id = filters.value.workflow_id
  if (filters.value.status) params.status = filters.value.status
  if (
    Array.isArray(filters.value.time_range) &&
    filters.value.time_range.length === 2 &&
    filters.value.time_range[0] &&
    filters.value.time_range[1]
  ) {
    params.start_time = new Date(filters.value.time_range[0]).toISOString()
    params.end_time = new Date(filters.value.time_range[1]).toISOString()
  }
  return params
}

async function fetchAll() {
  loading.value = true
  try {
    const [tracesRes, summaryRes] = await Promise.all([
      tracesApi.list(buildQueryParams(true)),
      tracesApi.getSummary(buildQueryParams()),
    ])
    traces.value = tracesRes.traces
    total.value = tracesRes.total
    summary.value = summaryRes
  } catch (e) {
    console.error('Failed to fetch traces:', e)
  } finally {
    loading.value = false
  }
}

async function fetchWorkflows() {
  try {
    const res = await workflowsApi.list({ include_builtin: true })
    workflows.value = res.workflows
  } catch (e) {
    console.error('Failed to fetch workflows:', e)
  }
}

function applyFilters() {
  page.value = 1
  fetchAll()
}

function resetFilters() {
  filters.value = { workflow_id: null, status: null, time_range: null }
  page.value = 1
  fetchAll()
}

function changePage(newPage) {
  page.value = newPage
  fetchAll()
}

function changePageSize(newSize) {
  limit.value = newSize
  page.value = 1
  fetchAll()
}

onMounted(() => {
  if (route.query.workflow_id) {
    filters.value.workflow_id = String(route.query.workflow_id)
  }
  fetchAll()
  fetchWorkflows()
})
</script>

<style scoped>
.stat-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 16px;
}

.traces-page {
  min-width: 0;
}

.trace-filter-card,
.trace-table-card {
  min-width: 0;
}

.trace-filter-space {
  min-width: 0;
}

.table-scroll {
  width: 100%;
  min-width: 0;
  overflow-x: auto;
}

.trace-pagination {
  margin-top: 16px;
  justify-content: flex-end;
  flex-wrap: wrap;
}

.token-stat {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 72px;
}

.token-stat__label {
  font-size: 13px;
}

.token-stat__total {
  font-size: 24px;
  font-weight: 700;
  line-height: 1.1;
}

.token-stat__meta {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

@media (max-width: 1200px) {
  .stat-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 640px) {
  .stat-grid {
    grid-template-columns: 1fr;
  }

  .trace-pagination {
    justify-content: flex-start;
  }

  .trace-pagination :deep(.n-pagination-quick-jumper),
  .trace-pagination :deep(.n-pagination-size-picker) {
    display: none;
  }
}

@media (max-width: 1024px) {
  .trace-filter-space {
    width: 100%;
    align-items: stretch !important;
  }

  .trace-filter-space :deep(.n-select),
  .trace-filter-space :deep(.n-date-picker),
  .trace-filter-space :deep(.n-button) {
    width: 100% !important;
  }

  .trace-filter-space :deep(.n-text) {
    min-width: 0;
    overflow-wrap: anywhere;
  }
}
</style>
