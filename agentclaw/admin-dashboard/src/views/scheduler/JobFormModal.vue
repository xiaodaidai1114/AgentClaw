<template>
  <n-modal :show="visible" @update:show="v => !v && $emit('close')" preset="card" :title="t('schedulerJobForm.title')"
    style="width: 640px; max-width: 90vw;" :mask-closable="false">
    <n-steps :current="step" size="small" style="margin-bottom: 20px;">
      <n-step :title="t('schedulerJobForm.steps.basicInfo')" />
      <n-step :title="t('schedulerJobForm.steps.triggerMode')" />
      <n-step :title="t('schedulerJobForm.steps.runtimeConfig')" />
    </n-steps>

    <n-form label-placement="top" :model="form">
      <!-- Step 1: 基本信息 -->
      <template v-if="step === 1">
        <n-form-item :label="t('schedulerJobForm.fields.jobName')" required>
          <n-input v-model:value="form.name" :placeholder="t('schedulerJobForm.placeholders.jobName')" />
        </n-form-item>
        <n-form-item :label="t('schedulerJobForm.fields.workflow')" required>
          <n-select v-model:value="form.workflow_id" :options="workflowOptions" :placeholder="t('schedulerJobForm.placeholders.selectWorkflow')"
            filterable @update:value="onWorkflowChange" />
        </n-form-item>
        <n-form-item :label="t('schedulerJobForm.fields.jobDescription')">
          <n-input v-model:value="form.description" type="textarea" :rows="2" :placeholder="t('schedulerJobForm.placeholders.description')" />
        </n-form-item>
      </template>

      <!-- Step 2: 触发方式 -->
      <template v-if="step === 2">
        <n-space :size="12" style="margin-bottom: 16px;">
          <n-checkbox v-model:checked="form.triggerEnabled.schedule">{{ t('schedulerJobForm.trigger.schedule') }}</n-checkbox>
          <n-checkbox v-model:checked="form.triggerEnabled.webhook">Webhook</n-checkbox>
        </n-space>

        <n-card v-if="form.triggerEnabled.schedule" size="small" style="margin-bottom: 12px;">
          <n-tabs v-model:value="form.trigger.type" type="segment" size="small" style="margin-bottom: 12px;">
            <n-tab name="cron">Cron</n-tab>
            <n-tab name="interval">{{ t('schedulerJobForm.trigger.interval') }}</n-tab>
            <n-tab name="date">{{ t('schedulerJobForm.trigger.oneTime') }}</n-tab>
          </n-tabs>

          <template v-if="form.trigger.type === 'cron'">
            <CronBuilder v-model="form.trigger.expression" />
            <n-form-item :label="t('schedulerJobForm.fields.timezone')" style="margin-top: 12px;">
              <n-select v-model:value="form.trigger.timezone" :options="timezoneOptions" />
            </n-form-item>
          </template>

          <n-grid v-if="form.trigger.type === 'interval'" :cols="3" :x-gap="12">
            <n-gi><n-form-item :label="t('schedulerJobForm.fields.hours')"><n-input-number v-model:value="form.trigger.hours" :min="0" :placeholder="t('schedulerJobForm.placeholders.hours')" /></n-form-item></n-gi>
            <n-gi><n-form-item :label="t('schedulerJobForm.fields.minutes')"><n-input-number v-model:value="form.trigger.minutes" :min="0" :placeholder="t('schedulerJobForm.placeholders.minutes')" /></n-form-item></n-gi>
            <n-gi><n-form-item :label="t('schedulerJobForm.fields.seconds')"><n-input-number v-model:value="form.trigger.seconds" :min="0" :placeholder="t('schedulerJobForm.placeholders.seconds')" /></n-form-item></n-gi>
          </n-grid>

          <n-form-item v-if="form.trigger.type === 'date'" :label="t('schedulerJobForm.fields.executionTime')" required>
            <n-date-picker v-model:value="form.trigger.run_date_ts" type="datetime" style="width: 100%;" />
          </n-form-item>
        </n-card>

        <n-card v-if="form.triggerEnabled.webhook" size="small">
          <template #header><n-text>{{ t('schedulerJobForm.webhook.title') }}</n-text></template>
          <n-form-item :label="t('schedulerJobForm.webhook.secretKey')" required>
            <n-input v-model:value="form.webhook.secret" :placeholder="t('schedulerJobForm.webhook.secretPlaceholder')" />
          </n-form-item>
          <n-checkbox v-model:checked="form.webhook.allow_input_override">{{ t('schedulerJobForm.webhook.allowInputOverride') }}</n-checkbox>
          <n-text depth="3" style="display: block; font-size: 12px; margin-top: 4px;">
            {{ t('schedulerJobForm.webhook.overrideHint') }}
          </n-text>
        </n-card>
      </template>

      <!-- Step 3: 运行配置 -->
      <template v-if="step === 3">
        <!-- 动态输入表单 -->
        <template v-if="currentFormConfig.length">
          <n-text depth="3" strong style="display: block; margin-bottom: 8px;">{{ t('schedulerJobForm.fields.inputParameters') }}</n-text>
          <n-form-item v-for="field in currentFormConfig" :key="field.name" :label="field.label || field.name" :required="field.required">
            <n-select v-if="field.type === 'select' && field.options" v-model:value="inputFormData[field.name]" :options="field.options.map(o => ({ label: o, value: o }))" />
            <n-switch v-else-if="field.type === 'boolean' || field.type === 'switch'" v-model:value="inputFormData[field.name]" />
            <n-input v-else-if="field.type === 'textarea' || field.type === 'text'" v-model:value="inputFormData[field.name]" type="textarea" :rows="3" />
            <n-input-number v-else-if="field.type === 'number' || field.type === 'integer'" v-model:value="inputFormData[field.name]" :min="field.min" :max="field.max" style="width: 100%;" />
            <n-input v-else v-model:value="inputFormData[field.name]" :placeholder="field.label || field.name" />
          </n-form-item>
        </template>
        <template v-else>
          <n-space justify="space-between" align="center" style="margin-bottom: 8px;">
            <n-text depth="3" strong>{{ t('schedulerJobForm.fields.inputParameters') }}</n-text>
            <n-radio-group v-model:value="inputMode" size="small">
              <n-radio-button value="kv">{{ t('schedulerJobForm.inputMode.keyValue') }}</n-radio-button>
              <n-radio-button value="json">JSON</n-radio-button>
            </n-radio-group>
          </n-space>

          <!-- Key-Value 模式 -->
          <template v-if="inputMode === 'kv'">
            <div v-for="(pair, idx) in kvPairs" :key="idx" style="display: flex; gap: 8px; margin-bottom: 8px;">
              <n-input v-model:value="pair.key" :placeholder="t('schedulerJobForm.placeholders.paramName')" style="flex: 1;" size="small" />
              <n-input v-model:value="pair.value" :placeholder="t('schedulerJobForm.placeholders.paramValue')" style="flex: 2;" size="small" />
              <n-button text type="error" size="small" @click="removeKvPair(idx)" :disabled="kvPairs.length <= 1">
                <template #icon><span style="font-size: 14px;">✕</span></template>
              </n-button>
            </div>
            <n-button dashed block size="small" @click="addKvPair" style="margin-bottom: 16px;">+ {{ t('schedulerJobForm.addParameter') }}</n-button>
          </template>

          <!-- JSON 模式 -->
          <template v-else>
            <n-input v-model:value="form.inputsJson" type="textarea" :rows="4"
              placeholder='{"key": "value"}'
              :status="jsonError ? 'error' : undefined"
              style="font-family: monospace; font-size: 13px; margin-bottom: 4px;" />
            <n-text v-if="jsonError" type="error" style="font-size: 12px;">{{ jsonError }}</n-text>
            <div v-else style="height: 18px;" />
          </template>
        </template>

        <n-divider style="margin: 8px 0 16px;" />
        <n-text depth="3" strong style="display: block; margin-bottom: 12px;">{{ t('schedulerJobForm.advancedConfig') }}</n-text>
        <n-grid :cols="3" :x-gap="12">
          <n-gi><n-form-item :label="t('schedulerJobForm.fields.timeoutSeconds')"><n-input-number v-model:value="form.config.timeout" :min="1" style="width: 100%;" /></n-form-item></n-gi>
          <n-gi><n-form-item :label="t('schedulerJobForm.fields.retryCount')"><n-input-number v-model:value="form.config.retry_count" :min="0" style="width: 100%;" /></n-form-item></n-gi>
          <n-gi><n-form-item :label="t('schedulerJobForm.fields.retryIntervalSeconds')"><n-input-number v-model:value="form.config.retry_interval" :min="1" style="width: 100%;" /></n-form-item></n-gi>
        </n-grid>
        <n-form-item :label="t('schedulerJobForm.fields.concurrencyStrategy')">
          <n-select v-model:value="form.config.concurrency" :options="concurrencyOptions" />
        </n-form-item>
      </template>
    </n-form>

    <template #action>
      <n-space justify="space-between" style="width: 100%;">
        <n-button v-if="step > 1" @click="step--">{{ t('schedulerJobForm.previous') }}</n-button>
        <span v-else />
        <n-space>
          <n-button @click="$emit('close')">{{ $t('common.cancel') }}</n-button>
          <n-button v-if="step < 3" type="primary" @click="nextStep" :disabled="!canNext">{{ t('schedulerJobForm.next') }}</n-button>
          <n-button v-else type="primary" @click="handleCreate" :loading="creating">{{ t('schedulerJobForm.createJob') }}</n-button>
        </n-space>
      </n-space>
    </template>
  </n-modal>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  NModal, NForm, NFormItem, NInput, NInputNumber, NSelect, NButton,
  NSpace, NGrid, NGi, NCard, NDivider, NTabs, NTab, NCheckbox,
  NSwitch, NDatePicker, NText, NSteps, NStep, NRadioGroup, NRadioButton,
  useMessage,
} from 'naive-ui'
import CronBuilder from '../../components/CronBuilder.vue'
import { schedulerApi, workflowsApi } from '../../api'

