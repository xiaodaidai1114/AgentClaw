<template>
  <div class="agent-chat" :class="{ 'public-chat': isPublicMode }">
    <ChatSidebar :conversations="conversations" :activeId="conversationId" v-model:collapsed="sidebarCollapsed" @new-conversation="newConversation" @select="loadConversation" @delete="deleteConversation" />
    <div class="chat-main">
      <div v-if="!isPublicMode" class="top-bar">
        <div class="top-bar-title">{{ workflowName || 'AgentClaw' }}</div>
        <div
          v-if="conversationModels.length"
          class="model-selector"
          role="button"
          tabindex="0"
          :aria-expanded="showModelSelector ? 'true' : 'false'"
          @click="showModelSelector = !showModelSelector"
          @keydown.enter.prevent="showModelSelector = !showModelSelector"
          @keydown.space.prevent="showModelSelector = !showModelSelector"
        >
          <div class="model-dot"></div>
          {{ selectedModelName }}
          <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg>
        </div>
        <div v-if="showModelSelector" class="model-dropdown" @click.stop>
          <div
            v-for="m in conversationModels"
            :key="m.id"
            class="model-option"
            :class="{ active: m.id === selectedModel }"
            role="button"
            tabindex="0"
            @click="selectedModel = m.id; showModelSelector = false"
            @keydown.enter.prevent="selectedModel = m.id; showModelSelector = false"
            @keydown.space.prevent="selectedModel = m.id; showModelSelector = false"
          >{{ m.name || m.id }}</div>
        </div>
      </div>
      <div v-else class="public-header"><h2>{{ workflowName }}</h2><p v-if="workflowDesc">{{ workflowDesc }}</p></div>
      <div class="messages-container" ref="messagesContainer">
        <div v-if="hasFormFields" class="config-panel-wrapper">
          <div class="config-panel">
            <div
              class="config-header"
              role="button"
              tabindex="0"
              :aria-expanded="!configCollapsed ? 'true' : 'false'"
              @click="configCollapsed = !configCollapsed"
              @keydown.enter.prevent="configCollapsed = !configCollapsed"
              @keydown.space.prevent="configCollapsed = !configCollapsed"
            >
              <span>{{ $t('agentChat.configTitle') }}</span>
              <svg class="chevron-icon" :class="{ open: !configCollapsed }" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M9 18l6-6-6-6" />
              </svg>
            </div>
            <div v-if="!configCollapsed" class="config-body">
              <div v-for="field in formFields" :key="field.name" class="form-field" :class="{ invalid: formErrors[field.name] }">
                <label>{{ field.label || field.name }}<span v-if="field.required" class="required-mark">*</span></label>
                <select v-if="field.type === 'select'" v-model="formData[field.name]" :disabled="!formEditable"><option v-for="opt in field.options" :key="opt" :value="opt">{{ opt }}</option></select>
                <div v-else-if="field.type === 'boolean' || field.type === 'switch'" class="switch-wrap"><input type="checkbox" v-model="formData[field.name]" :disabled="!formEditable" /></div>
                <div v-else-if="field.type === 'file-upload' || field.type === 'image-upload' || field.type === 'audio-upload'" class="file-upload-field">
                  <div v-if="formData[field.name]" class="file-uploaded">
                    <span class="file-name">{{ formDataFileNames[field.name] || $t('agentChat.uploaded') }}</span>
                    <button class="file-remove" @click="formData[field.name] = ''; delete formDataFileNames[field.name]" :disabled="!formEditable">&times;</button>
                  </div>
                  <label v-else class="file-upload-btn" :class="{ disabled: !formEditable || isPublicMode || formFieldUploading[field.name] }">
                    <input type="file" :accept="field.type === 'image-upload' ? 'image/*' : field.type === 'audio-upload' ? 'audio/*' : ''" :disabled="!formEditable || isPublicMode || formFieldUploading[field.name]" @change="handleFormFileUpload($event, field.name)" style="display:none" />
                    {{ formFieldUploading[field.name] ? $t('agentChat.uploading') : field.type === 'image-upload' ? $t('agentChat.selectImage') : field.type === 'audio-upload' ? $t('agentChat.selectAudio') : $t('agentChat.selectFile') }}
                  </label>
                </div>
                <div v-else-if="field.type === 'files-upload'" class="files-upload-field">
                  <div v-if="formData[field.name] && formData[field.name].length" class="files-list">
                    <div v-for="(file, fi) in formData[field.name]" :key="fi" class="file-uploaded">
                      <span class="file-name">{{ file.original_name }}</span>
                      <button class="file-remove" @click="formData[field.name].splice(fi, 1)" :disabled="!formEditable">&times;</button>
                    </div>
                  </div>
                  <label class="file-upload-btn" :class="{ disabled: !formEditable || isPublicMode || formFieldUploading[field.name] }">
                    <input type="file" multiple :disabled="!formEditable || isPublicMode || formFieldUploading[field.name]" @change="handleFormFilesUpload($event, field.name)" style="display:none" />
                    {{ formFieldUploading[field.name] ? $t('agentChat.uploading') : $t('agentChat.addFiles') }}
                  </label>
                </div>
                <textarea v-else-if="field.type === 'textarea' || field.type === 'text'" v-model="formData[field.name]" :disabled="!formEditable" rows="3"></textarea>
                <input v-else-if="field.type === 'number' || field.type === 'integer'" type="number" v-model.number="formData[field.name]" :disabled="!formEditable" :min="field.min" :max="field.max" />
                <input v-else type="text" v-model="formData[field.name]" :disabled="!formEditable" :placeholder="field.description || ''" />
                <div v-if="formErrors[field.name]" class="field-error">{{ formErrors[field.name] }}</div>
              </div>
            </div>
          </div>
        </div>
        <div v-if="workflowStartHint" class="form-start-bar">
          <span>{{ workflowStartHint }}</span>
          <button v-if="canStartWorkflow" class="btn-start" @click="startWorkflow">{{ $t('agentChat.startWorkflow') }}</button>
        </div>
        <div v-if="userInputTypeWarning" class="type-warning">{{ userInputTypeWarning }}</div>
        <div v-if="workflowLoadError" class="workflow-error-panel">
          <h3>{{ $t('agentChat.workflowUnavailableTitle') }}</h3>
          <p>{{ workflowLoadError }}</p>
        </div>
        <div v-else-if="messages.length === 0 && !isStreaming" class="welcome-area">
          <div class="welcome-icon-large">AC</div>
          <h3>{{ workflowName || 'AgentClaw' }}</h3>
          <p>{{ workflowDesc || $t('agentChat.welcomeFallback') }}</p>
          <div v-if="canStartWorkflow && !hasFormFields" class="standalone-start-wrapper">
            <button class="btn-start standalone" @click="startWorkflow">{{ $t('agentChat.startWorkflow') }}</button>
          </div>
        </div>
        <div
          v-if="hasHiddenMessages"
          class="show-all-bar"
          role="button"
          tabindex="0"
          @click="showAllMessages = true"
          @keydown.enter.prevent="showAllMessages = true"
          @keydown.space.prevent="showAllMessages = true"
        >
          <span class="show-all-btn mono-font">{{ $t('agentChat.showAllHistory', { count: hiddenCount }) }}</span>
        </div>
        <div v-if="hasProcessMessages" class="chat-display-toolbar">
          <button class="process-toggle-pill" @click="processCollapsed = !processCollapsed">
            <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M4 7h16M4 12h10M4 17h16" />
            </svg>
            <span>{{ processCollapsed ? $t('agentChat.expandProcess') : $t('agentChat.collapseProcess') }}</span>
          </button>
        </div>
        <ChatMessage v-for="(msg, index) in visibleMessages" :key="msg._origIndex != null ? msg._origIndex : index" :msg="msg" :process-collapsed="processCollapsed" :tts-available="ttsAvailable" :tts-state="ttsStateForMessage(msg)" @copy="copyMessage(msg, msg._origIndex != null ? msg._origIndex : index)" @edit="(newText) => editMessage(msg, msg._origIndex != null ? msg._origIndex : index, newText)" @feedback="(type) => feedbackMessage(msg, msg._origIndex != null ? msg._origIndex : index, type)" @toggle-reasoning="toggleReasoning(msg._origIndex != null ? msg._origIndex : index)" @approve="(action) => handleApproval(msg, msg._origIndex != null ? msg._origIndex : index, action)" @toggle-process-view="processCollapsed = !processCollapsed" @speak="speakMessage(msg)" />
        <StreamingMessage v-if="isStreaming || isCompressingContext" :streamingContent="streamingContent" :reasoningContent="reasoningContent" :thinkingStatus="thinkingStatus" :nodeSteps="nodeSteps" :todoItems="todoItems" :process-collapsed="processCollapsed" @toggle-process-view="processCollapsed = !processCollapsed" />
      </div>
      <ChatInput ref="chatInput" v-model="inputText" :placeholder="inputPlaceholder" :enabled="inputEnabled" :isStreaming="isStreaming" :contextDisplay="contextDisplay" :contextUsed="totalContextTokens" :contextLimit="effectiveContextLimit" :canCompressContext="canManualCompressContext" :uploadAvailable="uploadAvailable" :speechInputAvailable="speechInputAvailable" :recording="speechRecording" :attachedFiles="attachedFiles" :inputError="inputError" :inputModes="humanInputModes" @send="sendMessage" @action="submitHumanInputAction" @attach="$refs.fileInput && $refs.fileInput.click()" @speech-input="toggleSpeechInput" @clear="clearCurrentConversation" @remove-file="removeFile" @drop-files="handleDropFiles" @compress-context="manualCompressContext" />
      <input ref="fileInput" type="file" multiple style="display:none" @change="handleFileSelect" />
    </div>
    <div v-if="!isPublicMode" class="info-panel" :class="{ collapsed: infoPanelCollapsed }" :style="infoPanelCollapsed ? {} : { width: infoPanelWidth + 'px' }">
      <button class="info-panel-toggle" @click="infoPanelCollapsed = !infoPanelCollapsed" :title="infoPanelCollapsed ? $t('agentChat.expandPanel') : $t('agentChat.collapsePanel')">
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
          <path :d="infoPanelCollapsed ? 'M15 18l-6-6 6-6' : 'M9 18l6-6-6-6'" />
        </svg>
      </button>
      <div v-if="!infoPanelCollapsed" class="info-panel-resize-handle" @mousedown="onInfoPanelResizeDown"></div>
      <div v-if="!infoPanelCollapsed" class="panel-content">
        <div class="panel-section">
          <div class="section-title">
            <div class="section-title-main">
              <span>{{ $t('agentChat.workflowInfo') }}</span>
            </div>
          </div>
          <div class="section-content">{{ workflowDesc || $t('workflows.noDescription') }}</div>
        </div>
        <div v-if="isBuiltin" class="panel-section">
          <label class="filter-toggle" :title="preFilterEnabled ? $t('agentChat.prefilterDisabledHint') : $t('agentChat.prefilterEnabledHint')">
            <input type="checkbox" v-model="preFilterEnabled" />
            <span>{{ $t('agentChat.prefilter') }}</span>
          </label>
        </div>
        <div class="panel-section">
          <div
            class="section-title collapsible-title"
            role="button"
            tabindex="0"
            :aria-expanded="skillConfigExpanded ? 'true' : 'false'"
            @click="skillConfigExpanded = !skillConfigExpanded"
            @keydown.enter.prevent="skillConfigExpanded = !skillConfigExpanded"
            @keydown.space.prevent="skillConfigExpanded = !skillConfigExpanded"
          >
            <div class="section-title-main">
              <span>{{ $t('agentChat.skillsConfig') }}</span>
              <span v-if="availableSkills.length" class="section-count">{{ enabledSkillsCount }}/{{ availableSkills.length }}</span>
            </div>
            <svg class="chevron-icon" :class="{ open: skillConfigExpanded }" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M9 18l6-6-6-6" />
            </svg>
          </div>
          <div v-if="skillConfigExpanded" class="tool-config-body">
            <div v-if="toolConfigLoading">{{ $t('common.loading') }}</div>
            <template v-else>
              <div v-if="availableSkills.length > 0" class="tool-group-panel">
                <div class="tool-group-header">
                  <span>{{ $t('agentChat.enabledSkills', { enabled: enabledSkillsCount, total: availableSkills.length }) }}</span>
                </div>
                <div class="tool-list">
                  <label v-for="skill in availableSkills" :key="skill.name" class="tool-item" :title="skill.description">
                    <input type="checkbox" :checked="!skill.disabled" @change="toggleSkill(skill)" />
                    <span>{{ skill.name }}</span>
                  </label>
                </div>
              </div>
              <div v-if="availableSkills.length === 0" class="tool-empty">{{ $t('agentChat.noSkills') }}</div>
            </template>
          </div>
        </div>
        <div class="panel-section">
          <div
            class="section-title collapsible-title"
            role="button"
            tabindex="0"
            :aria-expanded="toolConfigExpanded ? 'true' : 'false'"
            @click="toolConfigExpanded = !toolConfigExpanded"
            @keydown.enter.prevent="toolConfigExpanded = !toolConfigExpanded"
            @keydown.space.prevent="toolConfigExpanded = !toolConfigExpanded"
          >
            <div class="section-title-main">
              <span>{{ $t('agentChat.toolsConfig') }}</span>
              <span v-if="allTools.length" class="section-count">{{ enabledToolsCount }}/{{ allTools.length }}</span>
            </div>
            <svg class="chevron-icon" :class="{ open: toolConfigExpanded }" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M9 18l6-6-6-6" />
            </svg>
          </div>
          <div v-if="toolConfigExpanded" class="tool-config-body">
            <div v-if="toolConfigLoading">{{ $t('common.loading') }}</div>
            <template v-else>
              <div v-for="group in toolGroups" :key="group.server" class="tool-group-panel">
                <div class="tool-group-header"><span>{{ group.server }} ({{ group.tools.filter(t => !t.disabled).length }}/{{ group.tools.length }})</span><button class="btn-toggle-all" @click="toggleAllServerTools(group)">{{ group.tools.every(t => !t.disabled) ? $t('agentChat.disableAll') : $t('agentChat.enableAll') }}</button></div>
                <div class="tool-list"><label v-for="tool in group.tools" :key="tool.name" class="tool-item" :title="tool.description"><input type="checkbox" :checked="!tool.disabled" @change="toggleTool(tool)" /><span>{{ tool.name }}</span></label></div>
              </div>
              <div v-if="toolGroups.length === 0" class="tool-empty">{{ $t('agentChat.noTools') }}</div>
              <button v-if="hasDisabledItems" class="btn-reset-tools" @click="resetToolConfig">{{ $t('common.reset') }}</button>
            </template>
          </div>
        </div>
        <div class="panel-section">
          <div class="section-title">
            <div class="section-title-main">
              <span>{{ $t('agentChat.usage') }}</span>
              <span class="section-count">{{ $t('agentChat.messagesCount', { count: messages.length }) }}</span>
            </div>
          </div>
          <div class="section-content">{{ $t('agentChat.sessionRecorded', { count: messages.length }) }}</div>
        </div>
        <div class="panel-section model-permission-section">
          <div class="section-title">
            <div class="section-title-main">
              <span>{{ $t('agentChat.modelPermission') }}</span>
            </div>
          </div>
          <label class="permission-field">
            <span>{{ $t('agentChat.toolSafetyLevel') }}</span>
            <select v-model="toolConfirmationLevel" class="permission-select">
              <option v-for="option in toolConfirmationLevelOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
            </select>
          </label>
          <div class="permission-hint">{{ currentToolPermissionHint }}</div>
        </div>
      </div>
      <div v-if="!infoPanelCollapsed && !isBuiltin" class="panel-actions"><button class="btn-back" @click="goBack">← {{ $t('agentChat.backToWorkflow') }}</button></div>
    </div>
    <ConfirmDialog :visible="confirmDialog.visible" :action="confirmDialog.action" :description="confirmDialog.description" :requireSudo="confirmDialog.requireSudo" :submitting="confirmDialog.submitting" @confirm="(pwd) => submitConfirmDialog(true, pwd)" @cancel="submitConfirmDialog(false)" />
    <ConfirmDialog :visible="compressConfirmDialog.visible" :action="$t('agentChat.compressContextAction')" :description="$t('agentChat.compressContextConfirm')" @confirm="confirmManualCompressContext" @cancel="compressConfirmDialog.visible = false" />
    <ConfirmDialog :visible="clearConversationDialog.visible" :action="$t('agentChat.clearConversationAction')" :description="$t('agentChat.clearConversationConfirm')" @confirm="confirmClearCurrentConversation" @cancel="clearConversationDialog.visible = false" />
    <ConfirmDialog :visible="deleteConversationDialog.visible" :action="$t('agentChat.deleteConversationAction')" :description="$t('agentChat.deleteConversationConfirm')" @confirm="confirmDeleteConversation" @cancel="deleteConversationDialog = { visible: false, conversationId: '' }" />
  </div>
