<template>
  <div>
    <PageHeader v-if="!embedded" :title="t('channelLogs.title')" @refresh="fetchData" />

    <!-- 统计栏 -->
    <div class="stat-grid" style="margin-bottom: 20px;">
      <n-card size="small"><n-statistic :label="t('channelLogs.totalMessages')" :value="stats.total" /></n-card>
      <n-card size="small">
        <n-statistic :label="t('channelLogs.success')">
          <template #default><n-text type="success">{{ stats.success }}</n-text></template>
          <template #suffix>
            <n-text depth="3" style="font-size: 12px; margin-left: 4px;">
              {{ stats.total ? ((stats.success / stats.total) * 100).toFixed(0) + '%' : '' }}
            </n-text>
          </template>
        </n-statistic>
      </n-card>
      <n-card size="small"><n-statistic :label="t('channelLogs.failed')"><template #default><n-text type="error">{{ stats.error }}</n-text></template></n-statistic></n-card>
      <n-card size="small">
        <div class="token-stat">
          <n-text depth="3" class="token-stat__label">{{ t('channelLogs.tokenUsage') }}</n-text>
          <div class="token-stat__total">{{ formatTokens(stats.total_tokens ?? 0) }}</div>
          <div class="token-stat__meta">
            <n-text depth="3">{{ t('channelLogs.input') }} <n-text type="info" strong>{{ formatTokens(stats.prompt_tokens ?? 0) }}</n-text></n-text>
            <n-text depth="3">{{ t('channelLogs.output') }} <n-text type="success" strong>{{ formatTokens(stats.completion_tokens ?? 0) }}</n-text></n-text>
          </div>
        </div>
      </n-card>
      <n-card size="small"><n-statistic :label="t('channelLogs.averageResponse')" :value="formatDuration(stats.avg_duration_ms)" /></n-card>
    </div>

    <!-- 筛选栏 -->
    <n-card size="small" style="margin-bottom: 16px;">
      <n-space :size="12" align="center" wrap>
        <n-select v-model:value="filters.channel_id" :options="channelOptions" :placeholder="t('channelLogs.allChannels')"
          clearable filterable style="width: 180px;" size="small" @update:value="applyFilters" />
        <n-select v-model:value="filters.status" :options="statusOptions" :placeholder="t('channelLogs.allStatuses')"
          clearable style="width: 120px;" size="small" @update:value="applyFilters" />
        <n-date-picker v-model:value="filters.time_range" type="datetimerange" :placeholder="t('channelLogs.messageTimeRange')"
          clearable size="small" style="width: 360px;" @update:value="applyFilters" />
        <n-button size="small" @click="resetFilters">{{ $t('common.reset') }}</n-button>
        <n-text depth="3" style="font-size: 13px;">{{ t('common.totalItems', { count: total }) }}</n-text>
      </n-space>
    </n-card>

    <!-- 表格 -->
    <n-card>
      <n-data-table :columns="columns" :data="logs" :loading="loading" :bordered="false"
        :row-key="r => r.id" size="small" :row-props="rowProps" />
      <n-pagination
        v-if="total > limit"
        v-model:page="page"
        :page-size="limit"
        :item-count="total"
        show-quick-jumper
        :page-sizes="[20, 50, 100]"
        show-size-picker
        @update:page="fetchLogs"
        @update:page-size="onPageSizeChange"
        style="margin-top: 16px; justify-content: flex-end;"
      />
    </n-card>

    <!-- 详情抽屉 -->
    <n-drawer v-model:show="drawerVisible" :width="drawerWidth" placement="right">
      <div :style="resizeHandleStyle" @mousedown="onResizeMouseDown" />
      <n-drawer-content :title="selectedLog ? t('channelLogs.logDetails') : ''" :native-scrollbar="false">
        <template v-if="selectedLog">
          <!-- 概览条 -->
          <n-card size="small" style="margin-bottom: 16px;">
            <n-space align="center" :size="16">
              <n-tag :type="statusTagType(selectedLog.status)" size="medium" round>{{ statusText(selectedLog.status) }}</n-tag>
              <n-text>{{ t('channelLogs.channel') }}: <n-text strong>{{ selectedLog.channel_name || '-' }}</n-text></n-text>
              <n-text>{{ t('channelLogs.duration') }}: <n-text strong :type="durClass(selectedLog.duration_ms)">{{ formatDuration(selectedLog.duration_ms) }}</n-text></n-text>
            </n-space>
            <n-progress type="line" :percentage="durPercent(selectedLog.duration_ms)"
              :status="durClass(selectedLog.duration_ms) === 'default' ? undefined : durClass(selectedLog.duration_ms)"
              :show-indicator="false" :height="3" style="margin-top: 8px;" />
          </n-card>

          <n-descriptions :column="1" label-placement="left" bordered size="small" style="margin-bottom: 16px;">
            <n-descriptions-item :label="t('channelLogs.time')">{{ formatDateTime(selectedLog.created_at) }}</n-descriptions-item>
            <n-descriptions-item :label="t('channelLogs.userId')">
              <n-text code>{{ selectedLog.user_id || '-' }}</n-text>
            </n-descriptions-item>
            <n-descriptions-item :label="t('channelLogs.chatOrGroup')">
              <n-text code>{{ selectedLog.chat_id || '-' }}</n-text>
            </n-descriptions-item>
            <n-descriptions-item label="Workflow">
              <n-text code>{{ selectedLog.workflow_id || '-' }}</n-text>
            </n-descriptions-item>
            <n-descriptions-item :label="t('channelLogs.logId')">
              <n-text code style="font-size: 11px;">{{ selectedLog.id }}</n-text>
            </n-descriptions-item>
            <n-descriptions-item v-if="selectedLog.trace_id" label="Trace">
              <n-button text type="primary" size="small" @click="router.push(`/traces/${selectedLog.trace_id}`)">
                {{ selectedLog.trace_id.substring(0, 16) }}...
              </n-button>
            </n-descriptions-item>
          </n-descriptions>

          <n-card size="small" style="margin-bottom: 12px;">
            <template #header>
              <n-space align="center" :size="8">
                <n-text strong style="font-size: 13px;">{{ t('channelLogs.userMessage') }}</n-text>
                <n-tag size="tiny" :bordered="false">{{ t('channelLogs.characters', { count: (selectedLog.message || '').length }) }}</n-tag>
              </n-space>
            </template>
            <n-text style="white-space: pre-wrap; word-break: break-word; font-size: 13px; line-height: 1.6;">
              {{ selectedLog.message || t('channelLogs.emptyMessage') }}
            </n-text>
          </n-card>

          <n-card size="small" style="margin-bottom: 12px;">
            <template #header>
              <n-space align="center" :size="8">
                <n-text strong style="font-size: 13px;">{{ t('channelLogs.botReply') }}</n-text>
                <n-tag size="tiny" :bordered="false">{{ t('channelLogs.characters', { count: (selectedLog.reply || '').length }) }}</n-tag>
              </n-space>
            </template>
            <n-text style="white-space: pre-wrap; word-break: break-word; font-size: 13px; line-height: 1.6;">
              {{ selectedLog.reply || t('channelLogs.noReply') }}
            </n-text>
          </n-card>

          <n-alert v-if="selectedLog.error" type="error" :title="t('channelLogs.errorInfo')">
            <pre style="margin: 0; white-space: pre-wrap; font-size: 12px;">{{ selectedLog.error }}</pre>
          </n-alert>
        </template>
        <n-empty v-else :description="t('channelLogs.selectLogForDetails')" />
      </n-drawer-content>
    </n-drawer>
  </div>
