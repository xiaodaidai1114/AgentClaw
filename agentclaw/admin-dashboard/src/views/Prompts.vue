<template>
  <div>
    <PageHeader :title="isScoped ? '' : t('promptsPage.title')" :breadcrumbs="breadcrumbs" :show-refresh="false" />

    <div class="prompt-layout">
      <!-- 左侧: 提示词列表 -->
      <n-card size="small" class="prompt-sidebar">
        <n-space vertical :size="12">
          <n-text v-if="isScoped" depth="3">{{ t('promptsPage.currentAgent') }}: <n-text strong>{{ selectedWorkflowId }}</n-text></n-text>
          <n-select v-else v-model:value="selectedWorkflowId" :options="workflowOptions" :placeholder="t('promptsPage.selectWorkflow')" @update:value="fetchPrompts" />
          <n-input v-model:value="searchQuery" :placeholder="t('promptsPage.searchPrompts')" clearable size="small" />
        </n-space>
        <n-divider style="margin: 12px 0;" />
        <div class="prompt-list">
          <n-list hoverable clickable :show-divider="false">
            <n-list-item v-for="prompt in filteredPrompts" :key="prompt.prompt_key"
              :class="{ 'active-prompt': selectedPrompt?.prompt_key === prompt.prompt_key }"
              @click="selectPrompt(prompt)">
            <n-thing :title="prompt.prompt_key">
              <template #description>
                <n-tag :type="prompt.is_custom ? 'warning' : 'default'" size="tiny">
                    {{ prompt.is_custom ? t('promptsPage.modified') : t('promptsPage.default') }}
                </n-tag>
              </template>
            </n-thing>
          </n-list-item>
        </n-list>
          <n-empty v-if="!filteredPrompts.length" :description="selectedWorkflowId ? t('promptsPage.noPrompts') : t('promptsPage.selectWorkflowFirst')" style="padding: 20px;" />
        </div>
      </n-card>

      <!-- 右侧: 编辑器 -->
      <n-card v-if="selectedPrompt" size="small" class="prompt-editor">
        <template #header>
          <n-space align="center" :size="12">
            <n-text strong>{{ selectedPrompt.prompt_key }}</n-text>
            <n-tag :type="selectedPrompt.is_custom ? 'warning' : 'default'" size="small">
              {{ selectedPrompt.is_custom ? t('promptsPage.modified') : t('promptsPage.default') }}
            </n-tag>
          </n-space>
        </template>
        <template #header-extra>
          <n-space :size="8">
            <n-popconfirm @positive-click="resetPrompt" :disabled="!selectedPrompt.is_custom">
              <template #trigger>
                <n-button size="small" :disabled="!selectedPrompt.is_custom">{{ $t('common.reset') }}</n-button>
              </template>
              {{ t('promptsPage.resetConfirm') }}
            </n-popconfirm>
            <n-button type="primary" size="small" @click="savePrompt" :disabled="!hasChanges">{{ $t('common.save') }}</n-button>
          </n-space>
        </template>

        <n-space v-if="selectedPrompt.variables?.length" align="center" style="margin-bottom: 8px;">
          <n-text depth="3" style="font-size: 12px;">
            {{ t('promptsPage.variables') }}: <n-text code v-for="v in selectedPrompt.variables" :key="v" style="margin-right: 4px;">{{ '{' + v + '}' }}</n-text>
          </n-text>
        </n-space>
        <n-input v-model:value="editContent" type="textarea" :rows="20"
          @input="hasChanges = true"
          style="font-family: monospace; font-size: 13px;" />

        <!-- 差异对比 -->
        <template v-if="selectedPrompt.is_custom">
          <n-divider style="margin: 16px 0 12px;" />
          <n-alert type="warning" :show-icon="false" style="margin-bottom: 8px;">
            <n-space justify="space-between" align="center">
              <n-text>{{ t('promptsPage.diffNotice') }}</n-text>
              <n-button text size="small" @click="showDiff = !showDiff">{{ showDiff ? t('promptsPage.hideDiff') : t('promptsPage.showDiff') }}</n-button>
            </n-space>
          </n-alert>
          <div v-if="showDiff" class="diff-grid">
            <n-card :title="t('promptsPage.defaultContent')" size="small">
              <pre style="margin: 0; white-space: pre-wrap; font-size: 12px;">{{ selectedPrompt.default_content }}</pre>
            </n-card>
            <n-card :title="t('promptsPage.currentContent')" size="small">
              <pre style="margin: 0; white-space: pre-wrap; font-size: 12px;">{{ editContent }}</pre>
            </n-card>
          </div>
        </template>
      </n-card>

      <!-- 未选择提示词 -->
      <n-card v-else class="prompt-editor">
        <n-empty :description="t('promptsPage.selectPromptToEdit')" style="padding: 80px 0;" />
      </n-card>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import {
  NCard, NSpace, NInput, NSelect, NButton, NTag, NText, NDivider,
  NList, NListItem, NThing, NEmpty, NAlert, NPopconfirm,
  useMessage,
} from 'naive-ui'
import PageHeader from '../components/PageHeader.vue'
import { workflowsApi, promptsApi } from '../api'