const props = defineProps({
  visible: Boolean,
  workflowIds: { type: Array, default: () => [] },
})

const emit = defineEmits(['close', 'created'])

const message = useMessage()
const { t } = useI18n()
const creating = ref(false)
const step = ref(1)
const inputMode = ref('kv')
const workflowFormConfigs = ref({})
const currentFormConfig = ref([])
const inputFormData = reactive({})
const kvPairs = ref([{ key: '', value: '' }])

const workflowOptions = ref([])

watch(() => props.workflowIds, (ids) => {
  workflowOptions.value = ids.map(id => ({ label: id, value: id }))
}, { immediate: true })

const timezoneOptions = [
  { label: 'Asia/Shanghai', value: 'Asia/Shanghai' },
  { label: 'UTC', value: 'UTC' },
  { label: 'America/New_York', value: 'America/New_York' },
  { label: 'Europe/London', value: 'Europe/London' },
]

const concurrencyOptions = computed(() => ([
  { label: t('schedulerJobForm.concurrency.skip'), value: 'skip' },
  { label: t('schedulerJobForm.concurrency.queue'), value: 'queue' },
  { label: t('schedulerJobForm.concurrency.parallel'), value: 'parallel' },
]))

const defaultForm = () => ({
  name: '',
  workflow_id: null,
  description: '',
  triggerEnabled: { schedule: true, webhook: false },
  trigger: {
    type: 'cron',
    expression: '',
    timezone: 'Asia/Shanghai',
    hours: null,
    minutes: null,
    seconds: null,
    run_date_ts: null,
  },
  webhook: {
    secret: '',
    allow_input_override: true,
  },
  inputsJson: '',
  config: {
    timeout: 300,
    retry_count: 0,
    retry_interval: 60,
    concurrency: 'skip',
  },
})