</template>
<script>
import {
  workflowsApi,
  conversationsApi,
  publicConversationsApi,
  publicWorkflowsApi,
  publicAudioApi,
  tasksApi,
  executionApi,
  audioApi,
  buildWorkflowRunInputs,
  getAdminAuthHeaders,
  handleAdminFetchAuthError,
} from '../api'
import ChatSidebar from '../components/chat/ChatSidebar.vue'
import ChatMessage from '../components/chat/ChatMessage.vue'
import ChatInput from '../components/chat/ChatInput.vue'
import StreamingMessage from '../components/chat/StreamingMessage.vue'
import ConfirmDialog from '../components/chat/ConfirmDialog.vue'
import {
  localizeBuiltinRuntimeStep,
  localizeBuiltinRuntimeSteps,
  localizeBuiltinWorkflow,
} from '../utils/builtinWorkflowI18n'
import { logger } from '../utils/logger'
import { isConversationModel } from '../utils/models'
import { agentRunManager } from '../utils/agentRunManager'
import { withReadinessRetry } from '../utils/eventualConsistency'

function getRouteConversationId(vm) {
  const raw = vm?.$route?.query?.conversation_id
  const value = Array.isArray(raw) ? raw[0] : raw
  return typeof value === 'string' && value.trim() ? value.trim() : ''
}

function getRouteSeedInput(vm) {
  const raw = vm?.$route?.query?.seed_input
  const value = Array.isArray(raw) ? raw[0] : raw
  return typeof value === 'string' && value.trim() ? value.trim() : ''
}

function withoutSeedInput(query = {}) {
  const nextQuery = { ...(query || {}) }
  delete nextQuery.seed_input
  return nextQuery
}

function consumeRouteSeedInput(vm) {
  const seedInput = getRouteSeedInput(vm)
  if (seedInput && vm?.$router && vm?.$route) {
    vm.$router.replace({ query: withoutSeedInput(vm.$route.query) })
  }
  return seedInput
}

function makeLocalConversation(vm, conversationId, messages = []) {
  return {
    id: conversationId,
    title: vm?.$t ? vm.$t('agentChat.newConversation') : 'New conversation',
    created_at: Date.now(),
    updated_at: Date.now(),
    messages: Array.isArray(messages) ? messages : [],
  }
}

function ensureLocalConversation(vm, conversationId, messages = []) {
  if (!conversationId) return null
  const existing = (vm.conversations || []).find(c => c.id === conversationId)
  if (existing) return existing
  const conv = makeLocalConversation(vm, conversationId, messages)
  if (!Array.isArray(vm.conversations)) vm.conversations = []
  vm.conversations.unshift(conv)
  vm.saveConversationsToLocal?.()
  return conv
}

function withWorkflowWelcome(vm, messages = []) {
  const normalized = Array.isArray(messages) ? messages : []
  if (normalized.length > 0 || !vm?.workflowWelcome) return normalized
  return [{ role: 'welcome', content: vm.workflowWelcome }]
}

function syncRouteConversationId(vm, conversationId) {
  if (!conversationId || !vm?.$router || !vm?.$route) return
  if (vm.$route.query?.conversation_id !== conversationId) {
    vm.$router.replace({ query: { ...withoutSeedInput(vm.$route.query), conversation_id: conversationId } })
  }
}

function getManagedRunKey(vm, conversationId = vm?.conversationId) {
  return agentRunManager.makeKey({
    isPublicMode: !!vm?.isPublicMode,
    workflowId: vm?.currentWorkflowId,
    conversationId,
  })
}

function generateLocalConversationId() {
  const suffix = [
    Date.now().toString(36),
    Math.random().toString(36).slice(2),
    Math.random().toString(36).slice(2),
  ].join('')
  return `conv_${suffix.padEnd(24, '0').slice(0, 24)}`
}

const RUN_SNAPSHOT_FIELDS = [
  'isStreaming',
  'workflowStatus',
  'streamingContent',
  'reasoningContent',
  'messages',
  'nodeSteps',
  'currentToolCalls',
  'todoItems',
  'thinkingStatus',
  'currentTaskId',
  'streamEndedByWorkflowEvent',
  'currentPromptTokens',
  'currentCompletionTokens',
  'currentContextTokens',
  'approvalMode',
  'humanInputModes',
  'humanWaitingFor',
  'confirmDialog',
  'confirmQueue',
  'processCollapsed',
]

function applyManagedRunSnapshot(vm, snapshot) {
  if (!vm || !snapshot || snapshot.conversationId !== vm.conversationId) return false
  for (const field of RUN_SNAPSHOT_FIELDS) {
    if (snapshot[field] !== undefined) vm[field] = snapshot[field]
  }
  vm.scrollToBottom?.()
  return true
}

function ensureConversationIdForRun(vm) {
  if (typeof vm.conversationId === 'string' && vm.conversationId.trim()) {
    ensureLocalConversation(vm, vm.conversationId)
    syncRouteConversationId(vm, vm.conversationId)
    return vm.conversationId
  }
  const routeConversationId = getRouteConversationId(vm)
  const conversationId = routeConversationId || (typeof vm.generateId === 'function'
    ? vm.generateId()
    : generateLocalConversationId())
  vm.conversationId = conversationId
  ensureLocalConversation(vm, conversationId)
  syncRouteConversationId(vm, conversationId)
  return conversationId
}

