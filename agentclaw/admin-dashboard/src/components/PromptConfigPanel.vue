<template>
  <div class="prompt-layout">
    <aside class="prompt-sidebar">
      <div class="sidebar-title">{{ t('promptConfigPanel.promptList') }}</div>
      <n-input v-model:value="searchQuery" :placeholder="t('promptConfigPanel.search')" clearable size="small" style="margin-bottom: 8px;" />
      <div
        v-for="prompt in filteredPrompts" :key="prompt.prompt_key"
        :class="['prompt-item', { active: selectedPrompt?.prompt_key === prompt.prompt_key }]"
        @click="selectPrompt(prompt)"
      >
        <span class="prompt-name">{{ prompt.prompt_key }}</span>
        <span :class="['prompt-badge', prompt.is_custom ? 'custom' : '']">{{ prompt.is_custom ? t('promptConfigPanel.modified') : t('promptConfigPanel.default') }}</span>
      </div>
      <div v-if="!filteredPrompts.length" class="sidebar-empty">{{ t('promptConfigPanel.noPrompts') }}</div>
    </aside>

    <div class="prompt-editor">
      <template v-if="selectedPrompt">
        <div class="editor-header">
          <div class="editor-title-row">
            <span class="editor-title">{{ selectedPrompt.prompt_key }}</span>
            <span :class="['prompt-badge', selectedPrompt.is_custom ? 'custom' : '']">{{ selectedPrompt.is_custom ? t('promptConfigPanel.modified') : t('promptConfigPanel.default') }}</span>
          </div>
          <div class="editor-actions">
            <n-popconfirm @positive-click="resetPrompt" :disabled="!selectedPrompt.is_custom">
              <template #trigger>
                <n-button size="small" quaternary :disabled="!selectedPrompt.is_custom">{{ $t('common.reset') }}</n-button>
              </template>
              {{ t('promptConfigPanel.resetConfirm') }}
            </n-popconfirm>
            <n-button type="primary" size="small" @click="savePrompt" :disabled="!hasChanges">{{ $t('common.save') }}</n-button>
          </div>
        </div>
        <div v-if="selectedPrompt.variables?.length" class="variables-bar">
          <span class="variables-label">{{ t('promptConfigPanel.variables') }}</span>
          <span v-for="v in selectedPrompt.variables" :key="v" class="variable-tag">{{ '{' + v + '}' }}</span>
        </div>
        <n-input
          v-model:value="editContent"
          type="textarea"
          :rows="20"
          class="prompt-textarea"
          @input="hasChanges = true"
        />
      </template>
      <div v-else class="editor-empty">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#d0d5dd" stroke-width="1.5"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
        <p>{{ t('promptConfigPanel.selectPrompt') }}</p>
      </div>
    </div>
  </div>
</template>
<script setup>
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { NButton, NInput, NPopconfirm, useMessage } from 'naive-ui'
import { promptsApi } from '../api'

const props = defineProps({
  workflowId: { type: String, required: true },
})

const message = useMessage()
const { t } = useI18n()
const prompts = ref([])
const selectedPrompt = ref(null)
const searchQuery = ref('')
const editContent = ref('')
const hasChanges = ref(false)

const filteredPrompts = computed(() => {
  if (!searchQuery.value) return prompts.value
  const q = searchQuery.value.toLowerCase()
  return prompts.value.filter((item) => item.prompt_key.toLowerCase().includes(q) || item.content?.toLowerCase().includes(q))
})

async function fetchPrompts() {
  if (!props.workflowId) return
  try {
    const res = await promptsApi.list(props.workflowId)
    prompts.value = res.prompts || []
    if (prompts.value.length) selectPrompt(prompts.value[0])
    else selectedPrompt.value = null
  } catch (e) {
    message.error(t('promptConfigPanel.fetchFailed'))
  }
}

function selectPrompt(prompt) {
  selectedPrompt.value = prompt
  editContent.value = prompt.content || ''
  hasChanges.value = false
}

async function savePrompt() {
  if (!selectedPrompt.value || !hasChanges.value) return
  try {
    const res = await promptsApi.update(props.workflowId, selectedPrompt.value.prompt_key, editContent.value)
    selectedPrompt.value = res
    editContent.value = res.content || ''
    hasChanges.value = false
    prompts.value = prompts.value.map((item) => item.prompt_key === res.prompt_key ? res : item)
    message.success(t('promptConfigPanel.saved'))
  } catch (e) {
    message.error(e.response?.data?.error || e.message || t('promptConfigPanel.saveFailed'))
  }
}

async function resetPrompt() {
  if (!selectedPrompt.value?.is_custom) return
  try {
    const res = await promptsApi.reset(props.workflowId, selectedPrompt.value.prompt_key)
    selectedPrompt.value = res
    editContent.value = res.content || ''
    hasChanges.value = false
    prompts.value = prompts.value.map((item) => item.prompt_key === res.prompt_key ? res : item)
    message.success(t('promptConfigPanel.resetSuccess'))
  } catch (e) {
    message.error(e.response?.data?.error || e.message || t('promptConfigPanel.resetFailed'))
  }
}

watch(() => props.workflowId, fetchPrompts, { immediate: true })
</script>

<style scoped>
.prompt-layout { display: flex; gap: 20px; min-height: 480px; }

.prompt-sidebar {
  width: 260px; flex-shrink: 0;
  background: #fff; border: 1px solid #eaecf0; border-radius: 12px;
  padding: 12px; overflow-y: auto;
}
.sidebar-title {
  font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;
  color: #98a2b3; padding: 4px 8px 10px; border-bottom: 1px solid #f2f4f7; margin-bottom: 8px;
}
.prompt-item {
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
  padding: 9px 10px; border-radius: 8px; cursor: pointer;
  transition: all 0.12s; font-size: 13px; color: #344054;
}
.prompt-item:hover { background: #f9fafb; }
.prompt-item.active { background: var(--primary-light); color: var(--primary); font-weight: 500; }
.prompt-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.prompt-badge {
  font-size: 10px; padding: 1px 6px; border-radius: 4px;
  background: #f2f4f7; color: #667085; flex-shrink: 0;
}
.prompt-badge.custom { background: #fef3cd; color: #b45309; }
.sidebar-empty { padding: 32px 0; text-align: center; color: #98a2b3; font-size: 13px; }

.prompt-editor { flex: 1; min-width: 0; }
.editor-header {
  display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px;
}
.editor-title-row { display: flex; align-items: center; gap: 8px; }
.editor-title { font-size: 15px; font-weight: 600; color: var(--text-primary); }
.editor-actions { display: flex; gap: 8px; }

.variables-bar {
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
  margin-bottom: 12px; padding: 8px 12px;
  background: #f9fafb; border-radius: 8px;
}
.variables-label { font-size: 12px; color: #98a2b3; margin-right: 4px; }
.variable-tag {
  font-size: 11px; font-family: monospace; padding: 2px 8px;
  background: #fff; border: 1px solid #eaecf0; border-radius: 4px; color: #667085;
}

.prompt-textarea :deep(textarea) {
  font-family: 'SF Mono', 'Fira Code', 'Cascadia Code', monospace;
  font-size: 13px; line-height: 1.6;
}

.editor-empty {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  height: 400px; color: #98a2b3; gap: 12px; font-size: 14px;
}

@media (max-width: 900px) {
  .prompt-layout { flex-direction: column; }
  .prompt-sidebar { width: 100%; }
}
@media (min-width: 901px) and (max-width: 1100px) {
  .prompt-sidebar { width: 220px; }
}
</style>