const form = reactive(defaultForm())

const hasEnabledTrigger = computed(() => form.triggerEnabled.schedule || form.triggerEnabled.webhook)
const hasValidInterval = computed(() => {
  return [form.trigger.hours, form.trigger.minutes, form.trigger.seconds].some(v => Number(v || 0) > 0)
})

const canNext = computed(() => {
  if (step.value === 1) return form.name && form.workflow_id
  if (step.value === 2) return validateTriggerStep(false)
  return true
})

const jsonError = computed(() => {
  if (inputMode.value !== 'json' || !form.inputsJson.trim()) return ''
  try {
    JSON.parse(form.inputsJson)
    return ''
  } catch (e) {
    return t('schedulerJobForm.invalidJson', { message: e.message })
  }
})

watch(() => props.visible, (v) => {
  if (v) {
    Object.assign(form, defaultForm())
    step.value = 1
    inputMode.value = 'kv'
    kvPairs.value = [{ key: '', value: '' }]
    currentFormConfig.value = []
    Object.keys(inputFormData).forEach(k => delete inputFormData[k])
  }
})

function addKvPair() {
  kvPairs.value.push({ key: '', value: '' })
}

function removeKvPair(idx) {
  if (kvPairs.value.length > 1) kvPairs.value.splice(idx, 1)
}

function nextStep() {
  if (step.value === 2 && !validateTriggerStep(true)) return
  if (!canNext.value) return
  step.value++
}

