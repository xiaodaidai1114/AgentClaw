<template>
  <div class="channels-page">
    <PageHeader :title="t('channels.title')">
      <template #actions>
        <n-button v-if="currentTab === 'config'" type="primary" @click="openCreate" size="small">+ {{ t('channels.create') }}</n-button>
      </template>
    </PageHeader>

    <n-tabs :value="currentTab" type="line" animated style="margin-bottom: 16px;" @update:value="handleTabChange">
      <n-tab-pane name="config" :tab="t('channels.config')">
        <div class="stat-grid" style="margin-bottom: 16px;">
          <n-card size="small"><n-statistic :label="t('channels.total')" :value="channels.length" /></n-card>
          <n-card size="small"><n-statistic :label="t('channels.running')" :value="runningCount" /></n-card>
          <n-card size="small"><n-statistic :label="t('channels.stopped')" :value="channels.length - runningCount" /></n-card>
          <n-card size="small"><n-statistic :label="t('channels.types')" :value="typeCount" /></n-card>
        </div>

        <n-card class="channel-filter-card" size="small" style="margin-bottom: 16px;">
          <n-space class="channel-filter-space" :size="12" align="center">
            <n-input v-model:value="searchText" :placeholder="t('channels.searchPlaceholder')" clearable style="width: 280px;" size="small" />
            <n-select v-model:value="filterType" :options="typeFilterOptions" :placeholder="t('channels.allTypes')" clearable style="width: 140px;" size="small" />
          </n-space>
        </n-card>

        <n-card class="table-card">
          <div class="table-scroll">
            <n-data-table :columns="columns" :data="filteredChannels" :loading="loading" :bordered="false" :row-key="r => r.id" size="small" scroll-x="max-content" />
          </div>
        </n-card>
      </n-tab-pane>
      <n-tab-pane name="logs" :tab="t('channels.logs')">
        <ChannelLogs :embedded="true" :key="`${route.fullPath}:${logRefreshKey}`" />
      </n-tab-pane>
    </n-tabs>

    <!-- 创建/编辑弹窗 -->
    <n-modal v-model:show="modal.visible.value" preset="card"
      :title="modal.isEdit.value ? t('channels.editTitle') : t('channels.createTitle')"
      style="width: 600px; max-width: 90vw;" :mask-closable="false">
      <n-form label-placement="left" label-width="90" :model="modal.form">
        <n-form-item :label="t('channels.fields.name')" required>
          <n-input v-model:value="modal.form.name" :disabled="modal.isEdit.value" :placeholder="t('channels.placeholders.name')" />
        </n-form-item>
        <n-form-item :label="t('channels.fields.type')" required>
          <n-select v-model:value="modal.form.type" :options="typeOptions" :disabled="modal.isEdit.value" :placeholder="t('channels.placeholders.selectPlatform')" @update:value="onTypeChange" />
        </n-form-item>
        <n-form-item :label="t('channels.fields.workflow')" required>
          <n-select v-model:value="modal.form.workflow_id" :options="workflowOptions" :placeholder="t('channels.placeholders.selectWorkflow')" />
        </n-form-item>
        <n-form-item :label="t('channels.fields.inputField')" required>
          <n-input v-model:value="modal.form.user_input_field" :placeholder="t('channels.placeholders.userInputField')" />
        </n-form-item>
        <n-form-item :label="t('channels.fields.threadMode')">
          <n-select v-model:value="modal.form.thread_mode" :options="threadModeOptions" />
        </n-form-item>
        <n-form-item :label="t('channels.fields.enabled')">
          <n-switch v-model:value="modal.form.enabled" />
        </n-form-item>

        <!-- 动态平台配置 -->
        <template v-if="modal.form.type">
          <n-divider style="margin: 8px 0 16px;">{{ t('channels.platformConfig', { type: typeLabel(modal.form.type) }) }}</n-divider>
          <n-form-item v-for="field in activePlatformFields" :key="field.key" :label="field.label" :required="field.required">
            <n-select v-if="field.options" v-model:value="modal.form.config[field.key]" :options="field.options" />
            <n-input v-else v-model:value="modal.form.config[field.key]" :type="field.secret ? 'password' : 'text'"
              show-password-on="click" :placeholder="field.placeholder" />
          </n-form-item>
          <n-text v-if="platformHint" depth="3" style="display: block; font-size: 12px; margin-bottom: 12px;">{{ platformHint }}</n-text>

          <!-- 验证连接 -->
          <n-space v-if="showProbe" align="center" style="margin-bottom: 12px;">
            <n-button @click="probeCredentials" :loading="probing" size="small">{{ t('channels.validateConnection') }}</n-button>
            <n-text v-if="probeResult" :type="probeResult.ok ? 'success' : 'error'">
              {{ probeResult.ok ? (probeResult.bot_name || t('channels.connectionSuccess')) : probeResult.error }}
            </n-text>
          </n-space>
        </template>

        <!-- Webhook 地址 -->
        <template v-if="modal.isEdit.value && supportsWebhook(modal.form.type)">
          <n-divider style="margin: 8px 0 16px;">{{ t('channels.webhookInfo') }}</n-divider>
          <n-form-item :label="t('channels.fields.address')">
            <n-space class="webhook-row" align="center" style="width: 100%;">
              <n-text code style="font-size: 12px;">{{ webhookUrl(modal.form.name) }}</n-text>
              <n-button text size="small" @click="copyWebhook(modal.form.name)">{{ $t('common.copy') }}</n-button>
            </n-space>
          </n-form-item>
        </template>
      </n-form>

      <template #action>
        <n-space justify="end">
          <n-button @click="modal.close()">{{ t('common.cancel') }}</n-button>
          <n-button type="primary" @click="submitForm" :loading="saving">{{ modal.isEdit.value ? t('common.save') : t('channels.create') }}</n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>