export default {
  name: 'AgentChat',
  components: { ChatSidebar, ChatMessage, ChatInput, StreamingMessage, ConfirmDialog },
  props: {
    publicMode: { type: Boolean, default: false },
    workflowId: { type: String, default: '' },
    shareToken: { type: String, default: ''},
  },
  data() {
    return {
      currentWorkflowId: '',
      workflowName: '',
      workflowDesc: '',
      workflowWelcome: '',
      chatAudio: null,
      conversationId: '',
      messages: [],
      inputText: '',
      inputError: '',
      inputErrorTimer: null,
      workflowLoadError: '',
      publicSessionReady: false,
      isStreaming: false,
      streamingContent: '',
      reasoningContent: '',
      conversations: [],
      sidebarCollapsed: false,
      infoPanelCollapsed: false,
      configCollapsed: false,
      infoPanelWidth: 308,
      inputSchema: null,
      formConfig: null,
      userInputFieldName: null,
      formData: {},
      currentToolCalls: [],
      streamingToolsExpanded: false,
      thinkingStatus: null,
      abortController: null,
      currentTaskId: null,
      workflowStatus: 'idle',
      streamEndedByWorkflowEvent: false,
      isInitializing: true,
      conversationLoadSeq: 0,
      nodeSteps: [],
      todoItems: [],
      skillConfigExpanded: false,
      toolConfigExpanded: false,
      toolConfigLoading: false,
      availableSkills: [],
      toolGroups: [],
      toolConfigWarnings: [],
      uploadAvailable: false,
      attachedFiles: [],
      uploading: false,
      formDataFileNames: {},
      formErrors: {},
      formFieldUploading: {},
      inputFocused: false,
      confirmDialog: { visible: false, submitting: false, confirmId: '', action: '', description: '', requireSudo: false, sudoPassword: '' },
      confirmQueue: [],
      compressConfirmDialog: { visible: false },
      clearConversationDialog: { visible: false },
      deleteConversationDialog: { visible: false, conversationId: '' },
      models: [],
      selectedModel: '',
      showModelSelector: false,
      isBuiltin: false,
      preFilterEnabled: false,
      maxContextTokens: 128000,
      selectedToolCall: null,
      showToolDetails: false,
      currentPromptTokens: 0,
      currentCompletionTokens: 0,
      currentContextTokens: 0,
      isCompressingContext: false,
      showAllMessages: false,
      approvalMode: false,
      humanInputModes: null,
      humanWaitingFor: '',
      toolConfirmationLevel: 'off',
      processCollapsed: true,
      runUnsubscribe: null,
      activeRunKey: '',
      lastStreamingDraftPersistAt: 0,
      speechRecording: false,
      speechRecorder: null,
      speechStream: null,
      speechChunks: [],
      ttsAudio: null,
      ttsPlaybackUrl: '',
      ttsMessageKey: '',
      ttsGenerating: false,
      ttsPlaying: false,
    }
  },
  computed: {
    isPublicMode() { return this.publicMode },
    userInputField() {
      if (!this.userInputFieldName || !this.formConfig) return null
      return this.formConfig.find(f => f.name === this.userInputFieldName)
    },
    userInputTypeWarning() {
      if (!this.userInputField) return null
      const type = this.userInputField.type
      if (!['string', 'text', 'textarea', null, undefined].includes(type)) {
        return this.$t('agentChat.userInputTypeWarning', { type })
      }
      return null
    },
    formFields() {
      if (!this.formConfig) return []
      let fields = this.formConfig
      if (this.userInputFieldName) {
        fields = fields.filter(f => f.name !== this.userInputFieldName)
      }
      // model 字段由顶部下拉选择器处理，不在参数面板中重复显示
      if (this.models.length > 0) {
        fields = fields.filter(f => f.name !== 'model')
      }
      return fields
    },
    hasFormFields() { return this.formFields.length > 0 },
    inputEnabled() {
      if (this.workflowLoadError) return false
      if (this.isInitializing || !this.conversationId) return false
      if (!this.userInputFieldName && !(this.workflowStatus === 'interrupted' && this.humanWaitingFor)) return false
      return ['idle', 'interrupted', 'finished', 'cancelled'].includes(this.workflowStatus)
    },
    canManualCompressContext() {
      return !this.isPublicMode && !this.isStreaming && !this.isCompressingContext && !!this.currentWorkflowId && !!this.conversationId && this.messages.length > 0
    },
    normalizedChatAudio() {
      const config = this.chatAudio || {}
      return {
        enabled: !!config.enabled,
        speech_input_enabled: !!config.speech_input_enabled,
        tts_enabled: !!config.tts_enabled,
        speech2text_model_id: config.speech2text_model_id || '',
        tts_model_id: config.tts_model_id || '',
        tts_voice: config.tts_voice || '',
      }
    },
    speechInputAvailable() {
      return this.normalizedChatAudio.enabled && this.normalizedChatAudio.speech_input_enabled
    },
    ttsAvailable() {
      return this.normalizedChatAudio.enabled && this.normalizedChatAudio.tts_enabled
    },
    formEditable() { return this.workflowStatus === 'idle' || this.workflowStatus === 'finished' },
    canSend() { return this.inputEnabled && this.inputText.trim() && !this.inputError },
    canStartWorkflow() {
      if (this.workflowLoadError) return false
      if (this.isInitializing) return false
      if (this.userInputFieldName) return false
      return this.workflowStatus === 'idle' || this.workflowStatus === 'finished'
    },
    workflowStartHint() {
      const hasVisibleFormFields = (this.formFields || []).length > 0
      if (this.userInputFieldName || this.workflowLoadError) return ''
      if (this.isInitializing) return this.$t('common.loading')
      if (this.workflowStatus === 'running') return this.$t('agentChat.workflowRunning')
      if (hasVisibleFormFields && this.canStartWorkflow) return this.$t('agentChat.formOnlyWorkflowHint')
      return ''
    },
    inputPlaceholder() {
      if (this.workflowLoadError) return this.$t('agentChat.workflowUnavailable')
      if (this.isInitializing) return this.$t('common.loading')
      if (!this.userInputFieldName) {
        const hasVisibleFormFields = (this.formFields || []).length > 0
        return hasVisibleFormFields ? this.$t('agentChat.formOnlyInputPlaceholder') : this.$t('agentChat.noUserInput')
      }
      if (this.workflowStatus === 'running') return this.$t('agentChat.workflowRunning')
      if (this.workflowStatus === 'interrupted') {
        return this.approvalMode ? this.$t('agentChat.approvalFeedbackOptional') : this.$t('agentChat.continueInput')
      }
      if (this.workflowStatus === 'finished') return this.$t('agentChat.startNewRound')
      const field = this.userInputField
      return field?.label || this.$t('agentChat.enterQuestion')
    },
    hasFormConfig() { return this.formConfig && this.formConfig.length > 0 },
    convApi() { return this.isPublicMode ? publicConversationsApi : conversationsApi },
    enabledSkillsCount() { return this.availableSkills.filter(s => !s.disabled).length },
    allTools() { return this.toolGroups.flatMap(g => g.tools) },
    enabledToolsCount() { return this.allTools.filter(t => !t.disabled).length },
    hasDisabledItems() { return this.availableSkills.some(s => s.disabled) || this.allTools.some(t => t.disabled) },
    conversationModels() { return this.models.filter(isConversationModel) },
    selectedModelName() {
      if (!this.selectedModel) return ''
      const m = this.conversationModels.find(m => m.id === this.selectedModel)
      return m ? (m.name || m.id) : this.selectedModel
    },
    toolConfirmationRequired() { return this.toolConfirmationLevel !== 'off' },
    toolConfirmationLevelOptions() {
      return [
        { value: 'off', label: this.$t('agentChat.permissionOff') },
        { value: 'high', label: this.$t('agentChat.permissionHigh') },
        { value: 'medium', label: this.$t('agentChat.permissionMedium') },
        { value: 'low', label: this.$t('agentChat.permissionLow') },
      ]
    },
    currentToolPermissionHint() {
      return this.$t(`agentChat.permissionHint.${this.toolConfirmationLevel}`)
    },
    totalContextTokens() {
      // 运行期间优先显示当前会话上下文长度，避免刚追加 user 消息后退回到 usage 累加值
      if (this.currentContextTokens > 0) return this.currentContextTokens

      // 使用最近一条带 context_tokens 的消息（会话级别上下文 token 数）
      // 如果最后一条是新 user 消息，它通常还没有 context_tokens，不能因此降级到 usage 累加
      for (let i = this.messages.length - 1; i >= 0; i--) {
        const tokens = Number(this.messages[i]?.context_tokens || 0)
        if (tokens > 0) {
          return tokens
        }
      }

      // 降级：累加所有消息的 prompt_tokens 和 completion_tokens
      return this.messages.reduce((sum, msg) => sum + (msg.prompt_tokens || 0) + (msg.completion_tokens || 0), 0)
    },
    selectedModelInfo() {
      return this.conversationModels.find(m => m.id === this.selectedModel) || null
    },
    effectiveContextLimit() {
      const modelInfo = this.selectedModelInfo || {}
      const candidates = [
        modelInfo.context_window,
        modelInfo.max_context_tokens,
        modelInfo.maxContextTokens,
        modelInfo.max_context,
        modelInfo.context_length,
        modelInfo.token_limit,
        modelInfo.max_input_tokens,
      ]
      for (const candidate of candidates) {
        const num = Number(candidate)
        if (Number.isFinite(num) && num > 0) return num
      }
      return this.maxContextTokens || 128000
    },
    contextDisplay() {
      return `${this.formatTokenCount(this.totalContextTokens)} / ${this.formatTokenCount(this.effectiveContextLimit)}`
    },
    dynamicVisibleCount() {
      // 根据消息内容长度动态计算显示条数
      // 从最新消息往前累加字符数，超过预算则停止
      const messages = this.getRenderableMessages()
      const charBudget = 3000
      let total = 0
      let count = 0
      for (let i = messages.length - 1; i >= 0; i--) {
        const len = (messages[i].content || '').length
        total += len
        count++
        if (count >= 2 && total > charBudget) break
      }
      return Math.max(count, 2)
    },
    visibleMessages() {
      const messages = this.getRenderableMessages()
      const n = this.dynamicVisibleCount
      if (this.showAllMessages || messages.length <= n) return messages
      return messages.slice(-n).map((msg, i) => ({ ...msg, _origIndex: messages.length - n + i }))
    },
    hiddenCount() {
      return this.getRenderableMessages().length - this.dynamicVisibleCount
    },
    hasHiddenMessages() {
      return !this.showAllMessages && this.hiddenCount > 0
    },
    hasProcessMessages() {
      if (this.nodeSteps.length > 0 || this.reasoningContent) return true
      return this.messages.some(msg => {
        if (msg.role !== 'assistant') return false
        return (msg.nodeSteps && msg.nodeSteps.length > 0)
          || (msg.toolCalls && msg.toolCalls.length > 0)
          || !!msg.reasoning
      })
    },
  },
  watch: {
    inputText() {
      this.validateInput()
    },
  },
  async mounted() {
    this.currentWorkflowId = this.workflowId || this.$route.params.id
    this.isInitializing = true
    try {
      if (this.isPublicMode) {
        await this.loadWorkflow()
        if (!this.workflowLoadError) await this.ensurePublicSession()
        await this.loadConversations()
      } else {
        const tasks = [
          this.loadWorkflow(),
          this.loadConversations(),
        ]
        tasks.push(this.checkUploadStatus(), this.loadModels(), this.loadToolConfig())
        await Promise.all(tasks)
      }
      const convId = this.$route.query.conversation_id
      const seedInput = consumeRouteSeedInput(this)
      const hasKnownPublicConversation = this.conversations.some(c => c.id === convId)
      if (this.workflowLoadError) {
        this.conversationId = ''
      } else if (convId && (!this.isPublicMode || hasKnownPublicConversation)) {
        await this.loadConversation(convId)
      } else if (convId && this.isPublicMode) {
        await this.newConversation()
      } else if (seedInput) {
        await this.newConversation()
      } else if (this.conversations.length > 0) await this.loadConversation(this.conversations[0].id)
      else await this.newConversation()
      if (seedInput && !this.inputText && this.userInputFieldName) {
        this.inputText = seedInput
      }
    } finally {
      this.isInitializing = false
      if (this.conversationId) this.attachActiveRun(this.conversationId)
    }
  },
  beforeUnmount() {
    if (this.inputErrorTimer) {
      window.clearTimeout(this.inputErrorTimer)
      this.inputErrorTimer = null
    }
    this.unsubscribeFromRun?.()
    this.stopSpeechStream?.()
    this.stopTtsPlayback?.()
  },
  methods: {
    async toggleSpeechInput() {
      if (!this.speechInputAvailable || this.isStreaming) return
      if (this.speechRecording) {
        this.stopSpeechInput()
        return
      }
      await this.startSpeechInput()
    },
    async startSpeechInput() {
      if (!this.speechInputAvailable || this.speechRecording) return
      if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
        this.setTimedInputError(this.$t('chatInput.speechInputUnsupported'))
        return
      }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
        const recorder = new MediaRecorder(stream)
        this.speechChunks = []
        this.speechStream = stream
        this.speechRecorder = recorder
        recorder.ondataavailable = (event) => {
          if (event.data && event.data.size > 0) this.speechChunks.push(event.data)
        }
        recorder.onstop = () => this.handleSpeechRecordingStopped()
        recorder.start()
        this.speechRecording = true
      } catch (error) {
        console.error('语音输入启动失败:', error)
        this.setTimedInputError(this.$t('chatInput.speechInputFailed'))
        this.stopSpeechStream()
      }
    },
    stopSpeechInput() {
      if (this.speechRecorder && this.speechRecorder.state !== 'inactive') {
        this.speechRecorder.stop()
        return
      }
      this.speechRecording = false
      this.stopSpeechStream()
    },
    stopSpeechStream() {
      if (this.speechStream) {
        this.speechStream.getTracks().forEach(track => track.stop())
      }
      this.speechStream = null
      this.speechRecorder = null
      this.speechRecording = false
    },
    async handleSpeechRecordingStopped() {
      const chunks = this.speechChunks
      this.speechChunks = []
      this.stopSpeechStream()
      if (!chunks.length) return
      try {
        const mimeType = chunks[0]?.type || 'audio/webm'
        const blob = new Blob(chunks, { type: mimeType })
        const file = new File([blob], `speech-${Date.now()}.webm`, { type: mimeType })
        const result = this.isPublicMode
          ? await this.transcribePublicSpeech(file)
          : await audioApi.speechToText(file, this.normalizedChatAudio.speech2text_model_id)
        const text = String(result?.text || '').trim()
        if (text) {
          this.inputText = this.inputText ? `${this.inputText}\n${text}` : text
          this.$nextTick(() => {
            this.$refs.chatInput?.focus?.()
            this.$refs.chatInput?.autoResize?.()
          })
        }
      } catch (error) {
        console.error('语音识别失败:', error)
        this.setTimedInputError(this.$t('chatInput.speechRecognitionFailed'))
      }
    },
    async speakMessage(msg) {
      if (!this.ttsAvailable || !msg?.content) return
      const key = this.messageAudioKey(msg)
      if (this.ttsMessageKey === key && this.ttsPlaying) {
        this.stopTtsPlayback()
        return
      }
      if (this.ttsMessageKey === key && this.ttsGenerating) return

      this.stopTtsPlayback()
      this.ttsMessageKey = key
      this.ttsGenerating = true
      this.ttsPlaying = false
      try {
        const blob = this.isPublicMode
          ? await this.synthesizePublicSpeech(msg.content)
          : await audioApi.textToSpeech({
            text: msg.content,
            model_id: this.normalizedChatAudio.tts_model_id,
            voice: this.normalizedChatAudio.tts_voice,
          })
        if (this.ttsMessageKey !== key) return
        this.ttsPlaybackUrl = URL.createObjectURL(blob)
        const audio = new Audio(this.ttsPlaybackUrl)
        this.ttsAudio = audio
        audio.onended = () => {
          if (this.ttsMessageKey === key) this.stopTtsPlayback()
        }
        this.ttsGenerating = false
        this.ttsPlaying = true
        await audio.play()
      } catch (error) {
        if (this.ttsMessageKey === key) {
          console.error('语音播放失败:', error)
          this.stopTtsPlayback()
          this.setTimedInputError(this.$t('chatMessage.speechGenerationFailed'))
        }
      }
    },
    async transcribePublicSpeech(file) {
      await this.ensurePublicSession()
      return publicAudioApi.speechToText(this.currentWorkflowId, this.shareToken, file)
    },
    async synthesizePublicSpeech(text) {
      await this.ensurePublicSession()
      return publicAudioApi.textToSpeech(this.currentWorkflowId, this.shareToken, { text })
    },
    messageAudioKey(msg) {
      return String(msg?._origIndex ?? msg?.id ?? msg?.timestamp ?? msg?.content ?? '')
    },
    ttsStateForMessage(msg) {
      if (this.ttsMessageKey !== this.messageAudioKey(msg)) return ''
      if (this.ttsGenerating) return 'generating'
      if (this.ttsPlaying) return 'playing'
      return ''
    },
    stopTtsPlayback() {
      if (this.ttsAudio) {
        this.ttsAudio.pause()
        this.ttsAudio = null
      }
      if (this.ttsPlaybackUrl) {
        URL.revokeObjectURL(this.ttsPlaybackUrl)
        this.ttsPlaybackUrl = ''
      }
      this.ttsMessageKey = ''
      this.ttsGenerating = false
      this.ttsPlaying = false
    },
    setTimedInputError(message) {
      if (this.inputErrorTimer) clearTimeout(this.inputErrorTimer)
      this.inputError = message
      this.inputErrorTimer = setTimeout(() => {
        this.inputError = ''
        this.inputErrorTimer = null
      }, 5000)
    },
    getRequestFailedMessage(error) {
      return this.$t('agentChat.requestFailed', {
        message: error?.message || this.$t('agentChat.unknownError'),
      })
    },
    getApprovalDefaultText(action) {
      return action === 'approve' ? this.$t('agentChat.approvalApprove') : this.$t('agentChat.approvalReject')
    },
    formatApprovalMessage(action, userMessage) {
      const defaultText = this.getApprovalDefaultText(action)
      if (action === 'approve') {
        return userMessage === defaultText
          ? this.$t('agentChat.approvalMessageApproved')
          : this.$t('agentChat.approvalMessageApprovedWithReason', { reason: userMessage })
      }
      return userMessage === defaultText
        ? this.$t('agentChat.approvalMessageRejected')
        : this.$t('agentChat.approvalMessageRejectedWithReason', { reason: userMessage })
    },
    applyHumanInterruptInfo(info) {
      const interruptInfo = info || {}
      const waitingFor = interruptInfo.waiting_for || this.userInputFieldName || ''
      this.approvalMode = !!interruptInfo.approval_mode
      this.humanWaitingFor = waitingFor
      this.humanInputModes = Array.isArray(interruptInfo.input_modes)
        ? interruptInfo.input_modes.map(mode => (
          mode && mode.type === 'button' ? { ...mode, field: waitingFor } : mode
        ))
        : null
    },
    onInfoPanelResizeDown(e) {
      e.preventDefault()
      const startX = e.clientX
      const startWidth = this.infoPanelWidth
      const onMove = (ev) => {
        const delta = startX - ev.clientX
        this.infoPanelWidth = Math.min(800, Math.max(200, startWidth + delta))
      }
      const onUp = () => {
        document.body.style.cursor = ''
        document.body.style.userSelect = ''
        document.removeEventListener('mousemove', onMove)
        document.removeEventListener('mouseup', onUp)
      }
      document.body.style.cursor = 'col-resize'
      document.body.style.userSelect = 'none'
      document.addEventListener('mousemove', onMove)
      document.addEventListener('mouseup', onUp)
    },
    formatTokenCount(tokens) {
      if (!tokens) return '0'
      return tokens < 1000 ? String(tokens) : (tokens / 1000).toFixed(1) + 'K'
    },
    async loadWorkflow() {
      try {
        this.workflowLoadError = ''
        this.publicSessionReady = false
        const data = await withReadinessRetry(
          () => this.isPublicMode
            ? publicWorkflowsApi.get(this.currentWorkflowId, this.shareToken)
            : workflowsApi.get(this.currentWorkflowId),
        )
        const workflow = localizeBuiltinWorkflow(data.workflow, this.$t.bind(this))
        this.workflowName = workflow.name
        this.workflowDesc = workflow.description
        this.workflowWelcome = workflow.welcome || ''
        this.chatAudio = workflow.chat_audio || null
        this.inputSchema = workflow.input_schema
        this.formConfig = workflow.form_config
        this.userInputFieldName = workflow.user_input_field
        this.isBuiltin = workflow.is_builtin || false
        this.initFormData()
      } catch (error) {
        console.error('加载工作流失败:', error)
        this.workflowLoadError = error.response?.data?.error || error.message || this.$t('agentChat.workflowUnavailable')
      }
    },
    async ensurePublicSession() {
      if (!this.isPublicMode || this.publicSessionReady) return
      await publicWorkflowsApi.openSession(this.currentWorkflowId, this.shareToken)
      this.publicSessionReady = true
    },
    async checkUploadStatus() {
      if (this.isPublicMode) { this.uploadAvailable = false; return }
      const headers = getAdminAuthHeaders()
      if (!headers) { this.uploadAvailable = false; return }
      try {
        const baseUrl = import.meta.env.VITE_API_BASE_URL || ''
        const res = await fetch(`${baseUrl}/api/upload/status`, { headers })
        if (handleAdminFetchAuthError(res)) { this.uploadAvailable = false; return }
        if (res.ok) { const data = await res.json(); this.uploadAvailable = data.available }
      } catch (e) { this.uploadAvailable = false }
    },
    async loadModels() {
      if (this.isPublicMode) return
      const headers = getAdminAuthHeaders()
      if (!headers) return
      try {
        const baseUrl = import.meta.env.VITE_API_BASE_URL || ''
        const res = await fetch(`${baseUrl}/api/models`, { headers })
        if (handleAdminFetchAuthError(res)) return
        if (res.ok) {
          const data = await res.json()
          this.models = (data.models || []).filter(isConversationModel)
          if (!this.models.some(m => m.id === this.selectedModel)) {
            this.selectedModel = this.models.some(m => m.id === data.default_model_id)
              ? data.default_model_id
              : (this.models[0]?.id || '')
          }
        }
      } catch (e) { console.error('加载模型列表失败:', e) }
    },
    async handleFileSelect(e) {
      const files = Array.from(e.target.files || [])
      e.target.value = ''
      if (!files.length) return
      const maxSize = 20 * 1024 * 1024
      const oversized = files.filter(f => f.size > maxSize)
      if (oversized.length > 0) {
        this.setTimedInputError(this.$t('agentChat.fileTooLarge', { size: '20MB' }))
        return
      }
      const headers = getAdminAuthHeaders()
      if (!headers) { this.setTimedInputError(this.$t('auth.invalidToken')); return }
      this.uploading = true
      this.inputError = ''
      const baseUrl = import.meta.env.VITE_API_BASE_URL || ''
      for (const file of files) {
        try {
          const form = new FormData()
          form.append('file', file)
          const res = await fetch(`${baseUrl}/api/upload`, { method: 'POST', headers, body: form })
          if (handleAdminFetchAuthError(res)) break
          if (res.ok) { this.attachedFiles.push(await res.json()) }
          else { this.setTimedInputError(this.$t('agentChat.uploadFailed')) }
        } catch (err) { this.setTimedInputError(this.$t('agentChat.uploadException')) }
      }
      this.uploading = false
    },
    removeFile(index) { this.attachedFiles.splice(index, 1) },
    async handleDropFiles(files) {
      if (!files.length) return
      const maxSize = 20 * 1024 * 1024
      const oversized = files.filter(f => f.size > maxSize)
      if (oversized.length > 0) {
        this.setTimedInputError(this.$t('agentChat.fileTooLarge', { size: '20MB' }))
        return
      }
      const headers = getAdminAuthHeaders()
      if (!headers) { this.setTimedInputError(this.$t('auth.invalidToken')); return }
      this.uploading = true
      this.inputError = ''
      const baseUrl = import.meta.env.VITE_API_BASE_URL || ''
      for (const file of files) {
        try {
          const form = new FormData()
          form.append('file', file)
          const res = await fetch(`${baseUrl}/api/upload`, { method: 'POST', headers, body: form })
          if (handleAdminFetchAuthError(res)) break
          if (res.ok) { this.attachedFiles.push(await res.json()) }
          else { this.setTimedInputError(this.$t('agentChat.uploadFailed')) }
        } catch (err) { this.setTimedInputError(this.$t('agentChat.uploadException')) }
      }
      this.uploading = false
    },
    async loadToolConfig() {
      if (this.isPublicMode) {
        this.availableSkills = []
        this.toolGroups = []
        this.toolConfigWarnings = []
        this.toolConfigLoading = false
        return
      }
      this.toolConfigLoading = true
      try {
        const data = await withReadinessRetry(() => workflowsApi.getToolConfig(this.currentWorkflowId))
        this.availableSkills = data.skills || []
        this.toolGroups = data.tool_groups || []
        this.toolConfigWarnings = data.warnings || []
      } catch (error) { console.error('加载工具配置失败:', error) }
      finally { this.toolConfigLoading = false }
    },
    async saveToolConfig() {
      const disabledSkills = this.availableSkills.filter(s => s.disabled).map(s => s.name)
      const disabledTools = this.allTools.filter(t => t.disabled).map(t => t.name)
      try { await workflowsApi.updateToolConfig(this.currentWorkflowId, { disabled_skills: disabledSkills, disabled_tools: disabledTools }) }
      catch (error) { console.error('保存工具配置失败:', error) }
    },
    toggleSkill(skill) { skill.disabled = !skill.disabled; this.saveToolConfig() },
    toggleTool(tool) { tool.disabled = !tool.disabled; this.saveToolConfig() },
    toggleAllServerTools(group) { const allEnabled = group.tools.every(t => !t.disabled); group.tools.forEach(t => { t.disabled = allEnabled }); this.saveToolConfig() },
    async resetToolConfig() { try { await workflowsApi.resetToolConfig(this.currentWorkflowId); await this.loadToolConfig() } catch (e) { console.error('重置失败:', e) } },
    initFormData() {
      if (!this.formConfig) return
      const cacheKey = `form_cache_${this.currentWorkflowId}`
      const cached = localStorage.getItem(cacheKey)
      if (cached) { try { this.formData = JSON.parse(cached); return } catch (e) {} }
      this.formData = {}
      for (const field of this.formConfig) {
        if (this.userInputFieldName && field.name === this.userInputFieldName) continue
        if (field.default !== undefined) this.formData[field.name] = field.default
        else if (field.type === 'files-upload') this.formData[field.name] = []
        else if (field.type === 'boolean' || field.type === 'switch') this.formData[field.name] = false
        else if (field.type === 'number' || field.type === 'integer') this.formData[field.name] = field.min || 0
        else this.formData[field.name] = ''
      }
    },
    saveFormCache() {
      const cacheKey = `form_cache_${this.currentWorkflowId}`
      const fileTypes = ['file-upload', 'file', 'image-upload', 'image', 'audio-upload', 'audio', 'files-upload', 'files']
      const fileFieldNames = new Set()
      if (this.formConfig) { for (const field of this.formConfig) { if (fileTypes.includes(field.type)) fileFieldNames.add(field.name) } }
      const cacheData = {}
      for (const [key, value] of Object.entries(this.formData)) { if (!fileFieldNames.has(key)) cacheData[key] = value }
      try { localStorage.setItem(cacheKey, JSON.stringify(cacheData)) } catch (e) {}
    },
    async handleFormFileUpload(event, fieldName) {
      const file = event.target.files[0]
      if (!file) return
      if (file.size > 20 * 1024 * 1024) { this.setTimedInputError(this.$t('agentChat.fileTooLarge', { size: '20MB' })); return }
      const headers = getAdminAuthHeaders()
      if (!headers) { this.setTimedInputError(this.$t('auth.invalidToken')); return }
      this.formFieldUploading[fieldName] = true
      const baseUrl = import.meta.env.VITE_API_BASE_URL || ''
      try {
        const form = new FormData()
        form.append('file', file)
        const res = await fetch(`${baseUrl}/api/upload`, { method: 'POST', headers, body: form })
        if (handleAdminFetchAuthError(res)) return
        if (res.ok) {
          const data = await res.json()
          this.formData[fieldName] = data.file_path
          this.formDataFileNames[fieldName] = file.name
        } else { this.setTimedInputError(this.$t('agentChat.fileUploadFailed')) }
      } catch (err) { this.setTimedInputError(this.$t('agentChat.fileUploadException')) }
      finally { this.formFieldUploading[fieldName] = false }
    },
    async handleFormFilesUpload(event, fieldName) {
      const files = Array.from(event.target.files || [])
      event.target.value = ''
      if (!files.length) return
      const maxSize = 20 * 1024 * 1024
      const oversized = files.filter(f => f.size > maxSize)
      if (oversized.length) { this.setTimedInputError(this.$t('agentChat.partialFilesTooLarge', { size: '20MB' })); return }
      const headers = getAdminAuthHeaders()
      if (!headers) { this.setTimedInputError(this.$t('auth.invalidToken')); return }
      this.formFieldUploading[fieldName] = true
      const baseUrl = import.meta.env.VITE_API_BASE_URL || ''
      if (!Array.isArray(this.formData[fieldName])) this.formData[fieldName] = []
      for (const file of files) {
        try {
          const form = new FormData()
          form.append('file', file)
          const res = await fetch(`${baseUrl}/api/upload`, { method: 'POST', headers, body: form })
          if (handleAdminFetchAuthError(res)) return
          if (res.ok) {
            const data = await res.json()
            this.formData[fieldName].push({ original_name: data.original_name, file_path: data.file_path, mime_type: data.mime_type, size: data.size })
          } else { this.setTimedInputError(this.$t('agentChat.fileUploadFailedWithName', { name: file.name })) }
        } catch (err) { this.setTimedInputError(this.$t('agentChat.fileUploadExceptionWithName', { name: file.name })) }
      }
      this.formFieldUploading[fieldName] = false
    },
    validateInput() {
      this.inputError = ''
      const text = this.inputText.trim()
      if (!text) return
      if (text.length > 10000) { this.inputError = this.$t('agentChat.inputTooLong'); return }
      if (/\{\{.*\}\}/.test(text) || /<script/i.test(text)) { this.inputError = this.$t('agentChat.inputContainsForbiddenChars') }
    },
    validateFormData() {
      const errors = {}
      for (const field of this.formFields) {
        if (!field.required) continue
        const value = this.formData[field.name]
        const missing = Array.isArray(value)
          ? value.length === 0
          : value === undefined || value === null || String(value).trim() === ''
        if (missing) errors[field.name] = this.$t('agentChat.requiredField')
      }
      this.formErrors = errors
      const firstError = Object.values(errors)[0]
      if (firstError) this.setTimedInputError(firstError)
      return Object.keys(errors).length === 0
    },
    async loadConversations() {
      const mergeConversationRecord = (existing, incoming) => {
        if (!existing) return incoming
        const existingMessages = Array.isArray(existing.messages) ? existing.messages : []
        const hasIncomingMessages = Array.isArray(incoming?.messages)
        const incomingMessages = hasIncomingMessages ? incoming.messages : []
        const messages = hasIncomingMessages && incomingMessages.length > existingMessages.length
          ? incomingMessages
          : existingMessages
        return { ...existing, ...incoming, messages }
      }
      const keyPrefix = this.isPublicMode ? 'public_conv_' : 'agent_conversations_'
      const key = `${keyPrefix}${this.currentWorkflowId}`
      const stored = localStorage.getItem(key)
      let localConvs = []
      if (stored) {
        try {
          const parsed = JSON.parse(stored)
          localConvs = Array.isArray(parsed) ? parsed : []
        } catch (e) {
          localConvs = []
        }
      }
      if (this.isPublicMode) {
        try {
          const res = await this.convApi.list(this.currentWorkflowId, 50, 'public')
          const apiConvs = res.conversations || []
          const merged = []
          for (const conv of [...localConvs, ...apiConvs]) {
            if (!conv?.id) continue
            const existingIndex = merged.findIndex(item => item.id === conv.id)
            if (existingIndex < 0) {
              merged.push(conv)
              continue
            }
            const existing = merged[existingIndex]
            merged[existingIndex] = mergeConversationRecord(existing, conv)
          }
          merged.sort((a, b) => (b.updated_at || b.created_at || 0) - (a.updated_at || a.created_at || 0))
          this.conversations = merged
          localStorage.setItem(key, JSON.stringify(merged))
        } catch (error) {
          this.conversations = localConvs
        }
        return
      }
      const source = this.isPublicMode ? 'public' : 'admin'
      try {
        const res = await this.convApi.list(this.currentWorkflowId, 50, source)
        const apiConvs = res.conversations || []
        const merged = []
        for (const conv of [...localConvs, ...apiConvs]) {
          if (!conv?.id) continue
          const existingIndex = merged.findIndex(item => item.id === conv.id)
          if (existingIndex < 0) {
            merged.push(conv)
            continue
          }
          const existing = merged[existingIndex]
          merged[existingIndex] = mergeConversationRecord(existing, conv)
        }
        merged.sort((a, b) => (b.updated_at || b.created_at || 0) - (a.updated_at || a.created_at || 0))
        this.conversations = merged
        localStorage.setItem(key, JSON.stringify(merged))
      } catch (error) { this.conversations = localConvs }
    },
    saveConversationsToLocal(options = {}) {
      const keyPrefix = this.isPublicMode ? 'public_conv_' : 'agent_conversations_'
      const key = `${keyPrefix}${this.currentWorkflowId}`
      if (options.replace === true) {
        localStorage.setItem(key, JSON.stringify(this.conversations || []))
        return
      }
      let existing = []
      try {
        const parsed = JSON.parse(localStorage.getItem(key) || '[]')
        existing = Array.isArray(parsed) ? parsed : []
      } catch (e) {
        existing = []
      }
      const mergedById = new Map(existing.filter(item => item?.id).map(item => [item.id, item]))
      for (const conv of this.conversations || []) {
        if (!conv?.id) continue
        const current = mergedById.get(conv.id)
        if (conv.id === this.conversationId || !current) mergedById.set(conv.id, conv)
      }
      const merged = [...mergedById.values()]
      merged.sort((a, b) => (b.updated_at || b.created_at || 0) - (a.updated_at || a.created_at || 0))
      localStorage.setItem(key, JSON.stringify(merged))
    },
    resetConversationRuntimeState() {
      this.streamingContent = ''
      this.reasoningContent = ''
      this.currentToolCalls = []
      this.nodeSteps = []
      this.todoItems = []
      this.currentPromptTokens = 0
      this.currentCompletionTokens = 0
      this.currentContextTokens = 0
      this.thinkingStatus = null
      this.workflowStatus = 'idle'
      this.streamEndedByWorkflowEvent = false
      this.currentTaskId = null
      this.lastStreamingDraftPersistAt = 0
      this.approvalMode = false
      this.humanInputModes = null
      this.humanWaitingFor = ''
      this.confirmDialog = { visible: false, submitting: false, confirmId: '', action: '', description: '', requireSudo: false, sudoPassword: '' }
      this.confirmQueue = []
    },
    getRenderableMessages(messages = this.messages) {
      const source = Array.isArray(messages) ? messages : []
      if (!this.isStreaming) return source
      return source.filter(msg => !(msg?.role === 'assistant' && msg.streamingDraft))
    },
    getRunKey(conversationId = this.conversationId) {
      return getManagedRunKey(this, conversationId)
    },
    createRunSnapshot() {
      return {
        conversationId: this.conversationId,
        isStreaming: this.isStreaming,
        workflowStatus: this.workflowStatus,
        streamingContent: this.streamingContent,
        reasoningContent: this.reasoningContent,
        messages: this.messages,
        nodeSteps: this.nodeSteps,
        currentToolCalls: this.currentToolCalls,
        todoItems: this.todoItems,
        thinkingStatus: this.thinkingStatus,
        currentTaskId: this.currentTaskId,
        streamEndedByWorkflowEvent: this.streamEndedByWorkflowEvent,
        currentPromptTokens: this.currentPromptTokens,
        currentCompletionTokens: this.currentCompletionTokens,
        currentContextTokens: this.currentContextTokens,
        approvalMode: this.approvalMode,
        humanInputModes: this.humanInputModes,
        humanWaitingFor: this.humanWaitingFor,
        confirmDialog: this.confirmDialog,
        confirmQueue: this.confirmQueue,
        processCollapsed: this.processCollapsed,
      }
    },
    applyRunSnapshot(snapshot) {
      return applyManagedRunSnapshot(this, snapshot)
    },
    beginManagedRun() {
      const key = this.getRunKey()
      if (!key || !this.conversationId) return
      this.activeRunKey = key
      agentRunManager.startRun(key, {
        abort: () => this.abortLocalRequest(),
        snapshot: this.createRunSnapshot(),
      })
    },
    publishRunSnapshot() {
      if (!this.activeRunKey) return
      agentRunManager.updateRun(this.activeRunKey, this.createRunSnapshot())
    },
    finishManagedRun() {
      if (!this.activeRunKey) return
      agentRunManager.finishRun(this.activeRunKey, this.createRunSnapshot())
      this.activeRunKey = ''
    },
    unsubscribeFromRun() {
      if (this.runUnsubscribe) {
        this.runUnsubscribe()
        this.runUnsubscribe = null
      }
    },
    attachActiveRun(conversationId = this.conversationId) {
      if (!conversationId) return false
      const key = typeof this.getRunKey === 'function'
        ? this.getRunKey(conversationId)
        : getManagedRunKey(this, conversationId)
      if (!agentRunManager.hasActiveRun(key)) return false
      this.unsubscribeFromRun?.()
      this.activeRunKey = key
      this.runUnsubscribe = agentRunManager.subscribe(key, snapshot => applyManagedRunSnapshot(this, snapshot))
      return true
    },
    generateId() { return generateLocalConversationId() },
    navigateToConversation(convId) {
      if (!convId) return
      this.$router.replace({ query: { ...withoutSeedInput(this.$route.query), conversation_id: convId } })
    },
    async createConversationShell() {
      const source = this.isPublicMode ? 'public' : 'admin'
      let conv = null
      try {
        conv = await this.convApi.create(this.currentWorkflowId, null, source, this.shareToken)
      } catch (error) {
        console.error('创建会话失败:', error)
      }
      if (!conv) {
        conv = {
          id: this.generateId(),
          title: this.$t('agentChat.newConversation'),
          created_at: Date.now(),
          updated_at: Date.now(),
          messages: [],
        }
      }
      const existing = this.conversations.find(item => item.id === conv.id)
      if (existing) Object.assign(existing, conv)
      else this.conversations.unshift(conv)
      this.saveConversationsToLocal()
      return conv
    },
    async newConversation() {
      if (this.workflowLoadError) return
      if (this.isStreaming) {
        const conv = await this.createConversationShell()
        this.navigateToConversation(conv.id)
        return
      }
      this.messages = withWorkflowWelcome(this, [])
      this.attachedFiles = []
      this.resetConversationRuntimeState()
      const conv = await this.createConversationShell()
      this.conversationId = conv.id
      conv.messages = this.messages
      conv.updated_at = Date.now()
      this.saveConversationsToLocal()
      if (this.messages.length > 0) {
        const title = conv.title || this.$t('agentChat.newConversation')
        try {
          await this.convApi.update(this.currentWorkflowId, conv.id, { title, messages: this.messages }, this.shareToken)
        } catch (error) {}
      }
      this.navigateToConversation(conv.id)
    },
    clearCurrentConversation() {
      if (this.isStreaming) return
      this.clearConversationDialog.visible = true
    },
    confirmClearCurrentConversation() {
      this.clearConversationDialog.visible = false
      this.messages = withWorkflowWelcome(this, [])
      this.resetConversationRuntimeState()
    },
    async loadConversation(convId) {
      if (this.isStreaming) {
        if (typeof this.navigateToConversation === 'function') {
          this.navigateToConversation(convId)
        } else {
          syncRouteConversationId(this, convId)
        }
        return
      }
      const loadSeq = ++this.conversationLoadSeq
      this.attachedFiles = []; this.showAllMessages = false; this.resetConversationRuntimeState()
      const applyConversation = (conv) => {
        if (loadSeq !== this.conversationLoadSeq || this.isStreaming) return false
        this.conversationId = conv.id
        this.messages = this.normalizeAssistantMessages(withWorkflowWelcome(this, conv.messages || []))
        this.nodeSteps = []
        this.loadFeedbackFromDb()
        this.scrollToBottom(true)
        return true
      }
      const conv = this.conversations.find(c => c.id === convId)
      if (conv) {
        applyConversation(conv)
      } else if (this.isPublicMode) {
        return
      } else {
        try {
          const apiConv = await this.convApi.get(this.currentWorkflowId, convId, this.shareToken)
          applyConversation(apiConv)
        } catch (error) {
          console.error('加载会话失败:', error)
          const localConv = ensureLocalConversation(this, convId)
          applyConversation(localConv)
        }
      }
      if (loadSeq !== this.conversationLoadSeq || this.isStreaming) return
      // 同步 conversation_id 到 URL，刷新页面后可恢复
      syncRouteConversationId(this, convId)
      const attachedRun = typeof this.attachActiveRun === 'function' ? this.attachActiveRun(convId) : false
      // 恢复中断状态：检查最后一条消息是否有 pendingApproval
      if (!attachedRun) this.restoreInterruptState()
    },
    async deleteConversation(convId) {
      this.deleteConversationDialog = { visible: true, conversationId: convId }
    },
    async confirmDeleteConversation() {
      const convId = this.deleteConversationDialog.conversationId
      this.deleteConversationDialog = { visible: false, conversationId: '' }
      if (!convId) return
      const removeConversationLocally = async () => {
        this.conversations = this.conversations.filter(c => c.id !== convId)
        this.saveConversationsToLocal({ replace: true })
        if (convId === this.conversationId) {
          if (this.conversations.length > 0) await this.loadConversation(this.conversations[0].id)
          else await this.newConversation()
        }
      }
      let deleteResult = null
      try {
        deleteResult = await this.convApi.delete(this.currentWorkflowId, convId, this.shareToken)
      } catch (e) {
        if (this.isPublicMode && e?.response?.status === 404) {
          await removeConversationLocally()
          return
        }
        console.error('删除会话失败:', e)
        this.setTimedInputError(this.$t('agentChat.deleteConversationFailed'))
        return
      }
      if (deleteResult?.success === false) {
        this.setTimedInputError(this.$t('agentChat.deleteConversationFailed'))
        return
      }
      await removeConversationLocally()
    },
    async updateCurrentConversation() {
      const conv = this.conversations.find(c => c.id === this.conversationId)
      if (!conv) return
      const firstUserMsg = this.messages.find(m => m.role === 'user')
      const title = firstUserMsg ? firstUserMsg.content.substring(0, 20) + (firstUserMsg.content.length > 20 ? '...' : '') : this.$t('agentChat.newConversation')
      conv.messages = this.messages; conv.updated_at = Date.now(); conv.title = title
      this.saveConversationsToLocal()
      try { await this.convApi.update(this.currentWorkflowId, this.conversationId, { title, messages: this.messages }, this.shareToken) } catch (e) {}
    },
    buildStreamingAssistantMessage({ draft = true } = {}) {
      const hasNodeSteps = this.nodeSteps.length > 0
      const fallbackText = this.workflowStatus === 'cancelled' ? this.$t('agentChat.interrupted') : this.$t('agentChat.noTextReply')
      const guardMeta = this.extractPostEditGuardMeta(this.streamingContent || fallbackText)
      const pendingHumanInput = this.workflowStatus === 'interrupted' && !!this.humanWaitingFor
      const message = {
        role: 'assistant', content: guardMeta.content, deliveryStatus: guardMeta.status,
        deliveryReason: guardMeta.reason, deliveryNextStep: guardMeta.nextStep,
        reasoning: this.reasoningContent || null, timestamp: Date.now(),
        toolCalls: hasNodeSteps ? [] : this.currentToolCalls.map(t => ({ ...t, expanded: false })),
        nodeSteps: this.nodeSteps.map(s => ({ ...s, expanded: false })),
        reasoningExpanded: false,
        prompt_tokens: this.currentPromptTokens || 0, completion_tokens: this.currentCompletionTokens || 0,
        context_tokens: this.currentContextTokens || 0,
        pendingApproval: this.approvalMode && this.workflowStatus === 'interrupted' ? true : undefined,
        pendingHumanInput: pendingHumanInput || undefined,
        humanWaitingFor: pendingHumanInput ? this.humanWaitingFor : undefined,
        humanInputModes: pendingHumanInput && Array.isArray(this.humanInputModes) ? this.humanInputModes : undefined,
      }
      if (draft) message.streamingDraft = true
      return message
    },
    upsertStreamingAssistantMessage({ draft = true } = {}) {
      if (!this.streamingContent && this.currentToolCalls.length === 0 && this.nodeSteps.length === 0 && !this.reasoningContent && this.workflowStatus !== 'cancelled') return null
      const message = this.buildStreamingAssistantMessage({ draft })
      const lastUserIndex = this.messages.reduce((latest, msg, index) => msg?.role === 'user' ? index : latest, -1)
      let existingIndex = -1
      for (let index = this.messages.length - 1; index > lastUserIndex; index--) {
        const msg = this.messages[index]
        if (msg?.role === 'assistant' && msg.streamingDraft) {
          existingIndex = index
          break
        }
      }
      if (existingIndex >= 0) this.messages.splice(existingIndex, 1, message)
      else this.messages.push(message)
      return message
    },
    persistStreamingAssistantDraft({ remote = false } = {}) {
      const message = this.upsertStreamingAssistantMessage({ draft: true })
      if (!message) return null
      const conv = this.conversations.find(c => c.id === this.conversationId)
      if (!conv) return message
      const firstUserMsg = this.messages.find(m => m.role === 'user')
      const title = firstUserMsg ? firstUserMsg.content.substring(0, 20) + (firstUserMsg.content.length > 20 ? '...' : '') : this.$t('agentChat.newConversation')
      conv.messages = this.messages
      conv.updated_at = Date.now()
      conv.title = title
      const now = Date.now()
      const shouldSaveLocal = remote || now - (this.lastStreamingDraftPersistAt || 0) > 1000
      if (shouldSaveLocal) {
        this.saveConversationsToLocal()
        this.lastStreamingDraftPersistAt = now
      }
      if (remote && this.convApi?.update) {
        this.convApi.update(this.currentWorkflowId, this.conversationId, { title, messages: this.messages }, this.shareToken).catch(() => {})
      }
      return message
    },
    async manualCompressContext() {
      if (!this.canManualCompressContext) return
      this.compressConfirmDialog.visible = true
    },
    async confirmManualCompressContext() {
      if (!this.canManualCompressContext) { this.compressConfirmDialog.visible = false; return }
      this.compressConfirmDialog.visible = false
      this.isCompressingContext = true
      this.thinkingStatus = { icon: '📦', text: this.$t('agentChat.compressingContext') }
      try {
        const result = await executionApi.compressContext(this.currentWorkflowId, this.conversationId)
        if (result.context_tokens !== undefined) this.currentContextTokens = result.context_tokens
        if (result.compressed) {
          this.messages = this.messages.map(msg => ({ ...msg, compressed_out: true }))
          this.messages.push({
            role: 'assistant',
            content: result.summary || this.$t('agentChat.contextCompressed'),
            timestamp: Date.now(),
            is_summary: true,
            force_visible: true,
            original_message_count: result.compressed_message_count || 0,
            context_tokens: this.currentContextTokens || 0,
          })
          this.thinkingStatus = { icon: '✅', text: this.$t('agentChat.contextCompressed') }
          await this.updateCurrentConversation()
          this.scrollToBottom()
        } else {
          this.thinkingStatus = { icon: 'ℹ️', text: this.$t('agentChat.contextCompressionSkipped') }
        }
      } catch (error) {
        this.thinkingStatus = { icon: '❌', text: this.$t('agentChat.contextCompressionFailed') }
        this.setTimedInputError(error.response?.data?.error || error.message || this.$t('agentChat.contextCompressionFailed'))
      } finally {
        this.isCompressingContext = false
        setTimeout(() => {
          if (!this.isStreaming && !this.isCompressingContext) this.thinkingStatus = null
        }, 1600)
      }
    },
    async sendMessage() {
      if (this.isStreaming) { this.abortRequest(); return }
      if (this.isInitializing) return
      if (!this.conversationId && !ensureConversationIdForRun(this)) return
      this.validateInput()
      if (!this.inputText.trim() || this.inputError) return
      if (!this.validateFormData()) return
      const userMessage = this.inputText.trim()
      const resumeField = this.workflowStatus === 'interrupted' && this.humanWaitingFor
        ? this.humanWaitingFor
        : null
      this.inputText = ''; this.inputError = ''; this.currentPromptTokens = 0; this.currentCompletionTokens = 0
      this.$nextTick(() => { if (this.$refs.chatInput) this.$refs.chatInput.resetHeight() })
      this.messages.push({ role: 'user', content: userMessage, timestamp: Date.now() })
      this.updateCurrentConversation(); this.scrollToBottom(); this.saveFormCache()
      this.approvalMode = false
      this.humanInputModes = null
      this.humanWaitingFor = ''
      this.lastStreamingDraftPersistAt = 0
      this.isStreaming = true; this.workflowStatus = 'running'; this.streamingContent = ''
      this.currentToolCalls = []; this.nodeSteps = []; this.todoItems = []; this.streamEndedByWorkflowEvent = false
      this.thinkingStatus = { icon: '', text: this.$t('agentChat.thinking') }
      try { await this.streamRequest(userMessage, null, null, resumeField) }
      catch (error) {
        if (error.name === 'AbortError') {
          if (this.streamingContent) {
            this.messages.push({ role: 'assistant', content: this.streamingContent + `\n\n[${this.$t('agentChat.stopped')}]`, timestamp: Date.now(), toolCalls: [...this.currentToolCalls] })
          }
        } else {
          this.messages.push({ role: 'assistant', content: this.getRequestFailedMessage(error), timestamp: Date.now() })
        }
      } finally {
        this.isStreaming = false
        if (this.workflowStatus === 'running') this.workflowStatus = 'finished'
        this.thinkingStatus = null; this.currentToolCalls = []; this.updateCurrentConversation(); this.scrollToBottom()
        this.finishManagedRun()
      }
    },
    handleApproval(msg, index, action) {
      // 标记当前消息审批完成
      const realMsg = this.messages[index] || msg
      realMsg.pendingApproval = false
      realMsg.approvalResult = action
      this.submitApproval(action)
    },
    restoreInterruptState() {
      // 检查最后一条助手消息是否还在等待用户输入，恢复中断状态
      const lastAssistant = [...this.messages].reverse().find(m => m.role === 'assistant')
      if (lastAssistant && lastAssistant.pendingApproval) {
        this.workflowStatus = 'interrupted'
        this.approvalMode = true
        this.humanWaitingFor = lastAssistant.humanWaitingFor || this.userInputFieldName || ''
        this.humanInputModes = lastAssistant.humanInputModes || null
      } else if (lastAssistant && lastAssistant.pendingHumanInput) {
        this.workflowStatus = 'interrupted'
        this.approvalMode = false
        this.humanWaitingFor = lastAssistant.humanWaitingFor || this.userInputFieldName || ''
        this.humanInputModes = lastAssistant.humanInputModes || null
      } else {
        this.workflowStatus = 'finished'
        this.approvalMode = false
        this.humanWaitingFor = ''
        this.humanInputModes = null
      }
    },
    async submitApproval(action) {
      const userMessage = this.inputText.trim() || this.getApprovalDefaultText(action)
      this.inputText = ''; this.approvalMode = false; this.humanInputModes = null; this.humanWaitingFor = ''
      this.messages.push({ role: 'user', content: this.formatApprovalMessage(action, userMessage), timestamp: Date.now(), isInterruptResponse: true })
      this.updateCurrentConversation(); this.scrollToBottom()
      this.lastStreamingDraftPersistAt = 0
      this.isStreaming = true; this.workflowStatus = 'running'; this.streamingContent = ''
      this.currentToolCalls = []; this.nodeSteps = []; this.todoItems = []; this.streamEndedByWorkflowEvent = false
      this.thinkingStatus = {
        icon: '',
        text: action === 'approve' ? this.$t('agentChat.approvalContinues') : this.$t('agentChat.approvalRedraft'),
      }
      try { await this.streamRequest(userMessage, action) }
      catch (error) {
        if (error.name !== 'AbortError') {
          this.messages.push({ role: 'assistant', content: this.getRequestFailedMessage(error), timestamp: Date.now() })
        }
      } finally {
        this.isStreaming = false
        if (this.workflowStatus === 'running') this.workflowStatus = 'finished'
        this.thinkingStatus = null; this.currentToolCalls = []; this.updateCurrentConversation(); this.scrollToBottom()
        this.finishManagedRun()
      }
    },
    async submitHumanInputAction({ label, value, mode }) {
      if (this.isStreaming) return
      if (!this.conversationId && !ensureConversationIdForRun(this)) return
      const field = mode?.field || this.humanWaitingFor
      if (!field) return
      const displayText = label || String(value ?? '')
      this.inputText = ''
      this.inputError = ''
      this.messages.push({ role: 'user', content: displayText, timestamp: Date.now(), isInterruptResponse: true })
      this.updateCurrentConversation(); this.scrollToBottom()
      this.approvalMode = false
      this.humanInputModes = null
      this.humanWaitingFor = ''
      this.lastStreamingDraftPersistAt = 0
      this.isStreaming = true; this.workflowStatus = 'running'; this.streamingContent = ''
      this.currentToolCalls = []; this.nodeSteps = []; this.todoItems = []; this.streamEndedByWorkflowEvent = false
      this.thinkingStatus = { icon: '', text: this.$t('agentChat.processingStart') }
      try { await this.streamRequest(null, null, { field, label: displayText, value }) }
      catch (error) {
        if (error.name !== 'AbortError') {
          this.messages.push({ role: 'assistant', content: this.getRequestFailedMessage(error), timestamp: Date.now() })
        }
      } finally {
        this.isStreaming = false
        if (this.workflowStatus === 'running') this.workflowStatus = 'finished'
        this.thinkingStatus = null; this.currentToolCalls = []; this.updateCurrentConversation(); this.scrollToBottom()
        this.finishManagedRun()
      }
    },
    async startWorkflow() {
      if (!this.canStartWorkflow) return
      if (!this.validateFormData()) return
      this.saveFormCache()
      this.lastStreamingDraftPersistAt = 0
      this.isStreaming = true; this.workflowStatus = 'running'; this.streamingContent = ''
      this.currentToolCalls = []; this.nodeSteps = []; this.todoItems = []; this.streamEndedByWorkflowEvent = false
      this.thinkingStatus = { icon: '', text: this.$t('agentChat.startingWorkflow') }
      try { await this.streamRequest(null) }
      catch (error) { if (error.name !== 'AbortError') this.messages.push({ role: 'assistant', content: this.getRequestFailedMessage(error), timestamp: Date.now() }) }
      finally {
        this.isStreaming = false
        if (this.workflowStatus === 'running') this.workflowStatus = 'finished'
        this.thinkingStatus = null; this.currentToolCalls = []; this.updateCurrentConversation(); this.scrollToBottom()
        this.finishManagedRun()
      }
    },
    async abortRequest() {
      const activeKey = typeof this.getRunKey === 'function' ? this.getRunKey() : getManagedRunKey(this)
      if (agentRunManager.hasActiveRun(activeKey)) {
        await agentRunManager.abortRun(activeKey)
        return
      }
      await this.abortLocalRequest()
    },
    async abortLocalRequest() {
      if (this.abortController) { this.abortController.abort(); this.abortController = null }
      this.markRunningStepsCancelled(this.$t('agentChat.interrupted'))
      this.workflowStatus = 'cancelled'; this.thinkingStatus = null; this.isStreaming = false
      const taskId = this.currentTaskId; this.currentTaskId = null
      if (taskId) { try { await tasksApi.cancel(taskId, '用户中止') } catch (e) {} }
      this.publishRunSnapshot?.()
    },
    async streamRequest(userInput, humanAction, humanInputAction = null, resumeField = null) {
      const baseUrl = import.meta.env.VITE_API_BASE_URL || ''
      this.abortController = new AbortController()
      const conversationId = ensureConversationIdForRun(this)
      this.beginManagedRun?.()
      const inputs = buildWorkflowRunInputs({
        baseInputs: this.formData,
        userInput,
        inputField: resumeField || this.userInputFieldName,
        humanInput: humanInputAction,
      })
      if (humanAction) inputs.__human_action__ = humanAction
      if (!this.isPublicMode && this.selectedModel) inputs.model = this.selectedModel
      if (!this.isPublicMode && this.isBuiltin && !this.preFilterEnabled) inputs.__skip_filter__ = true
      const body = { workflow_id: this.currentWorkflowId, response_mode: 'streaming', conversation_id: conversationId, inputs }
      if (!this.isPublicMode) {
        body.tool_confirmation_required = !!this.toolConfirmationRequired
        body.tool_confirmation_level = this.toolConfirmationLevel
      }
      if (typeof userInput === 'string' && userInput.trim().length > 0) body.user = userInput
      const workflowUserId = localStorage.getItem('workflow_user_id')
      if (!this.isPublicMode && workflowUserId) body.user_id = workflowUserId
      if (!this.isPublicMode && this.attachedFiles.length) body.files = this.attachedFiles.map(f => ({ original_name: f.original_name, path: f.file_path, mime_type: f.mime_type, size: f.size }))
      let endpoint = this.isPublicMode
        ? `${baseUrl}/api/public/workflows/${encodeURIComponent(this.currentWorkflowId)}/run`
        : `${baseUrl}/api/workflow/run`
      if (this.isPublicMode && this.shareToken) {
        endpoint += `?share_token=${encodeURIComponent(this.shareToken)}`
      }
      const headers = { 'Content-Type': 'application/json' }
      if (this.isPublicMode) {
        await this.ensurePublicSession()
        headers['X-AgentClaw-Public-Session'] = '1'
      }
      if (!this.isPublicMode) {
        const authHeaders = getAdminAuthHeaders(headers)
        if (!authHeaders) throw new Error(this.$t('auth.invalidToken'))
        Object.assign(headers, authHeaders)
      }
      const response = await fetch(endpoint, {
        method: 'POST', headers,
        credentials: this.isPublicMode ? 'same-origin' : undefined,
        body: JSON.stringify(body), signal: this.abortController.signal,
      })
      if (handleAdminFetchAuthError(response)) throw new Error(this.$t('auth.invalidToken'))
      if (!response.ok) throw new Error(`HTTP ${response.status}: ${await response.text()}`)
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      try {
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''
          for (const line of lines) {
            this.handleSseLine(line)
          }
        }
        buffer += decoder.decode()
        if (buffer.trim()) {
          for (const line of buffer.split('\n')) this.handleSseLine(line)
          buffer = ''
        }
      } catch (e) {
        if (e.name !== 'AbortError') throw e
      }
      if (!this.streamEndedByWorkflowEvent && this.workflowStatus === 'running') {
        const err = this.$t('agentChat.workflowDidNotFinish')
        this.markRunningStepsFailed(err); this.appendStreamError(err); this.workflowStatus = 'finished'
      }
      if (this.streamingContent || this.currentToolCalls.length > 0 || this.nodeSteps.length > 0 || this.reasoningContent || this.workflowStatus === 'cancelled') {
        logger.debug('Saving message with token data:', {
          prompt_tokens: this.currentPromptTokens,
          completion_tokens: this.currentCompletionTokens,
          context_tokens: this.currentContextTokens
        })

        this.upsertStreamingAssistantMessage({ draft: false })

        logger.info('Message saved:', this.messages[this.messages.length - 1])

        this.streamingContent = ''; this.reasoningContent = ''; this.nodeSteps = []; this.currentToolCalls = []
      }
    },
    handleSseLine(line) {
      if (!line || !line.startsWith('data: ')) return
      const data = line.slice(6).trim()
      if (!data || data === '[DONE]') return
      try {
        this.handleStreamEvent(JSON.parse(data))
      } catch (error) {
        logger.warn('Failed to parse SSE event', { data: data.slice(0, 200), error })
      }
    },
    handleStreamEvent(event) {
      const eventType = event.event || event.type
      const eventData = event.data || event

      // 记录所有事件
      logger.event(eventType, { event, eventData })

      const incomingTaskId = event.task_id || eventData.task_id
      if (incomingTaskId && !this.currentTaskId) {
        this.currentTaskId = incomingTaskId
        this.publishRunSnapshot?.()
      }
      switch (eventType) {
        case 'message':
          this.thinkingStatus = null
          if (eventData.answer) { this.streamingContent += eventData.answer; this.scrollToBottom() }
          else if (eventData.content) { this.streamingContent += eventData.content; this.scrollToBottom() }
          this.persistStreamingAssistantDraft?.()
          break
        case 'reasoning': {
          this.ensureProcessVisibleForFirstRun()
          if (!this.reasoningContent) this.reasoningContent = ''
          this.reasoningContent += eventData.content || ''
          this.thinkingStatus = { icon: '', text: this.$t('agentChat.thinking') }
          // 追加到 running step 的 segments（交叉显示）
          const reasonNodeId = eventData.node_id || event.node_id
          const reasonStep = reasonNodeId
            ? this.nodeSteps.find(s => s.id === reasonNodeId && s.status === 'running')
            : this.nodeSteps.findLast ? this.nodeSteps.findLast(s => s.status === 'running') : [...this.nodeSteps].reverse().find(s => s.status === 'running')
          if (reasonStep && reasonStep.segments) {
            const lastSeg = reasonStep.segments[reasonStep.segments.length - 1]
            if (lastSeg && lastSeg.type === 'reasoning') {
              lastSeg.content += eventData.content || ''
            } else {
              reasonStep.segments.push({ type: 'reasoning', content: eventData.content || '', expanded: true })
            }
          }
          this.scrollToBottom()
          this.persistStreamingAssistantDraft?.()
          break
        }
        case 'workflow_started':
          this.thinkingStatus = { icon: '', text: this.$t('agentChat.processingStart') }; this.reasoningContent = ''
          if (this.nodeSteps.length === 0) this.nodeSteps = []
          this.persistStreamingAssistantDraft?.()
          break
        case 'node_started': {
          this.ensureProcessVisibleForFirstRun()
          const nodeId = eventData.node_id || eventData.node || event.node_id || event.node
          const nodeType = eventData.node_type || eventData.type || event.node_type || 'unknown'
          if (this.nodeSteps.find(s => s.id === nodeId && s.status === 'running')) break
          this.nodeSteps.push(this.localizeNodeStep({ id: nodeId, name: eventData.title || nodeId, type: nodeType, typeLabel: this.getNodeTypeLabel(nodeType), status: 'running', startTime: Date.now(), elapsed: null, inputs: eventData.inputs || null, outputs: null, error: null, toolCalls: [], segments: [], showAllTools: false, expanded: false, parallelGroupId: eventData.parallel_group_id || null }))
          if (nodeType.toLowerCase().includes('llm')) this.thinkingStatus = { icon: '', text: this.$t('agentChat.thinking') }
          else if (nodeType.toLowerCase().includes('tool') || nodeType.toLowerCase().includes('mcp')) this.thinkingStatus = { icon: '', text: this.$t('agentChat.toolCallingGeneric') }
          else if (nodeType.toLowerCase().includes('human')) this.thinkingStatus = { icon: '', text: this.$t('agentChat.awaitingInput') }
          else this.thinkingStatus = { icon: '', text: this.$t('agentChat.executingNode', { nodeId }) }
          this.scrollToBottom(); this.persistStreamingAssistantDraft?.(); break
        }
        case 'node_finished': {
          const finishedNodeId = eventData.node_id || eventData.node || event.node_id || event.node
          const step = this.nodeSteps.find(s => s.id === finishedNodeId && s.status === 'running')
          if (step) {
            step.status = eventData.status || 'succeeded'
            if (eventData.error) step.error = eventData.error
            if (eventData.elapsed_time) { const e = eventData.elapsed_time; step.elapsed = e < 1 ? `${Math.round(e * 1000)}ms` : `${e.toFixed(1)}s` }
            else if (step.startTime) { const e = (Date.now() - step.startTime) / 1000; step.elapsed = e < 1 ? `${Math.round(e * 1000)}ms` : `${e.toFixed(1)}s` }
            if (eventData.outputs) step.outputs = eventData.outputs
          }
          // 只有当没有任何 running 节点时才清除 thinkingStatus（并行节点场景）
          if (!this.nodeSteps.some(s => s.status === 'running')) this.thinkingStatus = null
          this.persistStreamingAssistantDraft?.()
          break
        }
        case 'tool_start': {
          this.ensureProcessVisibleForFirstRun()
          const toolName = event.tool_call?.function?.name || this.$t('agentChat.toolDefaultName')
          this.archiveStreamingContentToStep(eventData.node_id || event.node_id)
          this.thinkingStatus = { icon: '', text: this.$t('agentChat.toolCalling', { name: toolName }) }
          const startToolCall = { id: event.tool_call?.id, name: toolName, arguments: event.tool_call?.function?.arguments || '{}', result: null, status: 'running', statusText: this.$t('agentChat.toolStatus.running'), expanded: false, batchId: eventData.batch_id || event.batch_id || null, startTime: Date.now() }
          const nodeId = eventData.node_id || event.node_id
          const runningStep = nodeId ? this.nodeSteps.find(s => s.id === nodeId && s.status === 'running') : this.nodeSteps.find(s => s.status === 'running')
          if (runningStep) {
            runningStep.toolCalls.push(startToolCall)
            if (runningStep.segments) runningStep.segments.push({ type: 'tool', ...startToolCall })
          }
          this.currentToolCalls.push(startToolCall); this.scrollToBottom(); this.persistStreamingAssistantDraft?.(); break
        }
        case 'tool': {
          const toolStatusMeta = this.resolveToolCallStatus({ status: eventData.status || event.status, result: event.tool_result })
          const toolCall = { id: event.tool_call?.id, name: event.tool_call?.function?.name || this.$t('agentChat.unknownTool'), arguments: event.tool_call?.function?.arguments || '{}', result: event.tool_result, status: toolStatusMeta.status, statusText: toolStatusMeta.text, expanded: false, batchId: eventData.batch_id || event.batch_id || null }
          this.thinkingStatus = null
          if (toolCall.name === 'TodoWrite' && toolCall.result) this.parseTodoResult(toolCall.result)
          const nodeId2 = eventData.node_id || event.node_id
          const runningStep2 = nodeId2 ? this.nodeSteps.find(s => s.id === nodeId2 && s.status === 'running') : this.nodeSteps.find(s => s.status === 'running')
          if (runningStep2) {
            const idx = runningStep2.toolCalls.findIndex(t => t.id === toolCall.id)
            if (idx >= 0) { const st = runningStep2.toolCalls[idx].startTime; if (st) { const e = (Date.now() - st) / 1000; toolCall.elapsed = e < 1 ? `${Math.round(e * 1000)}ms` : `${e.toFixed(1)}s` }; runningStep2.toolCalls[idx] = toolCall }
            else runningStep2.toolCalls.push(toolCall)
            // 同步更新 segments 中对应的 tool
            if (runningStep2.segments) {
              const segIdx = runningStep2.segments.findIndex(s => s.type === 'tool' && s.id === toolCall.id)
              if (segIdx >= 0) Object.assign(runningStep2.segments[segIdx], toolCall, { type: 'tool' })
            }
          }
          const existIdx = this.currentToolCalls.findIndex(t => t.id === toolCall.id)
          if (existIdx >= 0) this.currentToolCalls[existIdx] = toolCall
          else this.currentToolCalls.push(toolCall)
          this.scrollToBottom(); this.persistStreamingAssistantDraft?.(); break
        }
        case 'harness_feedback': {
          this.ensureProcessVisibleForFirstRun()
          const content = eventData.content || event.content || eventData.answer || event.answer || ''
          const nodeId = eventData.node_id || event.node_id
          const batchId = eventData.batch_id || event.batch_id || null
          const step = this.findStepForHarnessFeedback(nodeId, batchId)
          logger.debug('harness_feedback received', { nodeId, batchId, empty: !content, contentLen: content.length, hasStep: !!step, content })
          if (step) {
            if (!step.segments) step.segments = []
            step.segments.push({ type: content ? 'harness-feedback' : 'tool-separator', content, batchId, createdAt: eventData.created_at || event.created_at || Date.now() })
          } else if (content) {
            this.streamingContent += content
          }
          this.thinkingStatus = null
          this.scrollToBottom()
          this.persistStreamingAssistantDraft?.()
          break
        }
        case 'message_end':
          logger.debug('message_end event details:', {
            metadata: eventData.metadata,
            usage: eventData.metadata?.usage,
            context_tokens: eventData.metadata?.context_tokens
          })

          this.thinkingStatus = null
          if (eventData.metadata?.usage) {
            this.currentPromptTokens = eventData.metadata.usage.prompt_tokens || 0
            this.currentCompletionTokens = eventData.metadata.usage.completion_tokens || 0
            logger.info('Token counts set:', {
              prompt: this.currentPromptTokens,
              completion: this.currentCompletionTokens
            })
          }
          if (eventData.metadata?.context_tokens !== undefined) {
            this.currentContextTokens = eventData.metadata.context_tokens
          }
          this.persistStreamingAssistantDraft?.()
          break
        case 'workflow_finished':
          this.streamEndedByWorkflowEvent = true; this.thinkingStatus = null; this.currentTaskId = null
          if (eventData.status === 'cancelled' || eventData.outputs?.cancelled) this.workflowStatus = 'cancelled'
          else if (eventData.status === 'interrupted' || eventData.outputs?.interrupted) {
            this.workflowStatus = 'interrupted'
            this.applyHumanInterruptInfo(eventData.outputs?.interrupt_info)
          }
          else if (eventData.status === 'failed') {
            this.markRunningStepsFailed(eventData.error || this.$t('agentChat.workflowFailed'))
            this.appendStreamError(eventData.error || this.$t('agentChat.workflowFailed'))
            this.workflowStatus = 'finished'
          }
          else {
            this.workflowStatus = 'finished'
            if (eventData.outputs?.next_input_info) this.applyHumanInterruptInfo(eventData.outputs.next_input_info)
          }
          if (eventData.outputs?.answer && !this.streamingContent) this.streamingContent = eventData.outputs.answer
          this.persistStreamingAssistantDraft?.({ remote: true })
          break
        case 'interrupted':
          this.thinkingStatus = { icon: '', text: this.$t('agentChat.awaitingInput') }; this.workflowStatus = 'interrupted'
          this.applyHumanInterruptInfo(event.data || event)
          this.persistStreamingAssistantDraft?.({ remote: true })
          break
        case 'model_retry': {
          const attempt = eventData.attempt || event.attempt || 1
          const max = eventData.max_attempts || event.max_attempts || attempt
          const reason = String(eventData.error || event.error || '').trim()
          const retryText = reason
            ? this.$t('agentChat.modelRetryingWithReason', { attempt, max, reason })
            : this.$t('agentChat.modelRetrying', { attempt, max })
          this.thinkingStatus = { icon: '⚠️', text: retryText }
          const nodeId = eventData.node_id || event.node_id
          const step = nodeId ? this.nodeSteps.find(s => s.id === nodeId && s.status === 'running') : this.nodeSteps.find(s => s.status === 'running')
          if (step) step.warning = retryText
          this.scrollToBottom()
          break
        }
        case 'model_error': {
          const message = eventData.error || event.error || this.$t('agentChat.modelCallFailed')
          const nodeId = eventData.node_id || event.node_id
          this.markNodeStepFailed(nodeId, message)
          this.appendStreamError(this.$t('agentChat.modelCallFailedWithMessage', { message }))
          this.thinkingStatus = { icon: '❌', text: this.$t('agentChat.modelCallFailed') }
          this.scrollToBottom()
          break
        }
        case 'error':
          this.thinkingStatus = { icon: '❌', text: this.$t('agentChat.errorOccurred') }; this.workflowStatus = 'finished'; this.currentTaskId = null
          this.markRunningStepsFailed(event.message || this.$t('agentChat.workflowError')); this.appendStreamError(event.message || this.$t('agentChat.workflowError')); break
        case 'confirm_request':
          this.handleConfirmRequest(eventData); break
        case 'context_compression_started':
          this.thinkingStatus = { icon: '📦', text: this.$t('agentChat.compressingContext') }; break
        case 'context_compression_finished':
          this.thinkingStatus = { icon: '✅', text: this.$t('agentChat.contextCompressed') }
          // 更新上下文 token 数
          if (eventData.compressed_tokens !== undefined) {
            this.currentContextTokens = eventData.compressed_tokens
          }
          break
      }
      this.publishRunSnapshot?.()
    },
    archiveStreamingContentToStep(nodeId) {
      const content = String(this.streamingContent || '').trim()
      if (!content) return
      const step = nodeId
        ? this.nodeSteps.find(s => s.id === nodeId && s.status === 'running')
        : this.nodeSteps.findLast ? this.nodeSteps.findLast(s => s.status === 'running') : [...this.nodeSteps].reverse().find(s => s.status === 'running')
      if (!step) return
      if (!step.segments) step.segments = []
      const lastSeg = step.segments[step.segments.length - 1]
      if (lastSeg && lastSeg.type === 'assistant-note') {
        lastSeg.content = `${lastSeg.content}\n\n${content}`
      } else {
        step.segments.push({ type: 'assistant-note', content })
      }
      this.streamingContent = ''
    },
    ensureProcessVisibleForFirstRun() {
      if (!this.processCollapsed) return
      const hasActiveProcess = (this.nodeSteps || []).length > 0 || (this.currentToolCalls || []).length > 0 || !!this.reasoningContent
      if (hasActiveProcess) return
      const hasHistoricalProcess = (this.messages || []).some(msg => {
        if (!msg || msg.role !== 'assistant') return false
        return (msg.nodeSteps && msg.nodeSteps.length > 0)
          || (msg.toolCalls && msg.toolCalls.length > 0)
          || !!msg.reasoning
      })
      if (!hasHistoricalProcess) this.processCollapsed = false
    },
    findStepForHarnessFeedback(nodeId, batchId) {
      const steps = [...this.nodeSteps].reverse()
      if (nodeId) {
        const exact = steps.find(s => s.id === nodeId && (!batchId || (s.toolCalls || []).some(t => t.batchId === batchId)))
        if (exact) return exact
        const byNode = steps.find(s => s.id === nodeId)
        if (byNode) return byNode
      }
      if (batchId) {
        const byBatch = steps.find(s => (s.toolCalls || []).some(t => t.batchId === batchId))
        if (byBatch) return byBatch
      }
      return steps.find(s => s.status === 'running') || steps.find(s => (s.toolCalls || []).length) || null
    },
    showConfirmDialog(request) {
      this.confirmDialog = { ...request, visible: true, submitting: false, sudoPassword: '' }
      this.thinkingStatus = { icon: '⚠️', text: this.$t('agentChat.waitForConfirm', { action: request.action }) }
    },
    showNextConfirmDialog() {
      const next = this.confirmQueue.shift()
      if (next) this.showConfirmDialog(next)
      else this.confirmDialog = { visible: false, submitting: false, confirmId: '', action: '', description: '', requireSudo: false, sudoPassword: '' }
    },
    async handleConfirmRequest(event) {
      const payload = event?.data || event || {}
      const request = {
        confirmId: payload.confirm_id || payload.confirmId,
        action: payload.action || this.$t('agentChat.unknownAction'),
        description: payload.description || '',
        requireSudo: payload.require_sudo || payload.requireSudo || false,
      }
      if (!request.confirmId) return
      if (this.confirmDialog.visible || this.confirmDialog.submitting) {
        this.confirmQueue.push(request)
        return
      }
      this.showConfirmDialog(request)
    },
    async submitConfirmDialog(approved, password) {
      const current = { ...this.confirmDialog }
      if (!current.confirmId || current.submitting) return
      if (approved && current.requireSudo && !password) { this.setTimedInputError(this.$t('agentChat.enterSudoPassword')); return }
      const headers = getAdminAuthHeaders({ 'Content-Type': 'application/json' })
      if (!headers) { this.setTimedInputError(this.$t('auth.invalidToken')); return }
      this.confirmDialog = { ...this.confirmDialog, submitting: true }
      const baseUrl = import.meta.env.VITE_API_BASE_URL || ''
      try {
        const body = { approved, request_id: current.confirmId }
        if (current.requireSudo && password) body.sudo_password = password
        const res = await fetch(`${baseUrl}/api/confirm/${current.confirmId}`, { method: 'POST', headers, body: JSON.stringify(body) })
        if (handleAdminFetchAuthError(res)) throw new Error(this.$t('auth.invalidToken'))
        const data = await res.json().catch(() => ({}))
        if (!res.ok || data.success === false) throw new Error(data.error || data.message || `HTTP ${res.status}`)
        this.thinkingStatus = approved ? { icon: '✅', text: this.$t('agentChat.confirmed') } : { icon: '🚫', text: this.$t('agentChat.denied') }
        this.showNextConfirmDialog()
      } catch (error) {
        console.error('确认失败:', error)
        this.thinkingStatus = { icon: '❌', text: this.$t('agentChat.confirmFailed') }
        this.confirmDialog = { ...this.confirmDialog, submitting: false }
      }
    },
    getNodeTypeLabel(type) {
      const key = String(type || '').toLowerCase()
      const labels = {
        'llm': 'LLM',
        'llmnode': 'LLM',
        'human': this.$t('agentChat.nodeTypes.human'),
        'humannode': this.$t('agentChat.nodeTypes.human'),
        'function': this.$t('agentChat.nodeTypes.function'),
        'functionnode': this.$t('agentChat.nodeTypes.function'),
        'mcp': 'MCP',
        'mcpnode': 'MCP',
        'parallel': this.$t('agentChat.nodeTypes.parallel'),
        'parallelgroup': this.$t('agentChat.nodeTypes.parallel'),
        'agent': 'Agent',
        'agentnode': 'Agent',
      }
      return labels[key] || type
    },
    normalizeToolResult(result) {
      if (result === null || result === undefined) return ''
      if (typeof result === 'string') return result
      try { return JSON.stringify(result) } catch { return String(result) }
    },
    localizeNodeStep(step) {
      return localizeBuiltinRuntimeStep(step, this.currentWorkflowId, this.$t.bind(this))
    },
    localizeNodeSteps(steps) {
      const localizedSteps = localizeBuiltinRuntimeSteps(steps, this.currentWorkflowId, this.$t.bind(this))
      if (!Array.isArray(localizedSteps)) return localizedSteps
      return localizedSteps.map((step) => {
        if (!step) return step
        return step.expanded === undefined ? { ...step, expanded: false } : step
      })
    },
    extractPostEditGuardMeta(content) {
      const raw = typeof content === 'string' ? content : String(content || '')
      const guardRegex = /\[POST_EDIT_GUARD\]([\s\S]*?)\[\/POST_EDIT_GUARD\]/m
      const match = raw.match(guardRegex)
      if (!match) return { content: raw, status: null, reason: '', nextStep: '', rawGuard: null }
      const guardBody = (match[1] || '').trim()
      const cleaned = raw.replace(guardRegex, '').replace(/\n{3,}/g, '\n\n').trim() || this.$t('agentChat.noTextReply')
      const parsed = {}
      guardBody.split('\n').forEach(line => { const idx = line.trim().indexOf('='); if (idx > 0) parsed[line.trim().slice(0, idx).trim()] = line.trim().slice(idx + 1).trim() })
      const rs = String(parsed.recommended_status || '').toLowerCase().trim()
      let status = null
      if (['completed', 'partial', 'blocked'].includes(rs)) status = rs
      else if (parsed.blocked_reason || parsed.guard_reason) status = 'partial'
      return { content: cleaned, status, reason: parsed.guard_reason || parsed.blocked_reason || '', nextStep: parsed.next_step || '', rawGuard: guardBody }
    },
    normalizeAssistantMessages(messages) {
      if (!Array.isArray(messages)) return []
      return messages.map(msg => {
        if (!msg) return msg
        let normalizedMsg = msg
        if (msg.role === 'assistant') {
          if (msg.reasoning && msg.reasoningExpanded === undefined) {
            normalizedMsg = { ...normalizedMsg, reasoningExpanded: false }
          }
          if (msg.nodeSteps) {
            normalizedMsg = { ...normalizedMsg, nodeSteps: this.localizeNodeSteps(msg.nodeSteps) }
          }
          if (typeof msg.content !== 'string') return normalizedMsg
          const guardMeta = this.extractPostEditGuardMeta(msg.content)
          if (!guardMeta.status && guardMeta.content === msg.content) return normalizedMsg
          return { ...normalizedMsg, content: guardMeta.content, deliveryStatus: msg.deliveryStatus || guardMeta.status, deliveryReason: msg.deliveryReason || guardMeta.reason, deliveryNextStep: msg.deliveryNextStep || guardMeta.nextStep }
        }
        return normalizedMsg
      })
    },
    resolveToolCallStatus({ status, result }) {
      const ns = String(status || '').toLowerCase().trim()
      const nr = this.normalizeToolResult(result).toLowerCase()
      const prefix = nr.slice(0, 240)
      const map = {
        running: { status: 'running', text: this.$t('agentChat.toolStatus.running'), icon: '🔧', verb: this.$t('agentChat.toolStatus.running') },
        succeeded: { status: 'completed', text: this.$t('agentChat.toolStatus.completed'), icon: '', verb: '' },
        success: { status: 'completed', text: this.$t('agentChat.toolStatus.completed'), icon: '', verb: '' },
        completed: { status: 'completed', text: this.$t('agentChat.toolStatus.completed'), icon: '', verb: '' },
        failed: { status: 'failed', text: this.$t('agentChat.toolStatus.failed'), icon: '', verb: '' },
        error: { status: 'failed', text: this.$t('agentChat.toolStatus.failed'), icon: '', verb: '' },
        timeout: { status: 'failed', text: this.$t('agentChat.toolStatus.timeout'), icon: '', verb: '' },
        cancelled: { status: 'failed', text: this.$t('agentChat.toolStatus.cancelled'), icon: '', verb: '' },
        canceled: { status: 'failed', text: this.$t('agentChat.toolStatus.cancelled'), icon: '', verb: '' },
        interrupted: { status: 'failed', text: this.$t('agentChat.toolStatus.interrupted'), icon: '', verb: '' },
      }
      if (map[ns]) return map[ns]
      if (prefix.includes('[tool_success]')) return map.succeeded
      if (prefix.includes('[tool_failed:')) return map.failed
      if (prefix.includes('[timeout]')) return map.failed
      if (prefix.includes('[rejected]')) return map.failed
      if (['[timeout]', 'timed out', 'timeout', '超时'].some(h => nr.includes(h))) return map.failed
      if (['[tool_failed', '[error]', 'traceback', 'execution failed', 'tool_error'].some(h => nr.includes(h))) return map.failed
      if (['[rejected]', 'cancelled', 'canceled', 'rejected'].some(h => nr.includes(h))) return map.failed
      return map.succeeded
    },
    parseTodoResult(result) {
      if (!result) return
      const lines = result.split('\n').filter(l => l.trim())
      const items = []
      for (const line of lines) {
        if (line.startsWith('(') && line.includes('completed')) continue
        if (line === 'No todos.') { this.todoItems = []; return }
        const cm = line.match(/^\[x\]\s*(.+)$/); const im = line.match(/^\[>\]\s*(.+?)\s*<-\s*(.+)$/); const pm = line.match(/^\[ \]\s*(.+)$/)
        if (cm) items.push({ content: cm[1].trim(), status: 'completed', activeForm: '' })
        else if (im) items.push({ content: im[1].trim(), status: 'in_progress', activeForm: im[2].trim() })
        else if (pm) items.push({ content: pm[1].trim(), status: 'pending', activeForm: '' })
      }
      this.todoItems = items
    },
    markNodeStepFailed(nodeId, errorMsg) {
      const now = Date.now()
      const step = nodeId ? this.nodeSteps.find(s => s.id === nodeId) : this.nodeSteps.find(s => s.status === 'running')
      if (!step) return
      step.status = 'failed'
      if (step.startTime) { const e = (now - step.startTime) / 1000; step.elapsed = e < 1 ? `${Math.round(e * 1000)}ms` : `${e.toFixed(1)}s` }
      if (errorMsg) step.error = errorMsg
    },
    markRunningStepsFailed(errorMsg) {
      const now = Date.now()
      this.nodeSteps.forEach(step => {
        if (step.status === 'running') {
          step.status = 'failed'
          if (step.startTime) { const e = (now - step.startTime) / 1000; step.elapsed = e < 1 ? `${Math.round(e * 1000)}ms` : `${e.toFixed(1)}s` }
          if (errorMsg) step.error = errorMsg
        }
      })
    },
    markRunningStepsCancelled(reason) {
      const now = Date.now()
      const cancelledText = reason || this.$t('agentChat.interrupted')
      const markTool = (tool) => {
        if (!tool || tool.status !== 'running') return
        tool.status = 'failed'
        tool.statusText = cancelledText
        if (tool.startTime) { const e = (now - tool.startTime) / 1000; tool.elapsed = e < 1 ? `${Math.round(e * 1000)}ms` : `${e.toFixed(1)}s` }
      }
      this.nodeSteps.forEach(step => {
        if (step.status === 'running') {
          step.status = 'cancelled'
          if (step.startTime) { const e = (now - step.startTime) / 1000; step.elapsed = e < 1 ? `${Math.round(e * 1000)}ms` : `${e.toFixed(1)}s` }
        }
        ;(step.toolCalls || []).forEach(markTool)
        ;(step.segments || []).forEach(seg => { if (seg.type === 'tool') markTool(seg) })
      })
      ;(this.currentToolCalls || []).forEach(markTool)
    },
    appendStreamError(errorMsg) {
      if (!errorMsg) return
      const errorLine = this.$t('agentChat.errorPrefix', { message: errorMsg })
      if (!this.streamingContent) { this.streamingContent = errorLine; return }
      if (!this.streamingContent.includes(errorLine)) this.streamingContent += `\n\n${errorLine}`
    },
    toggleReasoning(index) {
      const msg = this.messages[index]
      if (msg) msg.reasoningExpanded = !msg.reasoningExpanded
    },
    async editMessage(msg, index, newText) {
      if (this.isStreaming) return
      // 计算该消息是第几条用户消息
      let userMsgCount = 0
      for (let i = 0; i <= index; i++) {
        if (this.messages[i].role === 'user') userMsgCount++
      }
      // 截断前端消息（保留到该用户消息之前）
      this.messages.splice(index)
      this.updateCurrentConversation()
      // 截断后端 checkpoint
      if (this.conversationId) {
        try {
          const baseUrl = import.meta.env.VITE_API_BASE_URL || ''
          const headers = getAdminAuthHeaders({ 'Content-Type': 'application/json' })
          if (!headers) return
          const response = await fetch(`${baseUrl}/api/workflow/truncate`, {
            method: 'POST',
            headers,
            body: JSON.stringify({ workflow_id: this.currentWorkflowId, conversation_id: this.conversationId, keep_count: userMsgCount }),
          })
          handleAdminFetchAuthError(response)
        } catch (e) { console.error('截断消息失败:', e) }
      }
      // 用编辑后的文本直接发送
      this.inputText = newText
      this.$nextTick(() => this.sendMessage())
    },
    async copyMessage(msg, index) {
      try { await navigator.clipboard.writeText(msg.content || '') }
      catch { const ta = document.createElement('textarea'); ta.value = msg.content || ''; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); document.body.removeChild(ta) }
      this.messages[index].copied = true
      setTimeout(() => { this.messages[index].copied = false }, 2000)
    },
    async feedbackMessage(msg, index, type) {
      const newFeedback = msg.feedback === type ? null : type
      this.messages[index].feedback = newFeedback
      try { await this.convApi.submitFeedback(this.currentWorkflowId, this.conversationId, index, newFeedback, this.shareToken) } catch (e) {}
    },
    async loadFeedbackFromDb() {
      if (!this.conversationId) return
      try {
        const res = await this.convApi.getFeedback(this.currentWorkflowId, this.conversationId, this.shareToken)
        const feedbacks = res.feedbacks || {}
        for (const [index, feedback] of Object.entries(feedbacks)) { const i = parseInt(index); if (this.messages[i]) this.messages[i].feedback = feedback }
      } catch (e) {}
    },
    scrollToBottom(force = false) {
      this.$nextTick(() => {
        const c = this.$refs.messagesContainer
        if (!c) return
        if (force) {
          c.scrollTop = c.scrollHeight
          return
        }
        // 只有用户已经在底部附近时才自动滚动
        const threshold = 100 // 距离底部 100px 内视为"在底部"
        const isNearBottom = c.scrollHeight - c.scrollTop - c.clientHeight < threshold
        if (isNearBottom) {
          c.scrollTop = c.scrollHeight
        }
      })
    },
    goBack() { this.$router.push(`/workflows/${this.currentWorkflowId}`) },
  },
}
</script>
<style scoped>
:root {
  --bg-app: #ffffff; --bg-sidebar: #f8fafc; --bg-main: #f8fafc; --bg-hover: #f1f5f9;
  --bg-user-msg: #f4f4f5; --bg-panel: #fbfbfb; --bg-terminal: #0f172a;
  --border-light: #f1f1f1; --border-base: #e4e4e7; --border-dark: #d4d4d8;
  --border-color: #e4e4e7; /* compat alias */
  --text-main: #18181b; --text-sec: #52525b; --text-secondary: #52525b; --text-muted: #a1a1aa;
  --accent-main: #3b82f6; --accent-color: #3b82f6; --accent-bg: #dbeafe;
  --danger-main: #ef4444; --success-color: #10b981;
  --primary-color: #18181b; --primary-hover: #000000;
  --radius-sm: 8px; --radius-md: 12px; --radius-lg: 18px; --radius-full: 9999px;
  --shadow-sm: 0 1px 2px 0 rgba(0,0,0,0.05);
  --shadow-md: 0 4px 6px -1px rgba(0,0,0,0.03), 0 2px 4px -1px rgba(0,0,0,0.02);
  --shadow-float: 0 12px 24px -6px rgba(0,0,0,0.08), 0 4px 10px -4px rgba(0,0,0,0.04);
  --font-mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
}
* { box-sizing: border-box; }
.mono-font { font-family: var(--font-mono); }
.agent-chat { display: flex; height: 100vh; width: 100%; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, "PingFang SC", "Microsoft YaHei", sans-serif; -webkit-font-smoothing: antialiased; background: linear-gradient(180deg, #f8fafc 0%, #eef3f8 100%); margin: -24px; width: calc(100% + 48px); }
.agent-chat.public-chat { margin: 0; width: 100%; height: 100vh; overflow: hidden; }

.chevron-icon {
  flex-shrink: 0;
  color: var(--text-muted);
  transition: transform 0.18s ease, color 0.18s ease;
}

.chevron-icon.open {
  transform: rotate(90deg);
  color: var(--text-sec);
}

/* Chat Main */
.chat-main { flex: 1; display: flex; flex-direction: column; background: linear-gradient(180deg, rgba(255,255,255,0.76), rgba(248,250,252,0.94)); position: relative; min-width: 400px; }
.public-chat .chat-main { min-width: 0; }
.top-bar { padding: 12px 24px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--border-light); z-index: 10; background: rgba(255,255,255,0.85); backdrop-filter: blur(12px); position: relative; }
.top-bar-title { font-size: 15px; font-weight: 600; letter-spacing: -0.3px; }
.model-selector { display: flex; align-items: center; gap: 6px; padding: 4px 10px; background: var(--bg-app); border: 1px solid var(--border-base); border-radius: var(--radius-full); cursor: pointer; font-size: 12px; font-weight: 500; color: var(--text-sec); transition: all 0.2s; }
.model-selector:hover { border-color: var(--border-dark); color: var(--text-main); box-shadow: var(--shadow-sm); }
.model-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--accent-main); }
.model-dropdown { position: absolute; top: 100%; right: 24px; background: white; border: 1px solid var(--border-base); border-radius: var(--radius-md); box-shadow: var(--shadow-float); z-index: 100; min-width: 200px; padding: 4px; }
.model-option { padding: 8px 12px; border-radius: 6px; cursor: pointer; font-size: 13px; color: var(--text-sec); transition: all 0.15s; }
.model-option:hover { background: var(--bg-hover); }
.model-option.active { background: var(--accent-bg); color: var(--accent-main); font-weight: 500; }