function validateTriggerStep(showMessage = true) {
  const warn = (key) => {
    if (showMessage) message.warning(t(key))
    return false
  }
  if (!hasEnabledTrigger.value) return warn('schedulerJobForm.selectAtLeastOneTrigger')
  if (!form.triggerEnabled.schedule) return warn('schedulerJobForm.scheduleTriggerRequired')
  if (form.trigger.type === 'cron' && !form.trigger.expression) return warn('schedulerJobForm.fillCronExpression')
  if (form.trigger.type === 'interval' && !hasValidInterval.value) return warn('schedulerJobForm.fillInterval')
  if (form.trigger.type === 'date' && !form.trigger.run_date_ts) return warn('schedulerJobForm.fillExecutionTime')
  if (form.triggerEnabled.webhook && !form.webhook.secret.trim()) return warn('schedulerJobForm.webhook.secretRequired')
  return true
}

async function onWorkflowChange() {
  currentFormConfig.value = []
  Object.keys(inputFormData).forEach(k => delete inputFormData[k])
  if (!form.workflow_id) return

  if (workflowFormConfigs.value[form.workflow_id]) {
    applyFormConfig(workflowFormConfigs.value[form.workflow_id])
    return
  }
  try {
    const detail = await workflowsApi.get(form.workflow_id)
    const config = detail.workflow?.form_config || detail.form_config || []
    workflowFormConfigs.value[form.workflow_id] = config
    applyFormConfig(config)
  } catch (e) {
    console.error('获取工作流详情失败:', e)
  }
}

function applyFormConfig(config) {
  currentFormConfig.value = config
  for (const field of config) {
    inputFormData[field.name] = field.default ?? (field.type === 'number' || field.type === 'integer' ? null : '')
  }
}

function buildInputs() {
  if (currentFormConfig.value.length) {
    const inputs = {}
    for (const field of currentFormConfig.value) {
      const val = inputFormData[field.name]
      if (val !== '' && val !== null && val !== undefined) inputs[field.name] = val
    }
    return inputs
  }
  if (inputMode.value === 'kv') {
    const inputs = {}
    for (const pair of kvPairs.value) {
      if (pair.key.trim()) inputs[pair.key.trim()] = pair.value
    }
    return inputs
  }
  if (form.inputsJson.trim()) {
    return JSON.parse(form.inputsJson)
  }
  return {}
}

async function handleCreate() {
  if (!form.name || !form.workflow_id) {
    message.warning(t('schedulerJobForm.fillNameAndWorkflow'))
    return
  }
  if (form.triggerEnabled.schedule && form.trigger.type === 'cron' && !form.trigger.expression) {
    message.warning(t('schedulerJobForm.fillCronExpression'))
    return
  }
  if (form.triggerEnabled.webhook && !form.webhook.secret.trim()) {
    message.warning(t('schedulerJobForm.webhook.secretRequired'))
    return
  }
  if (!validateTriggerStep(true)) return

  let inputs
  try {
    inputs = buildInputs()
  } catch {
    message.error(t('schedulerJobForm.inputJsonInvalid'))
    return
  }

  creating.value = true
  try {
    const trigger = { type: form.trigger.type }
    if (form.trigger.type === 'cron') {
      trigger.expression = form.trigger.expression
      trigger.timezone = form.trigger.timezone
    } else if (form.trigger.type === 'interval') {
      if (form.trigger.hours) trigger.hours = form.trigger.hours
      if (form.trigger.minutes) trigger.minutes = form.trigger.minutes
      if (form.trigger.seconds) trigger.seconds = form.trigger.seconds
    } else if (form.trigger.type === 'date') {
      trigger.run_date = form.trigger.run_date_ts ? new Date(form.trigger.run_date_ts).toISOString() : ''
    }

    const payload = {
      name: form.name,
      workflow_id: form.workflow_id,
      trigger,
      inputs,
      config: { ...form.config },
    }
    if (form.description) payload.description = form.description
    if (form.triggerEnabled.webhook) {
      payload.webhook = {
        enabled: true,
        secret: form.webhook.secret.trim(),
        allow_input_override: form.webhook.allow_input_override,
      }
    }

    await schedulerApi.createJob(payload)
    message.success(t('schedulerJobForm.createSuccess'))
    emit('created')
    emit('close')
  } catch (e) {
    message.error(e.response?.data?.error || e.message || t('schedulerJobForm.createFailed'))
  } finally {
    creating.value = false
  }
}
</script>