<script setup>
import { h, ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  NCard, NStatistic, NSpace, NButton, NInput, NSelect,
  NDataTable, NTag, NModal, NForm, NFormItem, NSwitch, NDivider,
  NPopconfirm, NText, useMessage,
  NTabs, NTabPane,
} from 'naive-ui'
import PageHeader from '../components/PageHeader.vue'
import ChannelLogs from './ChannelLogs.vue'
import { channelsApi, workflowsApi } from '../api'
import { useModalForm } from '../composables/useModalForm'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const { t } = useI18n()

const channels = ref([])
const workflows = ref([])
const searchText = ref('')
const filterType = ref(null)
const loading = ref(false)
const saving = ref(false)
const probing = ref(false)
const probeResult = ref(null)
const logRefreshKey = ref(0)

const TYPE_LABELS = computed(() => ({
  feishu: t('channels.feishu'),
  dingtalk: t('channels.dingtalk'),
  wecom: t('channels.wecom'),
  qq: t('channels.qq'),
}))
const typeLabel = (value) => TYPE_LABELS.value[value] || value
const TYPE_TAG_MAP = { feishu: 'info', dingtalk: 'info', wecom: 'success', qq: 'warning' }

const typeFilterOptions = computed(() => [
  { label: TYPE_LABELS.value.feishu, value: 'feishu' },
  { label: TYPE_LABELS.value.dingtalk, value: 'dingtalk' },
  { label: TYPE_LABELS.value.wecom, value: 'wecom' },
  { label: TYPE_LABELS.value.qq, value: 'qq' },
])

const typeOptions = computed(() => [
  { label: TYPE_LABELS.value.feishu, value: 'feishu' },
  { label: TYPE_LABELS.value.dingtalk, value: 'dingtalk' },
  { label: TYPE_LABELS.value.wecom, value: 'wecom' },
  { label: TYPE_LABELS.value.qq, value: 'qq' },
])

const threadModeOptions = computed(() => ([
  { label: t('channels.threadModes.perUser'), value: 'per_user' },
  { label: t('channels.threadModes.perChat'), value: 'per_chat' },
  { label: t('channels.threadModes.shared'), value: 'shared' },
]))

