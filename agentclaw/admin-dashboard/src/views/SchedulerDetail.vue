<template>
  <div v-if="job">
    <PageHeader :breadcrumbs="breadcrumbs">
      <template #actions>
        <n-button type="primary" size="small" @click="handleTrigger">{{ t('schedulerDetail.runNow') }}</n-button>
        <n-button v-if="job.status === 'enabled'" size="small" @click="handlePause">{{ t('schedulerDetail.pause') }}</n-button>
        <n-button v-if="job.status === 'paused'" size="small" @click="handleResume">{{ t('schedulerDetail.resume') }}</n-button>
        <n-popconfirm @positive-click="handleDelete">
          <template #trigger>
            <n-button size="small" type="error">{{ $t('common.delete') }}</n-button>
          </template>
          {{ t('schedulerDetail.confirmDelete', { name: job.name }) }}
        </n-popconfirm>
      </template>
    </PageHeader>

    <!-- 统计卡片 -->
    <div class="stat-grid" style="margin-bottom: 20px;">
      <n-card size="small"><n-statistic :label="t('schedulerDetail.totalRuns')" :value="job.run_count || 0" /></n-card>
      <n-card size="small">
        <n-statistic :label="t('schedulerDetail.successRate')">
          <template #default>{{ jobSuccessRate.toFixed(1) }}%</template>
        </n-statistic>
      </n-card>
      <n-card size="small"><n-statistic :label="t('schedulerDetail.failedRuns')" :value="job.fail_count || 0" /></n-card>
      <n-card size="small">
        <n-statistic :label="t('schedulerDetail.averageDuration')">
          <template #default>{{ formatDuration(avgDuration) }}</template>
        </n-statistic>
      </n-card>
    </div>

    <!-- 基本配置 -->
    <n-card :title="t('schedulerDetail.basicConfig')" size="small" style="margin-bottom: 20px;">
      <template #header-extra>
        <n-text code depth="3" style="font-size: 11px;">{{ job.id }}</n-text>
      </template>
      <n-descriptions :column="4" label-placement="top" bordered size="small">
        <n-descriptions-item :label="t('schedulerDetail.workflow')">
          <n-tag size="small">{{ job.workflow_id }}</n-tag>
        </n-descriptions-item>
        <n-descriptions-item :label="t('schedulerDetail.statusLabel')">
          <n-tag :type="statusType(job.status)" size="small">{{ statusLabel(job.status) }}</n-tag>
        </n-descriptions-item>
        <n-descriptions-item :label="t('schedulerDetail.nextRun')">
          {{ job.next_run_at ? formatDateTime(job.next_run_at) : t('schedulerDetail.none') }}
        </n-descriptions-item>
        <n-descriptions-item :label="t('schedulerDetail.timeoutSetting')">{{ job.config?.timeout || 300 }}s</n-descriptions-item>
        <n-descriptions-item :label="t('schedulerDetail.retryStrategy')">
          {{ t('schedulerDetail.retryStrategyValue', { count: job.config?.retry_count || 0, interval: job.config?.retry_interval || 60 }) }}
        </n-descriptions-item>
        <n-descriptions-item :label="t('schedulerDetail.concurrencyStrategy')">{{ concurrencyLabel(job.config?.concurrency) }}</n-descriptions-item>
        <n-descriptions-item :label="t('schedulerDetail.createdAt')">{{ formatDateTime(job.created_at) }}</n-descriptions-item>
        <n-descriptions-item v-if="job.last_run_at" :label="t('schedulerDetail.lastRun')">{{ formatDateTime(job.last_run_at) }}</n-descriptions-item>
        <n-descriptions-item v-if="job.inputs && Object.keys(job.inputs).length" :label="t('schedulerDetail.inputParameters')" :span="4">
          <n-text code>{{ JSON.stringify(job.inputs) }}</n-text>
        </n-descriptions-item>
        <n-descriptions-item v-if="job.description" :label="t('common.description')" :span="4">{{ job.description }}</n-descriptions-item>
      </n-descriptions>
    </n-card>

    <!-- 触发方式 -->
    <n-card :title="t('schedulerDetail.triggerMethods')" size="small" style="margin-bottom: 20px;">
      <n-grid :cols="3" :x-gap="16">
        <!-- 定时触发 -->
        <n-gi>
          <n-card size="small" :bordered="true">
            <template #header>
              <n-space justify="space-between" align="center">
                <n-tag :type="triggerTagType(job.trigger.type)" size="small">{{ triggerTypeLabel(job.trigger.type) }}</n-tag>
                <n-tag type="success" size="tiny">{{ t('schedulerDetail.enabled') }}</n-tag>
              </n-space>
            </template>
            <n-descriptions :column="1" label-placement="left" size="small">
              <n-descriptions-item :label="t('schedulerDetail.type')">{{ triggerTypeLabel(job.trigger.type) }}</n-descriptions-item>
              <n-descriptions-item v-if="job.trigger.timezone" :label="t('schedulerDetail.timezone')">{{ job.trigger.timezone }}</n-descriptions-item>
              <n-descriptions-item v-if="job.trigger.expression" :label="t('schedulerDetail.expression')">
                <n-text code>{{ job.trigger.expression }}</n-text>
              </n-descriptions-item>
              <n-descriptions-item v-if="job.trigger.type === 'interval'" :label="t('schedulerDetail.intervalLabel')">
                {{ intervalDescription(job.trigger) }}
              </n-descriptions-item>
              <n-descriptions-item v-if="job.trigger.run_date" :label="t('schedulerDetail.executionTime')">
                {{ formatDateTime(job.trigger.run_date) }}
              </n-descriptions-item>
            </n-descriptions>
          </n-card>
        </n-gi>

        <!-- Webhook -->
        <n-gi>
          <n-card size="small" :bordered="true">
            <template #header>
              <n-space justify="space-between" align="center">
                <n-tag type="info" size="small">Webhook</n-tag>
                <n-tag :type="job.webhook?.enabled ? 'success' : 'default'" size="tiny">
                  {{ job.webhook?.enabled ? t('schedulerDetail.enabled') : t('schedulerDetail.notEnabled') }}
                </n-tag>
              </n-space>
            </template>
            <template v-if="job.webhook?.enabled">
              <n-descriptions :column="1" label-placement="left" size="small">
                <n-descriptions-item label="URL">
                  <n-space align="center" :size="4">
                    <n-text code style="font-size: 11px; word-break: break-all;">{{ webhookUrl }}</n-text>
                    <n-button text size="tiny" @click="copyWebhookUrl">{{ $t('common.copy') }}</n-button>
                  </n-space>
                </n-descriptions-item>
                <n-descriptions-item :label="t('schedulerDetail.secret')">{{ job.webhook.secret ? t('schedulerDetail.set') : t('common.none') }}</n-descriptions-item>
                <n-descriptions-item :label="t('schedulerDetail.secretHeader')">
                  <n-text code style="font-size: 11px;">X-Webhook-Secret</n-text>
                </n-descriptions-item>
                <n-descriptions-item :label="t('schedulerDetail.parameterOverride')">{{ job.webhook.allow_input_override ? t('schedulerDetail.allowed') : t('schedulerDetail.forbidden') }}</n-descriptions-item>
              </n-descriptions>
            </template>
            <n-empty v-else :description="t('schedulerDetail.webhookEmpty')" :show-icon="false" size="small" />
          </n-card>
        </n-gi>

        <!-- 渠道触发 -->
        <n-gi>
          <n-card size="small" :bordered="true">
            <template #header>
              <n-space justify="space-between" align="center">
                <n-tag size="small">{{ t('schedulerDetail.channel') }}</n-tag>
                <n-tag type="default" size="tiny">{{ t('schedulerDetail.comingSoon') }}</n-tag>
              </n-space>
            </template>
            <n-empty :description="t('schedulerDetail.channelPhase2')" :show-icon="false" size="small" />
          </n-card>
        </n-gi>
      </n-grid>
    </n-card>

    <!-- 执行记录 -->
    <n-card :title="t('schedulerDetail.executionRecords')" size="small">
      <template #header-extra>
        <n-space :size="0">
          <n-button v-for="f in execFilterOptions" :key="f.value"
            :type="execFilter === f.value ? 'primary' : 'default'"
            :ghost="execFilter !== f.value"
            size="tiny"
            @click="execFilter = f.value; fetchExecutions()">
            {{ f.label }}
          </n-button>
        </n-space>
      </template>
      <n-data-table
        :columns="execColumns"
        :data="filteredExecutions"
        :bordered="false"
        :loading="execLoading"
        :row-props="execRowProps"
        size="small"
      />
      <n-pagination
          v-if="execTotal > execLimit"
          v-model:page="execPage"
          :page-size="execLimit"
          :item-count="execTotal"
          show-quick-jumper
          :page-sizes="[20, 50, 100]"
          show-size-picker
          @update:page="fetchExecutions"
          @update:page-size="onExecPageSizeChange"
          style="margin-top: 16px; justify-content: flex-end;"
        />
    </n-card>

    <!-- 执行详情抽屉 -->
    <n-drawer v-model:show="execDrawerVisible" :width="600" placement="right">
      <n-drawer-content :title="t('schedulerDetail.executionDetails')" :native-scrollbar="false">
        <template v-if="selectedExec">
          <n-card size="small" style="margin-bottom: 12px;">
            <n-space align="center" :size="16">
              <n-tag :type="execStatusType(selectedExec.status)" size="medium" round>{{ execStatusLabel(selectedExec.status) }}</n-tag>
              <n-text>{{ t('schedulerDetail.duration') }}: <n-text strong>{{ formatDuration(selectedExec.duration_ms) }}</n-text></n-text>
              <n-text depth="3" style="font-size: 11px; font-family: monospace;">{{ selectedExec.id }}</n-text>
            </n-space>
            <n-descriptions :column="2" label-placement="top" size="small" style="margin-top: 12px;">
              <n-descriptions-item :label="t('schedulerDetail.triggerSource')">
                <n-tag :type="triggerSourceType(selectedExec.trigger_source)" size="small">{{ triggerSourceLabel(selectedExec.trigger_source) }}</n-tag>
              </n-descriptions-item>
              <n-descriptions-item :label="t('schedulerDetail.retryCount')">{{ selectedExec.retry_count || 0 }}</n-descriptions-item>
              <n-descriptions-item :label="t('schedulerDetail.startTime')">{{ formatDateTime(selectedExec.started_at) }}</n-descriptions-item>
              <n-descriptions-item :label="t('schedulerDetail.endTime')">{{ selectedExec.ended_at ? formatDateTime(selectedExec.ended_at) : t('schedulerDetail.none') }}</n-descriptions-item>
            </n-descriptions>
          </n-card>

          <n-card v-if="selectedExec.outputs?.answer" size="small" style="margin-bottom: 12px;">
            <template #header>
              <n-space align="center" :size="8">
                <n-text strong style="font-size: 13px;">{{ t('schedulerDetail.output') }}</n-text>
                <n-tag size="tiny" :bordered="false" type="success">{{ t('schedulerDetail.userVisible') }}</n-tag>
              </n-space>
            </template>
            <div style="white-space: pre-wrap; font-size: 13px; line-height: 1.6;">{{ selectedExec.outputs.answer }}</div>
          </n-card>

          <n-card v-if="selectedExec.inputs && Object.keys(selectedExec.inputs).length" size="small" style="margin-bottom: 12px;">
            <template #header><n-text strong style="font-size: 13px;">{{ t('schedulerDetail.inputParameters') }}</n-text></template>
            <n-code :code="JSON.stringify(selectedExec.inputs, null, 2)" language="json" />
          </n-card>

          <n-card v-if="selectedExec.outputs" size="small" style="margin-bottom: 12px;">
            <template #header><n-text strong style="font-size: 13px;">{{ t('schedulerDetail.outputData') }}</n-text></template>
            <n-code :code="JSON.stringify(selectedExec.outputs, null, 2)" language="json" />
          </n-card>

          <n-alert v-if="selectedExec.error" type="error" :title="t('schedulerDetail.errorInfo')" style="margin-bottom: 12px;">
            <pre style="margin: 0; white-space: pre-wrap; font-size: 12px;">{{ selectedExec.error }}</pre>
          </n-alert>

          <n-button v-if="execTraceId" type="primary" size="small" @click="goToTrace">
            {{ t('schedulerDetail.viewTrace') }}
          </n-button>
        </template>
      </n-drawer-content>
    </n-drawer>
  </div>

  <div v-else-if="loading" style="padding: 80px; text-align: center;">
    <n-spin size="large" />
  </div>
  <div v-else-if="loadError" style="padding: 80px; max-width: 720px; margin: 0 auto;">
    <n-alert type="error" :title="t('schedulerDetail.loadFailed')" style="margin-bottom: 16px;">
      {{ loadError }}
    </n-alert>
    <n-space justify="center">
      <n-button type="primary" @click="fetchJob">{{ t('common.refresh') }}</n-button>
    </n-space>
  </div>
  <div v-else style="padding: 80px; text-align: center;">
    <n-empty :description="t('schedulerDetail.jobNotFound')" />
  </div>