const route = useRoute()
const message = useMessage()
const { t } = useI18n()
const workflows = ref([])
const prompts = ref([])
const selectedWorkflowId = ref(null)
const selectedPrompt = ref(null)
const searchQuery = ref('')
const editContent = ref('')
const hasChanges = ref(false)
const showDiff = ref(false)

const scopedWorkflowId = computed(() => route.params.id ? String(route.params.id) : '')
const isScoped = computed(() => Boolean(scopedWorkflowId.value))
const breadcrumbs = computed(() => (
  isScoped.value
    ? [
      { text: t('workflows.title'), to: '/workflows' },
      { text: scopedWorkflowId.value, to: `/workflows/${scopedWorkflowId.value}` },
      { text: t('promptsPage.title') },
    ]
    : []
))

const workflowOptions = computed(() =>
  workflows.value.map(wf => ({ label: wf.id, value: wf.id }))
)

const filteredPrompts = computed(() => {
  if (!searchQuery.value) return prompts.value
  const q = searchQuery.value.toLowerCase()
  return prompts.value.filter(p => p.prompt_key.toLowerCase().includes(q) || p.content?.toLowerCase().includes(q))
})

async function fetchWorkflows() {
  try {
    const res = await workflowsApi.list()
    workflows.value = res.workflows.filter(wf => wf.id !== '__builtin__')
  } catch (e) {
    console.error('Failed to fetch workflows:', e)
  }
}

async function fetchPrompts() {
  if (!selectedWorkflowId.value) {
    prompts.value = []
    selectedPrompt.value = null
    return
  }
  try {
    const res = await promptsApi.list(selectedWorkflowId.value)
    prompts.value = res.prompts || []
    selectedPrompt.value = null
  } catch (e) {
    message.error(t('promptsPage.fetchListFailed'))
  }
}

function selectPrompt(prompt) {
  selectedPrompt.value = prompt
  editContent.value = prompt.content || ''
  hasChanges.value = false
  showDiff.value = false
}

async function savePrompt() {
  if (!selectedPrompt.value || !hasChanges.value) return
  try {
    const res = await promptsApi.update(selectedWorkflowId.value, selectedPrompt.value.prompt_key, editContent.value)
    selectedPrompt.value = res
    hasChanges.value = false
    const idx = prompts.value.findIndex(p => p.prompt_key === res.prompt_key)
    if (idx >= 0) prompts.value[idx] = res
    message.success(t('promptsPage.saveSuccess'))
  } catch (e) {
    message.error(e.response?.data?.error || e.message || t('promptsPage.saveFailed'))
  }
}

async function resetPrompt() {
  if (!selectedPrompt.value?.is_custom) return
  try {
    const res = await promptsApi.reset(selectedWorkflowId.value, selectedPrompt.value.prompt_key)
    selectedPrompt.value = res
    editContent.value = res.content
    hasChanges.value = false
    const idx = prompts.value.findIndex(p => p.prompt_key === res.prompt_key)
    if (idx >= 0) prompts.value[idx] = res
    message.success(t('promptsPage.resetSuccess'))
  } catch (e) {
    message.error(e.response?.data?.error || e.message || t('promptsPage.resetFailed'))
  }
}

watch(scopedWorkflowId, async (workflowId) => {
  if (!workflowId) return
  selectedWorkflowId.value = workflowId
  await fetchPrompts()
}, { immediate: true })

onMounted(async () => {
  if (isScoped.value) return
  await fetchWorkflows()
})
</script>

<style scoped>
.prompt-layout {
  display: flex;
  gap: 16px;
  min-height: calc(100vh - 120px);
  min-width: 0;
}

.prompt-sidebar {
  width: 280px;
  flex-shrink: 0;
}

.prompt-list {
  max-height: calc(100vh - 260px);
  overflow-y: auto;
}

.prompt-editor {
  flex: 1;
  min-width: 0;
  overflow: hidden;
}

.active-prompt {
  background: var(--primary-light);
}

.diff-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

@media (max-width: 900px) {
  .prompt-layout {
    flex-direction: column;
    min-height: auto;
  }
  .prompt-sidebar {
    width: 100%;
  }
  .prompt-list {
    max-height: 240px;
  }
  .diff-grid {
    grid-template-columns: 1fr;
  }
}
</style>