</template>

<script setup>
import { h, computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import {
  NCard, NStatistic, NSpace, NSelect, NText, NTag, NButton, NAlert, NProgress,
  NDatePicker,
  NDataTable, NPagination, NDrawer, NDrawerContent, NDescriptions,
  NDescriptionsItem, NEmpty, useMessage,
} from 'naive-ui'
import PageHeader from '../components/PageHeader.vue'
import { channelsApi } from '../api'
import { durationBarPercent, formatDateTime, formatDate, formatTime, formatDuration, formatTokens } from '../composables/useFormatters'
import { useResizableDrawer } from '../composables/useResizableDrawer'

defineProps({
  embedded: { type: Boolean, default: false },
})

const route = useRoute()
const router = useRouter()
const message = useMessage()
const { t } = useI18n()

const loading = ref(false)
const logs = ref([])
const total = ref(0)
const page = ref(1)
const limit = ref(50)
const selectedLog = ref(null)
const drawerVisible = ref(false)
const { drawerWidth, resizeHandleStyle, onResizeMouseDown } = useResizableDrawer({ initial: 500, min: 360, max: 1000 })
const channelList = ref([])

const stats = reactive({
  total: 0,
  success: 0,
  error: 0,
  timeout: 0,
  avg_duration_ms: 0,
  total_tokens: 0,
  prompt_tokens: 0,
  completion_tokens: 0,
})
const filters = reactive({ channel_id: null, status: null, time_range: null })

const statusOptions = computed(() => ([
  { label: t('channelLogs.status.success'), value: 'success' },
  { label: t('channelLogs.status.error'), value: 'error' },
  { label: t('channelLogs.status.timeout'), value: 'timeout' },
  { label: t('channelLogs.status.cancelled'), value: 'cancelled' },
]))

const channelOptions = computed(() =>
  channelList.value.map(ch => ({ label: ch.name, value: ch.id }))
)

const statusText = (st) => ({
  success: t('channelLogs.status.success'),
  error: t('channelLogs.status.error'),
  timeout: t('channelLogs.status.timeout'),
  cancelled: t('channelLogs.status.cancelled'),
}[st] || st)
const statusTagType = (st) => ({ success: 'success', error: 'error', timeout: 'warning', cancelled: 'warning' }[st] || 'default')

function durClass(ms) {
  if (ms == null) return 'default'
  const avg = stats.avg_duration_ms || 1
  if (ms < avg * 0.5) return 'success'
  if (ms < avg * 1.5) return 'default'
  if (ms < avg * 2.5) return 'warning'
  return 'error'
}

function durPercent(ms) {
  return durationBarPercent(ms, logs.value.map(l => l.duration_ms))
}

const columns = computed(() => [
  {
    title: t('channelLogs.columns.time'), key: 'created_at', width: 140,
    render: (row) => h('div', null, [
      h('div', { style: 'font-size: 12px;' }, formatDate(row.created_at)),
      h('div', { style: 'font-size: 12px; color: var(--text-secondary);' }, row.created_at ? formatTime(row.created_at) : ''),
    ]),
  },
  {
    title: t('channelLogs.columns.channel'), key: 'channel_name', width: 130,
    render: (row) => h('div', null, [
      h('div', { style: 'font-weight: 500;' }, row.channel_name || '-'),
      h('div', { style: 'font-size: 12px; color: var(--text-secondary); font-family: monospace;' },
        row.channel_id ? (row.channel_id.length > 12 ? row.channel_id.slice(0, 12) + '...' : row.channel_id) : '-'),
    ]),
  },
  {
    title: t('channelLogs.columns.status'), key: 'status', width: 80,
    render: (row) => h(NTag, { type: statusTagType(row.status), size: 'small', round: true }, { default: () => statusText(row.status) }),
  },
  {
    title: t('channelLogs.columns.user'), key: 'user_id', width: 120,
    ellipsis: { tooltip: true },
    render: (row) => h('div', null, [
      h('div', { style: 'font-size: 12px; font-family: monospace;' }, row.user_id ? (row.user_id.length > 18 ? row.user_id.slice(0, 18) + '...' : row.user_id) : '-'),
      h('div', { style: 'font-size: 12px; color: var(--text-secondary);' }, row.chat_id ? (row.chat_id.length > 16 ? row.chat_id.slice(0, 16) + '...' : row.chat_id) : t('channelLogs.privateChat')),
    ]),
  },
  {
    title: t('channelLogs.columns.userMessage'), key: 'message', ellipsis: { tooltip: true },
    render: (row) => h('span', { style: row.message ? 'font-size: 13px;' : 'font-size: 13px; color: var(--text-secondary);' }, row.message || t('channelLogs.emptyMessage')),
  },
  {
    title: t('channelLogs.columns.botReply'), key: 'reply', ellipsis: { tooltip: true },
    render: (row) => h('span', { style: row.reply ? 'font-size: 13px;' : 'font-size: 13px; color: var(--text-secondary);' }, row.reply || (row.status === 'timeout' ? t('channelLogs.processingTimeout') : t('channelLogs.noReply'))),
  },
  {
    title: t('channelLogs.columns.duration'), key: 'duration_ms', width: 110,
    render: (row) => {
      const dur = row.duration_ms
      const type = durClass(dur)
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
])

function rowProps(row) {
  return {
    style: 'cursor: pointer;',
    onClick: () => {
      selectedLog.value = row
      drawerVisible.value = true
    },
  }
}

function buildQueryParams(includePagination = false) {
  const params = {}
  if (includePagination) {
    params.page = page.value
    params.limit = limit.value
  }
  if (filters.channel_id) params.channel_id = filters.channel_id
  if (filters.status) params.status = filters.status
  if (
    Array.isArray(filters.time_range) &&
    filters.time_range.length === 2 &&
    filters.time_range[0] &&
    filters.time_range[1]
  ) {
    params.start_time = new Date(filters.time_range[0]).toISOString()
    params.end_time = new Date(filters.time_range[1]).toISOString()
  }
  return params
}

function applyFilters() {
  page.value = 1
  fetchData()
}

function resetFilters() {
  filters.channel_id = null
  filters.status = null
  filters.time_range = null
  page.value = 1
  fetchData()
}

function onPageSizeChange(newSize) {
  limit.value = newSize
  page.value = 1
  fetchData()
}

async function fetchLogs() {
  loading.value = true
  try {
    const res = await channelsApi.getAllLogs(buildQueryParams(true))
    logs.value = res.logs || []
    total.value = res.total || 0
  } catch (e) {
    message.error(t('channelLogs.fetchLogsFailed'))
    logs.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

async function fetchStats() {
  try {
    const res = await channelsApi.getLogStats(buildQueryParams())
    Object.assign(stats, res)
  } catch (e) {
    console.error('Failed to fetch stats:', e)
  }
}

async function fetchChannels() {
  try {
    const res = await channelsApi.list()
    channelList.value = res.channels || []
  } catch (e) {
    console.error('Failed to fetch channels:', e)
  }
}

async function fetchData() {
  await Promise.all([fetchLogs(), fetchStats()])
}

onMounted(async () => {
  if (route.query.channel_id) filters.channel_id = String(route.query.channel_id)
  await fetchChannels()
  await fetchData()
})
</script>

<style scoped>
.stat-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 16px;
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
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