const PLATFORM_FIELDS = computed(() => ({
  feishu: [
    { key: 'app_id', label: t('channels.platform.labels.appId'), required: true, placeholder: t('channels.platform.feishu.appIdPlaceholder') },
    { key: 'app_secret', label: t('channels.platform.labels.appSecret'), required: true, placeholder: t('channels.platform.feishu.appSecretPlaceholder'), secret: true },
    { key: 'domain', label: t('channels.platform.feishu.domain'), options: [{ value: 'feishu', label: t('channels.platform.feishu.domainFeishu') }, { value: 'lark', label: t('channels.platform.feishu.domainLark') }] },
    { key: 'bot_name', label: t('channels.platform.labels.botName'), placeholder: t('channels.platform.feishu.botNamePlaceholder') },
  ],
  dingtalk: [
    { key: 'app_key', label: t('channels.platform.labels.appKey'), required: true, placeholder: t('channels.platform.dingtalk.appKeyPlaceholder') },
    { key: 'app_secret', label: t('channels.platform.labels.appSecret'), required: true, placeholder: t('channels.platform.dingtalk.appSecretPlaceholder'), secret: true },
    { key: 'robot_code', label: t('channels.platform.labels.robotCode'), placeholder: t('channels.platform.dingtalk.robotCodePlaceholder') },
    { key: 'card_template_id', label: t('channels.platform.labels.cardTemplateId'), placeholder: t('channels.platform.dingtalk.cardTemplateIdPlaceholder') },
    { key: 'card_template_key', label: t('channels.platform.labels.cardFieldKey'), placeholder: t('channels.platform.dingtalk.cardTemplateKeyPlaceholder') },
  ],
  wecom: [
    { key: 'mode', label: t('channels.platform.labels.mode'), options: [{ value: 'bot', label: t('channels.platform.wecom.modeBot') }, { value: 'webhook', label: t('channels.platform.wecom.modeWebhook') }] },
    { key: 'bot_id', label: t('channels.platform.labels.botId'), required: true, placeholder: t('channels.platform.wecom.botIdPlaceholder') },
    { key: 'secret', label: t('channels.platform.labels.secret'), required: true, placeholder: t('channels.platform.wecom.secretPlaceholder'), secret: true },
    { key: 'websocket_url', label: t('channels.platform.labels.websocketUrl'), placeholder: t('channels.platform.wecom.websocketUrlPlaceholder') },
    { key: 'webhook_key', label: t('channels.platform.labels.webhookKey'), placeholder: t('channels.platform.wecom.webhookKeyPlaceholder') },
  ],
  qq: [
    { key: 'app_id', label: t('channels.platform.labels.appId'), required: true, placeholder: t('channels.platform.qq.appIdPlaceholder') },
    { key: 'app_secret', label: t('channels.platform.labels.appSecret'), required: true, placeholder: t('channels.platform.qq.appSecretPlaceholder'), secret: true },
  ],
}))

const runningCount = computed(() => channels.value.filter(c => c.running).length)
const typeCount = computed(() => new Set(channels.value.map(c => c.type)).size)

const workflowOptions = computed(() => [
  { label: t('channels.builtinAgent'), value: '__builtin__' },
  ...workflows.value.map(wf => ({ label: wf.id, value: wf.id })),
])

const filteredChannels = computed(() => {
  let list = channels.value
  if (filterType.value) list = list.filter(c => c.type === filterType.value)
  if (searchText.value) {
    const q = searchText.value.toLowerCase()
    list = list.filter(c => c.name.toLowerCase().includes(q) || c.workflow_id.toLowerCase().includes(q))
  }
  return list
})

const currentTab = computed(() => route.query.tab === 'logs' ? 'logs' : 'config')

const activePlatformFields = computed(() => {
  const fields = PLATFORM_FIELDS.value[modal.form.type] || []
  if (modal.form.type !== 'wecom') return fields
  return (modal.form.config.mode || 'bot') === 'webhook'
    ? fields.filter(f => ['mode', 'webhook_key'].includes(f.key))
    : fields
})

const showProbe = computed(() => modal.form.type && modal.form.type !== 'wecom')

const platformHint = computed(() => {
  const type = modal.form.type
  if (type === 'qq') return t('channels.hints.qq')
  if (type !== 'wecom') return ''
  return (modal.form.config.mode || 'bot') === 'webhook'
    ? t('channels.hints.wecomWebhook')
    : t('channels.hints.wecomBot')
})