.public-header { padding: 24px; text-align: center; border-bottom: 1px solid var(--border-light); }
.public-header h2 { font-size: 18px; font-weight: 600; margin: 0 0 4px; }
.public-header p { font-size: 13px; color: var(--text-muted); margin: 0; }

/* Messages */
.messages-container { flex: 1; overflow-y: auto; padding: 24px 0 160px; display: flex; flex-direction: column; scroll-behavior: smooth; scrollbar-gutter: stable; scrollbar-width: thin; scrollbar-color: rgba(100, 116, 139, 0.72) rgba(226, 232, 240, 0.55); }
.messages-container::-webkit-scrollbar { width: 10px; }
.messages-container::-webkit-scrollbar-track { background: rgba(226, 232, 240, 0.55); border-radius: var(--radius-full); margin: 12px 0 152px; }
.messages-container::-webkit-scrollbar-thumb { background: linear-gradient(180deg, rgba(100, 116, 139, 0.78), rgba(71, 85, 105, 0.88)); border: 2px solid rgba(248, 250, 252, 0.9); border-radius: var(--radius-full); }
.messages-container::-webkit-scrollbar-thumb:hover { background: linear-gradient(180deg, rgba(71, 85, 105, 0.92), rgba(51, 65, 85, 0.98)); }

