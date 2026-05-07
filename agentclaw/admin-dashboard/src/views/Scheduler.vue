<template>
  <div>
    <PageHeader :title="t('schedulerPage.title')">
      <template #actions>
        <n-button type="primary" @click="showCreateModal = true" size="small">+ {{ t('schedulerPage.createJob') }}</n-button>
      </template>
    </PageHeader>

    <!-- 统计栏 -->
    <div class="stat-grid" style="margin-bottom: 20px;">
      <n-card size="small">
        <n-statistic :label="t('schedulerPage.totalJobs')" :value="stats.total">
          <template #suffix><n-text depth="3" style="font-size: 12px;"> · {{ t('schedulerPage.enabledCount', { count: stats.enabledCount }) }}</n-text></template>
        </n-statistic>
      </n-card>
      <n-card size="small"><n-statistic :label="t('schedulerPage.todayRuns')" :value="stats.todayExec" /></n-card>
      <n-card size="small">
        <n-statistic :label="t('schedulerPage.successRate')">
          <template #default><n-text :type="stats.successRate >= 90 ? 'success' : 'warning'">{{ stats.successRate }}%</n-text></template>
        </n-statistic>
      </n-card>
      <n-card size="small"><n-statistic :label="t('schedulerPage.averageDuration')" :value="stats.avgDuration" /></n-card>
    </div>

    <!-- 筛选栏 -->
    <n-card size="small" style="margin-bottom: 16px;">
      <n-space :size="12" align="center">
        <n-input v-model:value="searchText" :placeholder="t('schedulerPage.searchPlaceholder')" clearable style="width: 260px;" size="small" />
        <n-select v-model:value="filters.status" :options="statusFilterOptions" :placeholder="t('schedulerPage.allStatuses')"
          clearable style="width: 130px;" size="small" @update:value="fetchJobs" />
        <n-select v-model:value="filterTriggerType" :options="triggerFilterOptions" :placeholder="t('schedulerPage.allTriggerTypes')"
          clearable style="width: 150px;" size="small" />
        <n-select v-model:value="filters.workflow_id" :options="workflowFilterOptions" :placeholder="t('schedulerPage.allWorkflows')"
          clearable style="width: 180px;" size="small" @update:value="fetchJobs" />
      </n-space>
    </n-card>

    <!-- 表格 -->
    <n-card>
      <n-data-table :columns="columns" :data="filteredJobs" :loading="loading" :bordered="false"
        :row-key="r => r.id" size="small" :row-props="rowProps" />
      <n-pagination
        v-if="total > limit"
        v-model:page="page"
        :page-size="limit"
        :item-count="total"
        show-quick-jumper
        :page-sizes="[20, 50, 100]"
        show-size-picker
        @update:page="fetchJobs"
        @update:page-size="onPageSizeChange"
        style="margin-top: 16px; justify-content: flex-end;"
      />
    </n-card>

    <!-- 创建弹窗 -->
    <JobFormModal :visible="showCreateModal" :workflow-ids="workflowIds"
      @close="showCreateModal = false" @created="fetchJobs" />
  </div>
</template>