// --- Modal ---
const modal = useModalForm(() => ({
  id: '', name: '', type: null, workflow_id: '__builtin__',
  user_input_field: 'user_input', thread_mode: 'per_user', enabled: true, config: {},
}))

function openCreate() {
  modal.openCreate()
  probeResult.value = null
}

function openEdit(ch) {
  modal.openEdit({
    id: ch.id, name: ch.name, type: ch.type, workflow_id: ch.workflow_id,
    user_input_field: ch.user_input_field, thread_mode: ch.thread_mode,
    enabled: ch.enabled, config: withPlatformDefaults(ch.type, ch.config),
  })
  probeResult.value = null
}

function onTypeChange() {
  modal.form.config = withPlatformDefaults(modal.form.type, {})
  probeResult.value = null
}

function handleTabChange(tab) {
  if (tab === 'logs') {
    router.push({ path: '/channels', query: { ...route.query, tab: 'logs' } })
    return
  }
  router.push({ path: '/channels' })
}

// --- 平台配置处理 ---
function withPlatformDefaults(type, config = {}) {
  const c = { ...(config || {}) }
  if (type === 'feishu' && !c.domain) c.domain = 'feishu'
  if (type === 'dingtalk') { c.mode = 'stream'; if (!c.card_template_key) c.card_template_key = 'content' }
  if (type === 'wecom' && !c.mode) c.mode = (c.webhook_key && !c.bot_id && !c.secret) ? 'webhook' : 'bot'
  return c
}

function normalizePlatformConfig(type, config = {}) {
  const c = withPlatformDefaults(type, config)
  if (type === 'feishu') return { app_id: c.app_id || '', app_secret: c.app_secret || '', domain: c.domain || 'feishu', bot_name: c.bot_name || '' }
  if (type === 'dingtalk') return { app_key: c.app_key || '', app_secret: c.app_secret || '', robot_code: c.robot_code || '', mode: 'stream', card_template_id: c.card_template_id || '', card_template_key: c.card_template_key || 'content' }
  if (type === 'wecom') {
    if (c.mode === 'webhook') return { mode: 'webhook', webhook_key: c.webhook_key || '' }
    return { mode: 'bot', bot_id: c.bot_id || '', secret: c.secret || '', websocket_url: c.websocket_url || 'wss://openws.work.weixin.qq.com', webhook_key: c.webhook_key || '' }
  }
  if (type === 'qq') return { app_id: c.app_id || '', app_secret: c.app_secret || c.client_secret || '' }
  return c
}

const webhookUrl = (name) => `/api/channels/${name}/webhook`
const supportsWebhook = (type) => !['qq'].includes(type)

async function copyWebhook(name) {
  const url = `${window.location.origin}${webhookUrl(name)}`
  try {
    await navigator.clipboard.writeText(url)
    message.success(t('channels.webhookCopied'))
  } catch {
    message.info(url)
  }
}

// --- 表格列 ---
const columns = computed(() => [
  {
    title: t('channels.columns.channel'), key: 'name', width: 200,
    render: (row) => h('div', null, [
      h('div', { style: 'font-weight: 500;' }, row.name),
      h('div', { style: 'font-size: 12px; color: var(--text-secondary); font-family: monospace;' }, row.id.substring(0, 8) + '...'),
    ]),
  },
  {
    title: t('channels.columns.type'), key: 'type', width: 90,
    render: (row) => h(NTag, { type: TYPE_TAG_MAP[row.type] || 'default', size: 'small', round: true }, { default: () => typeLabel(row.type) }),
  },
  {
    title: t('channels.columns.workflow'), key: 'workflow_id', ellipsis: { tooltip: true },
    render: (row) => h('code', { style: 'font-size: 12px;' }, row.workflow_id),
  },
  {
    title: t('channels.columns.status'), key: 'running', width: 100,
    render: (row) => {
      const type = row.running ? 'success' : (row.enabled ? 'default' : 'warning')
      const label = row.running ? t('channels.running') : (row.enabled ? t('channels.stopped') : t('channels.disabled'))
      return h(NTag, { type, size: 'small', round: true }, { default: () => label })
    },
  },
  {
    title: t('channels.columns.actions'), key: 'actions', width: 220,
    render: (row) => h(NSpace, { size: 8 }, () => [
      h(NButton, { text: true, type: 'primary', size: 'small', onClick: () => openEdit(row) }, { default: () => t('common.edit') }),
      h(NPopconfirm, { onPositiveClick: () => restartChannel(row) }, {
        trigger: () => h(NButton, { text: true, type: 'warning', size: 'small' }, { default: () => t('channels.actions.restart') }),
        default: () => t('channels.confirmRestart', { name: row.name }),
      }),
      h(NButton, {
        text: true,
        size: 'small',
        onClick: () => router.push({ path: '/channels', query: { tab: 'logs', channel_id: row.id } }),
      }, { default: () => t('channels.logs') }),
      h(NPopconfirm, { onPositiveClick: () => doDelete(row) }, {
        trigger: () => h(NButton, { text: true, type: 'error', size: 'small' }, { default: () => t('common.delete') }),
        default: () => t('channels.confirmDelete', { name: row.name }),
      }),
    ]),
  },
])