/* Config Panel */
.config-panel-wrapper { width: 100%; display: flex; justify-content: center; padding: 0 24px; margin-bottom: 16px; }
.config-panel { width: 100%; max-width: 880px; border: 1px solid rgba(226, 232, 240, 0.95); border-radius: 18px; overflow: hidden; background: rgba(255,255,255,0.88); box-shadow: 0 20px 42px -36px rgba(15, 23, 42, 0.35); backdrop-filter: blur(12px); }
.config-header { padding: 13px 16px; background: linear-gradient(180deg, rgba(248,250,252,0.98), rgba(241,245,249,0.92)); cursor: pointer; display: flex; justify-content: space-between; align-items: center; font-size: 14px; font-weight: 600; color: var(--text-main); }
.config-body { padding: 20px; display: flex; flex-direction: column; gap: 16px; }
.form-field { display: flex; flex-direction: column; gap: 6px; }
.form-field label { font-size: 13px; font-weight: 500; color: var(--text-secondary); line-height: 1.5; }
.form-field input, .form-field select, .form-field textarea { padding: 10px 14px; border: 1px solid var(--border-color); border-radius: 6px; font-size: 14px; outline: none; font-family: inherit; line-height: 1.5; }
.form-field input:focus, .form-field select:focus, .form-field textarea:focus { border-color: var(--accent-color); box-shadow: 0 0 0 3px rgba(59,130,246,0.1); }
.form-field.invalid input, .form-field.invalid select, .form-field.invalid textarea { border-color: var(--danger-main); }
.required-mark { color: var(--danger-main); margin-left: 3px; }
.field-error { color: var(--danger-main); font-size: 12px; line-height: 1.4; }
.form-field textarea { resize: vertical; min-height: 60px; }
.file-upload-field { display: flex; align-items: center; gap: 8px; }
.file-upload-btn { display: inline-flex; align-items: center; justify-content: center; padding: 8px 16px; border: 1px dashed var(--border-color); border-radius: 6px; font-size: 13px; color: var(--accent-color); cursor: pointer; transition: all 0.2s; }
.file-upload-btn:hover:not(.disabled) { border-color: var(--accent-color); background: rgba(59,130,246,0.05); }
.file-upload-btn.disabled { opacity: 0.5; cursor: not-allowed; }
.file-uploaded { display: flex; align-items: center; gap: 8px; padding: 8px 12px; background: var(--bg-light); border: 1px solid var(--border-color); border-radius: 6px; font-size: 13px; }
.file-uploaded .file-name { color: var(--text-primary); max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.file-uploaded .file-remove { background: none; border: none; color: var(--text-secondary); cursor: pointer; font-size: 16px; padding: 0 4px; line-height: 1; }
.file-uploaded .file-remove:hover { color: var(--error); }
.files-upload-field { display: flex; flex-direction: column; gap: 6px; }
.files-list { display: flex; flex-direction: column; gap: 4px; }
.btn-start { padding: 10px 20px; background: var(--primary-color, #18181b); color: white; border: none; border-radius: 8px; font-size: 14px; font-weight: 500; cursor: pointer; transition: all 0.2s; }
.btn-start:hover { background: var(--primary-hover, #000000); }
.form-start-bar { width: 100%; max-width: 880px; margin: -8px auto 16px; padding: 0 24px; display: flex; align-items: center; justify-content: space-between; gap: 16px; color: var(--text-sec); font-size: 13px; line-height: 1.6; }
.form-start-bar .btn-start { flex-shrink: 0; }

.type-warning { text-align: center; padding: 8px; font-size: 12px; color: #f59e0b; background: #fffbeb; border-radius: 6px; margin: 0 24px 8px; }

/* Welcome */
.welcome-area { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 16px; color: var(--text-muted); }
.workflow-error-panel { width: min(560px, calc(100% - 32px)); margin: 72px auto 0; padding: 20px 22px; border: 1px solid rgba(239,68,68,0.28); border-radius: 8px; background: #fff5f5; color: var(--danger-main); }
.workflow-error-panel h3 { margin: 0 0 8px; font-size: 16px; line-height: 1.4; color: #991b1b; }
.workflow-error-panel p { margin: 0; font-size: 14px; line-height: 1.6; color: #7f1d1d; word-break: break-word; }
.welcome-icon-large { font-size: 48px; font-weight: 600; color: var(--text-secondary); }
.welcome-area h3 { font-size: 20px; font-weight: 600; color: var(--text-main); margin: 0; line-height: 1.4; }
.welcome-area p { font-size: 15px; margin: 0; line-height: 1.6; }
.standalone-start-wrapper { margin-top: 4px; }
.btn-start.standalone { min-width: 160px; }
/* Show All Messages */
.show-all-bar { display: flex; justify-content: center; padding: 8px 24px; }
.show-all-btn { display: inline-flex; align-items: center; gap: 6px; padding: 6px 16px; background: var(--bg-hover, #f1f1f1); border-radius: 20px; font-size: 12px; color: var(--text-muted, #a1a1aa); cursor: pointer; transition: all 0.15s; border: 1px solid var(--border-base, #e4e4e7); }
.show-all-btn:hover { background: var(--bg-sidebar, #fafafa); color: var(--text-sec, #52525b); border-color: var(--border-dark, #d4d4d8); }
.chat-display-toolbar { position: sticky; top: 12px; z-index: 3; display: flex; justify-content: center; padding: 4px 24px 12px; pointer-events: none; }
.process-toggle-pill {
  pointer-events: auto;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  border-radius: 999px;
  border: 1px solid rgba(228, 228, 231, 0.96);
  background: rgba(255, 255, 255, 0.88);
  backdrop-filter: blur(10px);
  box-shadow: 0 20px 40px -30px rgba(15, 23, 42, 0.4);
  color: var(--text-sec, #52525b);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.18s ease;
}
.process-toggle-pill:hover {
  transform: translateY(-1px);
  color: var(--text-main, #18181b);
  border-color: rgba(59, 130, 246, 0.28);
}
/* Info Panel */
.info-panel {
  width: 308px;
  position: relative;
  background: linear-gradient(180deg, rgba(248,250,252,0.92), rgba(241,245,249,0.96));
  border-left: 1px solid rgba(226, 232, 240, 0.95);
  box-shadow: inset 1px 0 0 rgba(255,255,255,0.7);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  transition: width 0.2s;
}
.info-panel.collapsed {
  width: 42px;
  min-width: 42px;
}
.info-panel-toggle {
  position: absolute;
  top: 50%;
  left: 6px;
  transform: translateY(-50%);
  z-index: 10;
  background: rgba(255,255,255,0.9);
  border: 1px solid var(--border-base, #e4e4e7);
  border-radius: 6px;
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: var(--text-muted, #a1a1aa);
  transition: all 0.2s;
  padding: 0;
}
.info-panel-toggle:hover {
  background: var(--bg-hover, #f1f5f9);
  color: var(--text-main, #18181b);
  border-color: var(--border-dark, #d4d4d8);
}
.info-panel-resize-handle {
  position: absolute;
  left: -3px;
  top: 0;
  width: 6px;
  height: 100%;
  cursor: col-resize;
  z-index: 10;
}

.panel-content {
  flex: 1;
  overflow-y: auto;
  padding: 20px 18px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.panel-section {
  margin-bottom: 0;
  padding: 14px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid rgba(226, 232, 240, 0.9);
  box-shadow: 0 16px 30px -28px rgba(15, 23, 42, 0.32);
}

.filter-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  font-size: 13px;
  color: var(--text-secondary);
  user-select: none;
}
.filter-toggle input[type="checkbox"] { cursor: pointer; }

.section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-sec);
  margin-bottom: 10px;
  line-height: 1.5;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.collapsible-title {
  cursor: pointer;
  user-select: none;
}

.collapsible-title:hover {
  color: var(--text-main);
}

.section-title-main {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.section-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 42px;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(219, 234, 254, 0.82);
  color: #2563eb;
  font-size: 11px;
  font-weight: 600;
}

.section-content { font-size: 13px; color: var(--text-secondary); line-height: 1.7; }

.tool-config-body {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.tool-group-panel {
  margin-bottom: 0;
  padding: 12px;
  border-radius: 14px;
  background: rgba(248, 250, 252, 0.92);
  border: 1px solid rgba(226, 232, 240, 0.95);
}

.tool-group-header { display: flex; justify-content: space-between; align-items: center; gap: 12px; font-size: 12px; color: var(--text-secondary); margin-bottom: 8px; line-height: 1.5; }
.btn-toggle-all { background: rgba(219, 234, 254, 0.74); border: 1px solid rgba(191, 219, 254, 0.95); border-radius: 999px; font-size: 11px; color: var(--accent-color); cursor: pointer; padding: 4px 8px; }
.tool-list { display: flex; flex-direction: column; gap: 8px; }
.tool-item { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--text-secondary); cursor: pointer; padding: 8px 10px; line-height: 1.5; border-radius: 10px; background: rgba(255, 255, 255, 0.88); border: 1px solid rgba(226, 232, 240, 0.9); }
.tool-item:hover { border-color: rgba(191, 219, 254, 0.95); background: rgba(239, 246, 255, 0.92); }
.tool-item input { margin: 0; }
.tool-empty { font-size: 12px; color: var(--text-muted); text-align: center; padding: 14px; border-radius: 12px; background: rgba(248, 250, 252, 0.92); }
.btn-reset-tools { margin-top: 4px; background: rgba(255,255,255,0.92); border: 1px solid var(--border-color); border-radius: 10px; padding: 8px 12px; font-size: 12px; color: var(--text-secondary); cursor: pointer; width: 100%; }
.btn-reset-tools:hover { background: #f8fafc; color: var(--text-main); }
.model-permission-section { margin-top: auto; }
.permission-field { display: flex; flex-direction: column; gap: 8px; font-size: 12px; color: var(--text-secondary); }
.permission-select { width: 100%; border: 1px solid var(--border-color); border-radius: 10px; background: rgba(255,255,255,0.92); color: var(--text-main); padding: 9px 10px; font-size: 13px; outline: none; }
.permission-select:focus { border-color: var(--accent-main); box-shadow: 0 0 0 3px rgba(79,70,229,0.12); }
.permission-hint { margin-top: 8px; color: var(--text-tertiary); font-size: 12px; line-height: 1.5; }
.panel-actions { padding: 16px 18px 18px; border-top: 1px solid rgba(226, 232, 240, 0.92); background: rgba(248,250,252,0.7); }
.btn-back { width: 100%; padding: 10px 12px; background: rgba(255,255,255,0.92); border: 1px solid var(--border-color); border-radius: 12px; font-size: 13px; color: var(--text-secondary); cursor: pointer; transition: all 0.2s; }
.btn-back:hover { background: #f8fafc; color: var(--text-main); border-color: rgba(191, 219, 254, 0.95); }

/* Approval bar */
/* Responsive */
@media (max-width: 1024px) { .info-panel { display: none; } }
@media (max-width: 768px) {
  .agent-chat { margin: -24px 0; width: 100%; }
  .agent-chat { height: calc(100vh + 48px); }
  .chat-main { min-width: 0; }
  .chat-sidebar { display: none; }
  .messages-container { padding: 18px 0 150px; }
  .config-panel-wrapper { padding: 0 12px; }
}
</style>