<script setup>
import { h, ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import {
  NCard, NStatistic, NSpace, NButton, NInput, NSelect,
  NDataTable, NTag, NPagination, NText, NPopconfirm, NProgress,
  useMessage,
} from 'naive-ui'
import PageHeader from '../components/PageHeader.vue'
import JobFormModal from './scheduler/JobFormModal.vue'
import { schedulerApi, workflowsApi } from '../api'
import { formatDateTime } from '../composables/useFormatters'

const router = useRouter()
const message = useMessage()
const { t, locale } = useI18n()

const jobs = ref([])
const total = ref(0)
const loading = ref(false)
const page = ref(1)
const limit = ref(50)
const searchText = ref('')
const filterTriggerType = ref(null)
const workflowIds = ref([])
const showCreateModal = ref(false)

const filters = ref({ status: null, workflow_id: null })

const statusFilterOptions = computed(() => ([
  { label: t('schedulerPage.status.enabled'), value: 'enabled' },
  { label: t('schedulerPage.status.paused'), value: 'paused' },
  { label: t('schedulerPage.status.disabled'), value: 'disabled' },
]))

const triggerFilterOptions = computed(() => ([
  { label: t('schedulerPage.triggerType.schedule'), value: 'schedule' },
  { label: t('schedulerPage.triggerType.webhook'), value: 'webhook' },
]))

const workflowFilterOptions = computed(() =>
  workflowIds.value.map(id => ({ label: id, value: id }))
)

// --- Stats ---
const stats = computed(() => {
  const list = jobs.value
  const totalRuns = list.reduce((s, j) => s + (j.run_count || 0), 0)
  const totalFails = list.reduce((s, j) => s + (j.fail_count || 0), 0)
  return {
    total: total.value,
    enabledCount: list.filter(j => j.status === 'enabled').length,
    todayExec: list.reduce((s, j) => s + (j.today_exec || 0), 0),
    successRate: totalRuns > 0 ? Math.round((totalRuns - totalFails) / totalRuns * 100) : 0,
    avgDuration: list.length > 0
      ? (list.reduce((s, j) => s + (j.avg_duration || 0), 0) / list.length).toFixed(1) + 's'
      : '-',
  }
})

// --- Filtered ---
const filteredJobs = computed(() => {
  let result = jobs.value
  if (searchText.value) {
    const q = searchText.value.toLowerCase()
    result = result.filter(j => j.name.toLowerCase().includes(q) || j.workflow_id.toLowerCase().includes(q))
  }
  if (filterTriggerType.value === 'schedule') {
    result = result.filter(j => j.trigger)
  } else if (filterTriggerType.value === 'webhook') {
    result = result.filter(j => j.webhook?.enabled)
  }
  return result
})

// --- Formatters ---
function triggerDescription(trigger) {
  if (!trigger) return t('schedulerPage.webhookOnly')
  if (trigger.type === 'cron') return trigger.expression || ''
  if (trigger.type === 'interval') {
    const parts = []
    if (trigger.hours) parts.push(t('schedulerPage.interval.hours', { count: trigger.hours }))
    if (trigger.minutes) parts.push(t('schedulerPage.interval.minutes', { count: trigger.minutes }))
    if (trigger.seconds) parts.push(t('schedulerPage.interval.seconds', { count: trigger.seconds }))
    return parts.length ? t('schedulerPage.interval.every', { value: parts.join(' ') }) : t('schedulerPage.interval.label')
  }
  if (trigger.type === 'date' && trigger.run_date) {
    return new Date(trigger.run_date).toLocaleString(locale.value || undefined)
  }
  return ''
}

const statusLabel = (s) => ({
  enabled: t('schedulerPage.status.enabled'),
  paused: t('schedulerPage.status.paused'),
  disabled: t('schedulerPage.status.disabled'),
}[s] || s)
const statusType = (s) => ({ enabled: 'success', paused: 'warning', disabled: 'default' }[s] || 'default')

function successRate(job) {
  if (!job.run_count) return 0
  return Math.round((job.run_count - (job.fail_count || 0)) / job.run_count * 100)
}

function rateType(job) {
  const r = successRate(job)
  if (r >= 95) return 'success'
  if (r >= 80) return 'warning'
  return 'error'
}

function formatNextRun(job) {
  if (job.status === 'paused') return t('schedulerPage.status.paused')
  if (!job.next_run_at) return '-'
  const d = new Date(job.next_run_at)
  const diffMs = d - Date.now()
  if (diffMs < 0) return d.toLocaleString(locale.value || undefined)
  if (diffMs < 3600000) return t('schedulerPage.minutesLater', { count: Math.round(diffMs / 60000) })
  if (diffMs < 86400000) {
    return t('schedulerPage.hoursMinutesLater', {
      hours: Math.floor(diffMs / 3600000),
      minutes: Math.round((diffMs % 3600000) / 60000),
    })
  }
  return d.toLocaleString(locale.value || undefined)
}

// --- Columns ---
const columns = computed(() => [
  {
    title: t('schedulerPage.columns.job'), key: 'name', width: 200,
    render: (row) => h('div', null, [
      h('div', { style: 'font-weight: 500;' }, row.name),
      h('div', { style: 'font-size: 11px; color: var(--text-secondary); font-family: monospace;' },
        `${row.workflow_id} · ${row.id.substring(0, 8)}`),
    ]),
  },
  {
    title: t('schedulerPage.columns.trigger'), key: 'trigger', width: 180,
    render: (row) => h('div', null, [
      h(NSpace, { size: 4, style: 'margin-bottom: 2px;' }, () => [
        row.trigger ? h(NTag, { size: 'tiny', type: 'info', bordered: false }, { default: () => t('schedulerPage.scheduled') }) : null,
        row.webhook?.enabled ? h(NTag, { size: 'tiny', type: 'default', bordered: false }, { default: () => t('schedulerPage.triggerType.webhook') }) : null,
      ]),
      h('div', { style: 'font-size: 11px; color: var(--text-secondary); font-family: monospace;' }, triggerDescription(row.trigger)),
    ]),
  },
  {
    title: t('schedulerPage.columns.status'), key: 'status', width: 90,
    render: (row) => h(NTag, { type: statusType(row.status), size: 'small', round: true }, { default: () => statusLabel(row.status) }),
  },
  {
    title: t('schedulerPage.columns.runs'), key: 'run_count', width: 160,
    render: (row) => {
      if (!row.run_count) return h(NText, { depth: 3, style: 'font-size: 13px;' }, { default: () => t('schedulerPage.noRuns') })
      const rate = successRate(row)
      return h(NSpace, { align: 'center', size: 8 }, () => [
        h(NText, { style: 'font-size: 13px; font-weight: 500;' }, { default: () => t('schedulerPage.runCount', { count: row.run_count }) }),
        h(NProgress, { type: 'line', percentage: rate, status: rateType(row), showIndicator: false, style: 'width: 50px;' }),
        h(NText, { type: rateType(row), style: 'font-size: 11px;' }, { default: () => `${rate}%` }),
      ])
    },
  },
  {
    title: t('schedulerPage.columns.nextRun'), key: 'next_run_at', width: 140,
    render: (row) => h(NText, { depth: 3, style: 'font-size: 12px;' }, { default: () => formatNextRun(row) }),
  },
  {
    title: t('schedulerPage.columns.actions'), key: 'actions', width: 180,
    render: (row) => h(NSpace, { size: 8, onClick: stopRowClick }, () => [
      h(NPopconfirm, { onPositiveClick: () => handleTrigger(row) }, {
        trigger: () => h(NButton, { text: true, type: 'primary', size: 'small', onClick: stopRowClick }, { default: () => t('schedulerPage.actions.run') }),
        default: () => t('schedulerPage.confirmRun', { name: row.name }),
      }),
      row.status === 'enabled'
        ? h(NButton, { text: true, size: 'small', type: 'warning', onClick: (event) => { stopRowClick(event); handlePause(row) } }, { default: () => t('schedulerPage.actions.pause') })
        : null,
      row.status === 'paused'
        ? h(NButton, { text: true, size: 'small', type: 'success', onClick: (event) => { stopRowClick(event); handleResume(row) } }, { default: () => t('schedulerPage.actions.resume') })
        : null,
      h(NPopconfirm, { onPositiveClick: () => handleDelete(row) }, {
        trigger: () => h(NButton, { text: true, type: 'error', size: 'small', onClick: stopRowClick }, { default: () => t('schedulerPage.actions.delete') }),
        default: () => t('schedulerPage.confirmDelete', { name: row.name }),
      }),
    ]),
  },
])

function stopRowClick(event) {
  event?.stopPropagation?.()
}

function rowProps(row) {
  return {
    style: 'cursor: pointer;',
    onClick: () => router.push(`/scheduler/${row.id}`),
  }
}

// --- API ---
function onPageSizeChange(newSize) {
  limit.value = newSize
  page.value = 1
  fetchJobs()
}

async function fetchJobs() {
  loading.value = true
  try {
    const params = { page: page.value, limit: limit.value }
    if (filters.value.status) params.status = filters.value.status
    if (filters.value.workflow_id) params.workflow_id = filters.value.workflow_id
    const res = await schedulerApi.listJobs(params)
    jobs.value = res.jobs
    total.value = res.total
  } catch (e) {
    message.error(t('schedulerPage.fetchJobsFailed'))
  } finally {
    loading.value = false
  }
}

async function fetchWorkflows() {
  try {
    const res = await workflowsApi.list()
    const ids = res.workflows.map(w => w.id)
    if (!ids.includes('__builtin__')) ids.unshift('__builtin__')
    workflowIds.value = ids
  } catch (e) {
    console.error('Failed to fetch workflows:', e)
  }
}

async function handleTrigger(job) {
  try {
    await schedulerApi.triggerJob(job.id)
    message.success(t('schedulerPage.messages.triggered'))
    fetchJobs()
  } catch (e) {
    message.error(e.response?.data?.error || t('schedulerPage.messages.triggerFailed'))
  }
}

async function handlePause(job) {
  try {
    await schedulerApi.pauseJob(job.id)
    message.success(t('schedulerPage.messages.paused'))
    fetchJobs()
  } catch (e) {
    message.error(t('schedulerPage.messages.pauseFailed'))
  }
}

async function handleResume(job) {
  try {
    await schedulerApi.resumeJob(job.id)
    message.success(t('schedulerPage.messages.resumed'))
    fetchJobs()
  } catch (e) {
    message.error(t('schedulerPage.messages.resumeFailed'))
  }
}

async function handleDelete(job) {
  try {
    await schedulerApi.deleteJob(job.id)
    message.success(t('schedulerPage.messages.deleted'))
    fetchJobs()
  } catch (e) {
    message.error(e.response?.data?.error || t('schedulerPage.messages.deleteFailed'))
  }
}

onMounted(() => {
  fetchJobs()
  fetchWorkflows()
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