// --- 数据获取 ---
async function fetchChannels() {
  loading.value = true
  try {
    const [chRes, wfRes] = await Promise.all([channelsApi.list(), workflowsApi.list()])
    channels.value = chRes.channels || []
    workflows.value = (wfRes.workflows || []).filter(w => w.id !== '__builtin__')
  } catch (e) {
    message.error(t('channels.fetchListFailed'))
  } finally {
    loading.value = false
  }
}

// --- 操作 ---
async function submitForm() {
  saving.value = true
  try {
    const cfg = normalizePlatformConfig(modal.form.type, modal.form.config)
    if (modal.isEdit.value) {
      await channelsApi.update(modal.form.id, {
        workflow_id: modal.form.workflow_id, user_input_field: modal.form.user_input_field,
        thread_mode: modal.form.thread_mode, enabled: modal.form.enabled, config: cfg,
      })
      message.success(t('channels.messages.updated', { name: modal.form.name }))
    } else {
      await channelsApi.create({
        name: modal.form.name, type: modal.form.type, workflow_id: modal.form.workflow_id,
        user_input_field: modal.form.user_input_field, thread_mode: modal.form.thread_mode,
        enabled: modal.form.enabled, config: cfg,
      })
      message.success(t('channels.messages.created', { name: modal.form.name }))
    }
    modal.close()
    await fetchChannels()
  } catch (e) {
    message.error(e.response?.data?.detail || e.message || t('channels.messages.operationFailed'))
  } finally {
    saving.value = false
  }
}

async function restartChannel(ch) {
  try {
    await channelsApi.restart(ch.id)
    message.success(t('channels.messages.restarted', { name: ch.name }))
    await fetchChannels()
  } catch (e) {
    message.error(e.response?.data?.detail || t('channels.messages.restartFailed'))
  }
}

async function doDelete(ch) {
  try {
    await channelsApi.delete(ch.id)
    message.success(t('channels.messages.deleted'))
    await fetchChannels()
  } catch (e) {
    message.error(e.response?.data?.detail || t('channels.messages.deleteFailed'))
  }
}

async function probeCredentials() {
  probing.value = true
  probeResult.value = null
  try {
    probeResult.value = await channelsApi.probe({ type: modal.form.type, config: modal.form.config })
  } catch (e) {
    probeResult.value = { ok: false, error: e.response?.data?.detail || e.message }
  } finally {
    probing.value = false
  }
}

onMounted(fetchChannels)
</script>

<style scoped>
.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}

.channels-page {
  min-width: 0;
}

.channel-filter-card,
.table-card {
  min-width: 0;
}

.channel-filter-space {
  min-width: 0;
}

.table-scroll {
  width: 100%;
  min-width: 0;
  overflow-x: auto;
}

.webhook-row {
  min-width: 0;
  flex-wrap: wrap;
}

.webhook-row :deep(.n-text) {
  min-width: 0;
  overflow-wrap: anywhere;
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
  .channel-filter-space {
    width: 100%;
  }

  .channel-filter-space :deep(.n-input),
  .channel-filter-space :deep(.n-select) {
    width: 100% !important;
  }
}
</style>