</template>

<script setup>
import { h, ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import {
  NCard, NGrid, NGi, NStatistic, NSpace,
  NDescriptions, NDescriptionsItem, NTag, NText, NButton, NDataTable,
  NPopconfirm, NPagination, NSpin, NEmpty, NDrawer, NDrawerContent,
  NCode, NAlert, useMessage,
} from 'naive-ui'
import PageHeader from '../components/PageHeader.vue'
import { schedulerApi } from '../api'
import { formatDuration, formatDateTime } from '../composables/useFormatters'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const { t } = useI18n()
const jobId = route.params.id

const job = ref(null)
const loading = ref(false)
const loadError = ref('')
const executions = ref([])
const execTotal = ref(0)
const execPage = ref(1)
const execLimit = ref(20)
const execLoading = ref(false)
const execFilter = ref('')

const execDrawerVisible = ref(false)
const selectedExec = ref(null)
const breadcrumbs = computed(() => ([
  { text: t('schedulerPage.title'), to: '/scheduler' },
  { text: job.value?.name || String(jobId) },
]))

const execTraceId = computed(() => selectedExec.value?.outputs?.metadata?.trace_id || null)

const execFilterOptions = computed(() => ([
  { label: t('schedulerDetail.filters.all'), value: '' },
  { label: t('schedulerDetail.status.success'), value: 'success' },
  { label: t('schedulerDetail.status.failed'), value: 'failed' },
  { label: t('schedulerDetail.status.timeout'), value: 'timeout' },
]))

const webhookUrl = computed(() => `${window.location.origin}/api/scheduler/jobs/${jobId}/webhook`)

const jobSuccessRate = computed(() => {
  if (!job.value || !job.value.run_count) return 0
  return (job.value.run_count - (job.value.fail_count || 0)) / job.value.run_count * 100
})

const avgDuration = computed(() => {
  if (!executions.value.length) return 0
  const withDuration = executions.value.filter(e => e.duration_ms != null)
  if (!withDuration.length) return 0
  return withDuration.reduce((s, e) => s + e.duration_ms, 0) / withDuration.length
})

const filteredExecutions = computed(() => {
  if (!execFilter.value) return executions.value
  return executions.value.filter(e => e.status === execFilter.value)
})

const execColumns = computed(() => [
  {
    title: t('schedulerDetail.columns.executionId'), key: 'id', width: 130,
    render: (row) => h(NText, { code: true }, () => row.id?.substring(0, 12)),
  },
  {
    title: t('schedulerDetail.columns.triggerSource'), key: 'trigger_source', width: 100,
    render: (row) => {
      const map = { schedule: 'info', manual: 'warning', webhook: 'primary' }
      const src = row.trigger_source || 'schedule'
      return h(NTag, { type: map[src] || 'default', size: 'small' }, () => triggerSourceLabel(src))
    },
  },
  {
    title: t('schedulerDetail.columns.status'), key: 'status', width: 100,
    render: (row) => {
      const map = { success: 'success', failed: 'error', timeout: 'warning', running: 'info', pending: 'default' }
      return h(NTag, { type: map[row.status] || 'default', size: 'small' }, () => execStatusLabel(row.status))
    },
  },
  { title: t('schedulerDetail.columns.startTime'), key: 'started_at', render: (row) => formatDateTime(row.started_at) },
  { title: t('schedulerDetail.columns.duration'), key: 'duration_ms', width: 100, render: (row) => formatDuration(row.duration_ms) },
  { title: t('schedulerDetail.columns.retry'), key: 'retry_count', width: 60, render: (row) => row.retry_count || 0 },
  {
    title: t('schedulerDetail.columns.result'), key: 'result', ellipsis: { tooltip: true },
    render: (row) => {
      if (row.error) return h(NText, { type: 'error' }, () => row.error)
      if (row.outputs) {
        const str = JSON.stringify(row.outputs)
        return str.length > 60 ? str.substring(0, 60) + '...' : str
      }
      return t('schedulerDetail.none')
    },
  },
])

async function fetchJob() {
  loading.value = true
  loadError.value = ''
  try {
    job.value = await schedulerApi.getJob(jobId)
  } catch (e) {
    if (e.response?.status === 404) job.value = null
    else loadError.value = e.response?.data?.error || e.message || t('schedulerDetail.loadFailed')
  } finally {
    loading.value = false
  }
}

async function fetchExecutions() {
  execLoading.value = true
  try {
    const res = await schedulerApi.listExecutions(jobId, { page: execPage.value, limit: execLimit.value })
    executions.value = res.executions || []
    execTotal.value = res.total || 0
  } catch (e) {
    console.error('Failed to fetch executions:', e)
  } finally {
    execLoading.value = false
  }
}

function onExecPageSizeChange(newSize) {
  execLimit.value = newSize
  execPage.value = 1
  fetchExecutions()
}

async function handleTrigger() {
  try {
    await schedulerApi.triggerJob(jobId)
    message.success(t('schedulerDetail.messages.triggered'))
    fetchJob()
    fetchExecutions()
  } catch (e) {
    message.error(t('schedulerDetail.messages.triggerFailed', { error: e.response?.data?.error || e.message }))
  }
}

async function handlePause() {
  try {
    job.value = await schedulerApi.pauseJob(jobId)
    message.success(t('schedulerDetail.messages.paused'))
  } catch (e) {
    message.error(t('schedulerDetail.messages.pauseFailed'))
  }
}

async function handleResume() {
  try {
    job.value = await schedulerApi.resumeJob(jobId)
    message.success(t('schedulerDetail.messages.resumed'))
  } catch (e) {
    message.error(t('schedulerDetail.messages.resumeFailed'))
  }
}

async function handleDelete() {
  try {
    await schedulerApi.deleteJob(jobId)
    message.success(t('schedulerDetail.messages.deleted'))
    router.push('/scheduler')
  } catch (e) {
    message.error(t('schedulerDetail.messages.deleteFailed'))
  }
}

function statusLabel(status) {
  return {
    enabled: t('schedulerDetail.status.enabled'),
    paused: t('schedulerDetail.status.paused'),
    disabled: t('schedulerDetail.status.disabled'),
  }[status] || status
}

function statusType(status) {
  return { enabled: 'success', paused: 'warning', disabled: 'default' }[status] || 'default'
}

function concurrencyLabel(c) {
  return {
    skip: t('schedulerDetail.concurrency.skip'),
    queue: t('schedulerDetail.concurrency.queue'),
    parallel: t('schedulerDetail.concurrency.parallel'),
  }[c] || c || 'skip'
}

function triggerTypeLabel(type) {
  return {
    cron: 'Cron',
    interval: t('schedulerDetail.triggerType.interval'),
    date: t('schedulerDetail.triggerType.date'),
  }[type] || type
}

function triggerTagType(type) {
  return { cron: 'info', interval: 'primary', date: 'warning' }[type] || 'default'
}

function intervalDescription(trigger) {
  const parts = []
  if (trigger.hours) parts.push(t('schedulerDetail.interval.hours', { count: trigger.hours }))
  if (trigger.minutes) parts.push(t('schedulerDetail.interval.minutes', { count: trigger.minutes }))
  if (trigger.seconds) parts.push(t('schedulerDetail.interval.seconds', { count: trigger.seconds }))
  return parts.length ? t('schedulerDetail.interval.every', { value: parts.join(' ') }) : t('schedulerDetail.none')
}

function copyWebhookUrl() {
  navigator.clipboard.writeText(webhookUrl.value).then(() => {
    message.success(t('schedulerDetail.messages.webhookCopied'))
  }).catch(() => {
    message.info(webhookUrl.value)
  })
}

function execStatusType(status) {
  return { success: 'success', failed: 'error', timeout: 'warning', running: 'info', pending: 'default', cancelled: 'default' }[status] || 'default'
}

function execStatusLabel(status) {
  return {
    pending: t('schedulerDetail.status.pending'),
    running: t('schedulerDetail.status.running'),
    success: t('schedulerDetail.status.success'),
    failed: t('schedulerDetail.status.failed'),
    timeout: t('schedulerDetail.status.timeout'),
    cancelled: t('schedulerDetail.status.cancelled'),
  }[status] || status
}

function triggerSourceType(src) {
  return { schedule: 'info', manual: 'warning', webhook: 'primary' }[src] || 'default'
}

function triggerSourceLabel(src) {
  return {
    schedule: t('schedulerDetail.triggerSourceOptions.schedule'),
    manual: t('schedulerDetail.triggerSourceOptions.manual'),
    webhook: 'Webhook',
  }[src] || src
}

function execRowProps(row) {
  return {
    style: 'cursor: pointer;',
    onClick: () => {
      selectedExec.value = row
      execDrawerVisible.value = true
    },
  }
}

function goToTrace() {
  if (execTraceId.value) {
    router.push(`/traces/${execTraceId.value}`)
  }
}

onMounted(() => {
  fetchJob()
  fetchExecutions()
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
