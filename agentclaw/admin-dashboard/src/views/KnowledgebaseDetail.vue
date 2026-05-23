<template>
  <div class="kb-detail-page">
    <!-- Header -->
    <div class="detail-header">
      <div class="detail-header-left">
        <button class="back-btn" @click="router.push('/knowledgebases')">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 12H5"/><path d="M12 19l-7-7 7-7"/></svg>
        </button>
        <h2 class="detail-title">{{ knowledgebase.name }}</h2>
      </div>
      <n-button type="primary" size="small" @click="openUploadDialog">
        {{ isUploading ? t('knowledgebaseDetail.uploadQueue') : t('knowledgebaseDetail.uploadDocument') }}
      </n-button>
    </div>

    <!-- Tab bar -->
    <div class="config-tabs">
      <button :class="['tab-btn', { active: activeTab === 'files' }]" @click="activeTab = 'files'">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
        {{ t('knowledgebaseDetail.tabs.files') }}
      </button>
      <button :class="['tab-btn', { active: activeTab === 'test' }]" @click="activeTab = 'test'">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
        {{ t('knowledgebaseDetail.tabs.searchTest') }}
      </button>
      <button :class="['tab-btn', { active: activeTab === 'logs' }]" @click="activeTab = 'logs'">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
        {{ t('knowledgebaseDetail.tabs.logs') }}
      </button>
      <button :class="['tab-btn', { active: activeTab === 'config' }]" @click="activeTab = 'config'">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
        {{ t('knowledgebaseDetail.tabs.config') }}
      </button>
    </div>

    <!-- ═══ Tab: Files ═══ -->
    <div v-show="activeTab === 'files'" class="tab-body">
      <div class="tab-toolbar">
        <n-input v-model:value="documentQuery" :placeholder="t('knowledgebaseDetail.searchDocument')" clearable size="small" style="width: 320px;" />
        <span class="toolbar-count">{{ t('knowledgebaseDetail.documentsCount', { count: documents.length }) }}</span>
      </div>
      <n-data-table v-if="filteredDocuments.length" :columns="docColumns" :data="filteredDocuments" :bordered="false" size="small" />
      <div v-else class="empty-state">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#d0d5dd" stroke-width="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
        <p>{{ t('knowledgebaseDetail.noDocuments') }}</p>
      </div>
    </div>
    <!-- ═══ Tab: Search Test ═══ -->
    <div v-show="activeTab === 'test'" class="tab-body">
      <div class="search-layout">
        <!-- Config sidebar -->
        <aside class="search-sidebar">
          <template v-if="configForm.mode === 'hybrid'">
            <div class="sidebar-section-title">{{ t('knowledgebaseDetail.hybridWeights') }}</div>
            <div class="param-row">
              <span class="param-label">{{ t('knowledgebaseDetail.vector') }}</span><span class="param-val">{{ vectorWeight.toFixed(2) }}</span>
            </div>
            <n-slider v-model:value="vectorWeight" :min="0" :max="1" :step="0.05" @update:value="onVectorWeightChange" />
            <div class="param-row" style="margin-top: 12px;">
              <span class="param-label">{{ t('knowledgebaseDetail.keyword') }}</span><span class="param-val">{{ keywordWeight.toFixed(2) }}</span>
            </div>
            <n-slider v-model:value="keywordWeight" :min="0" :max="1" :step="0.05" @update:value="onKeywordWeightChange" />
          </template>
          <div class="sidebar-section-title" :style="configForm.mode === 'hybrid' ? 'margin-top: 20px;' : ''">{{ t('knowledgebaseDetail.searchParameters') }}</div>
          <div class="param-row"><span class="param-label">{{ t('knowledgebaseDetail.similarityThreshold') }}</span><span class="param-val">{{ testThreshold.toFixed(2) }}</span></div>
          <n-slider v-model:value="testThreshold" :min="0" :max="1" :step="0.01" />
          <div class="param-row" style="margin-top: 12px;"><span class="param-label">{{ t('knowledgebaseDetail.returnCount') }}</span><span class="param-val">{{ searchTopK }}</span></div>
          <n-slider v-model:value="searchTopK" :min="1" :max="20" :step="1" />
          <div class="sidebar-section-title" style="margin-top: 20px;">{{ t('knowledgebaseDetail.postProcessing') }}</div>
          <n-select
            v-model:value="testRerankSelection"
            :options="testRerankOptions"
            :placeholder="t('knowledgebaseDetail.selectRerankStrategy')"
            size="small"
          />
        </aside>

        <!-- Results -->
        <div class="search-results">
          <div class="search-bar">
            <n-input v-model:value="searchQuery" :placeholder="t('knowledgebaseDetail.searchQueryPlaceholder')" clearable style="flex: 1;" size="small" />
            <n-button type="primary" size="small" :loading="isSearching" @click="runSearch">{{ t('knowledgebaseDetail.runSearch') }}</n-button>
            <span v-if="results.length" class="toolbar-count">{{ t('knowledgebaseDetail.resultsCount', { count: results.length }) }}</span>
            <n-tag v-if="results.length" :type="rerankApplied ? 'success' : 'default'" size="small" :bordered="false">
              {{ rerankApplied ? t('knowledgebaseDetail.rerankApplied') : t('knowledgebaseDetail.rerankNotApplied') }}
            </n-tag>
          </div>
          <div v-if="results.length" class="result-list">
            <div v-for="item in pagedResults" :key="item.id" class="result-card">
              <div class="result-header">
                <span class="result-title">{{ item.title }}</span>
                <span class="score-badge">{{ item.score }}</span>
              </div>
              <div class="result-scores">
                <span v-if="item.denseScore !== '-'" class="score-tag dense">{{ t('knowledgebaseDetail.scoreLabels.dense') }} {{ item.denseScore }}</span>
                <span v-if="item.keywordScore !== '-'" class="score-tag keyword">{{ t('knowledgebaseDetail.scoreLabels.keyword') }} {{ item.keywordScore }}</span>
              </div>
              <p class="result-preview">{{ item.preview }}</p>
            </div>
            <n-pagination v-if="resultTotalPages > 1" v-model:page="resultPage" :page-count="resultTotalPages" size="small" style="justify-content: center; margin-top: 12px;" />
          </div>
          <div v-else class="empty-state"><p>{{ t('knowledgebaseDetail.emptySearchHint') }}</p></div>
        </div>
      </div>
    </div>
    <!-- ═══ Tab: Logs ═══ -->
    <div v-show="activeTab === 'logs'" class="tab-body">
      <div class="tab-toolbar">
        <span class="toolbar-count">{{ t('knowledgebaseDetail.logsCount', { count: searchLogs.length }) }}</span>
        <n-button v-if="searchLogs.length" text type="error" size="small" @click="handleClearLogs">{{ t('knowledgebaseDetail.clearLogs') }}</n-button>
      </div>
      <n-data-table v-if="searchLogs.length" :columns="logColumns" :data="pagedLogs" :bordered="false" size="small"
        :row-props="(row) => ({ style: 'cursor: pointer;', onClick: () => toggleLogDetail(row) })" />
      <n-drawer v-model:show="logDrawerVisible" :width="logDrawerWidth" placement="right">
        <div :style="logResizeHandleStyle" @mousedown="onLogResizeMouseDown" />
        <n-drawer-content v-if="expandedLog" :title="t('knowledgebaseDetail.searchLogTitle', { query: expandedLog.query })">
          <div class="log-meta-grid">
            <div class="log-meta-item"><span class="log-meta-label">{{ t('knowledgebaseDetail.mode') }}</span><span>{{ modeLabel(expandedLog.mode) }}</span></div>
            <div class="log-meta-item"><span class="log-meta-label">{{ t('knowledgebaseDetail.topK') }}</span><span>{{ expandedLog.topK }}</span></div>
            <div class="log-meta-item"><span class="log-meta-label">{{ t('knowledgebaseDetail.hits') }}</span><span>{{ expandedLog.hitCount }}</span></div>
            <div class="log-meta-item"><span class="log-meta-label">{{ t('knowledgebaseDetail.latency') }}</span><span>{{ expandedLog.latency }}ms</span></div>
          </div>
          <div class="block-title" style="margin-top: 16px;">{{ t('knowledgebaseDetail.hitResults') }}</div>
          <div v-for="(hit, idx) in (expandedLog.hits || [])" :key="idx" class="result-card" style="margin-bottom: 8px;">
            <div class="result-header">
              <span class="result-title">{{ hit.title }}</span>
              <span class="score-badge">{{ hit.score }}</span>
            </div>
            <p class="result-preview">{{ hit.preview }}</p>
          </div>
        </n-drawer-content>
      </n-drawer>
      <div v-if="!searchLogs.length" class="empty-state"><p>{{ t('knowledgebaseDetail.logsHint') }}</p></div>
      <n-pagination v-if="logTotalPages > 1" v-model:page="logPage" :page-count="logTotalPages" size="small" style="margin-top: 12px; justify-content: center;" />
    </div>
    <!-- ═══ Tab: Config ═══ -->
    <div v-show="activeTab === 'config'" class="tab-body">
      <!-- Basic info -->
      <div class="config-block">
        <div class="block-title">{{ t('knowledgebaseDetail.basicInfo') }}</div>
        <div class="field-grid">
          <div class="form-field"><label class="field-label">{{ t('knowledgebaseDetail.knowledgebaseName') }}</label><n-input v-model:value="configForm.name" /></div>
          <div class="form-field"><label class="field-label">{{ t('knowledgebaseDetail.rerankModel') }}</label><n-select v-model:value="configForm.rerankModelId" :options="rerankModelOptions" clearable :placeholder="t('knowledgebaseDetail.disableRerank')" /></div>
          <div class="form-field full"><label class="field-label">{{ t('common.description') }}</label><n-input v-model:value="configForm.description" type="textarea" :placeholder="t('knowledgebaseDetail.descriptionPlaceholder')" :rows="3" /></div>
        </div>
      </div>

      <!-- Retrieval strategy -->
      <div class="config-block">
        <div class="block-title">{{ t('knowledgebaseDetail.retrievalStrategy') }}</div>
        <p class="section-desc" style="margin-bottom: 14px;">{{ t('knowledgebaseDetail.retrievalStrategyHint') }}</p>
        <n-radio-group v-model:value="configForm.mode" style="margin-bottom: 16px;">
          <n-space>
            <n-radio-button v-for="opt in MODE_OPTIONS" :key="opt.value" :value="opt.value">{{ opt.label }}</n-radio-button>
          </n-space>
        </n-radio-group>
        <template v-if="configForm.mode === 'hybrid'">
          <div class="field-grid" style="margin-bottom: 16px;">
            <div class="form-field">
              <div class="param-row"><span class="param-label">{{ t('knowledgebaseDetail.vector') }}</span><span class="param-val">{{ cfgVectorWeight.toFixed(2) }}</span></div>
              <n-slider v-model:value="cfgVectorWeight" :min="0" :max="1" :step="0.05" @update:value="onCfgVectorWeightChange" />
            </div>
            <div class="form-field">
              <div class="param-row"><span class="param-label">{{ t('knowledgebaseDetail.keyword') }}</span><span class="param-val">{{ cfgKeywordWeight.toFixed(2) }}</span></div>
              <n-slider v-model:value="cfgKeywordWeight" :min="0" :max="1" :step="0.05" @update:value="onCfgKeywordWeightChange" />
            </div>
          </div>
        </template>
        <div class="field-grid">
          <div class="form-field">
            <div class="param-row"><span class="param-label">{{ t('knowledgebaseDetail.similarityThreshold') }}</span><span class="param-val">{{ configForm.threshold.toFixed(2) }}</span></div>
            <n-slider v-model:value="configForm.threshold" :min="0" :max="1" :step="0.01" />
          </div>
          <div class="form-field">
            <div class="param-row"><span class="param-label">{{ t('knowledgebaseDetail.returnCount') }}</span><span class="param-val">{{ configForm.topK }}</span></div>
            <n-slider v-model:value="configForm.topK" :min="1" :max="20" :step="1" />
          </div>
        </div>
      </div>

      <!-- Chunk strategy -->
      <div class="config-block">
        <div class="block-title">{{ t('knowledgebaseDetail.chunkStrategy') }}</div>
        <p class="section-desc" style="margin-bottom: 14px;">{{ t('knowledgebaseDetail.chunkStrategyHint') }}</p>
        <div class="field-grid">
          <div class="form-field">
            <div class="param-row"><span class="param-label">{{ t('knowledgebaseDetail.chunkSize') }}</span><span class="param-val">{{ configForm.chunkSize }}</span></div>
            <n-slider v-model:value="configForm.chunkSize" :min="100" :max="2000" :step="50" />
          </div>
          <div class="form-field">
            <div class="param-row"><span class="param-label">{{ t('knowledgebaseDetail.chunkOverlap') }}</span><span class="param-val">{{ configForm.chunkOverlap }}</span></div>
            <n-slider v-model:value="configForm.chunkOverlap" :min="50" :max="500" :step="10" />
          </div>
        </div>
      </div>

      <div style="display: flex; gap: 8px;">
        <n-button type="primary" size="small" :loading="isSavingConfig" @click="saveConfig">{{ t('knowledgebaseDetail.saveConfig') }}</n-button>
        <n-button size="small" @click="resetConfig">{{ $t('common.reset') }}</n-button>
      </div>
    </div>

    <!-- Upload dialog -->
    <DocumentUploadDialog
      v-model="showUploadDialog"
      :files="selectedFiles"
      :uploading="isUploading"
      :progress-label="uploadProgressLabel"
      :error-text="uploadError"
      @select="addUploadFiles"
      @remove="removeUploadFile"
      @clear="clearUploadFiles"
      @submit="submitUpload"
    />
  </div>
</template>
<script setup>
import { h, computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import {
  NButton, NInput, NText, NTag, NDataTable, NSlider, NSelect,
  NRadioGroup, NRadioButton, NSpace, NDrawer, NDrawerContent,
  NPagination, NTooltip, NPopconfirm, useMessage,
} from 'naive-ui'
import DocumentUploadDialog from '../components/DocumentUploadDialog.vue'
import { knowledgebaseApi, modelsApi } from '../api'
import { useKnowledgebaseUpload } from '../composables/useKnowledgebaseUpload'
import { formatDateTime } from '../composables/useFormatters'
import { useResizableDrawer } from '../composables/useResizableDrawer'
import { withReadinessRetry } from '../utils/eventualConsistency'

const TEST_RERANK_FOLLOW = '__follow__'
const TEST_RERANK_DISABLED = '__disabled__'
const DOCUMENT_POLL_INTERVAL_MS = 2500

const route = useRoute()
const router = useRouter()
const message = useMessage()
const { t } = useI18n()
const activeTab = ref('files')
const knowledgebase = ref({ name: t('knowledgebaseDetail.defaultName') })
const documents = ref([])
const results = ref([])
const resultPage = ref(1)
const searchLogs = ref([])
const logPage = ref(1)
const documentQuery = ref('')
const searchQuery = ref('')
const searchTopK = ref(8)
const testThreshold = ref(0.3)
const testRerankSelection = ref(TEST_RERANK_FOLLOW)
const vectorWeight = ref(0.7)
const keywordWeight = ref(0.3)
const cfgVectorWeight = ref(0.7)
const cfgKeywordWeight = ref(0.3)
const isSavingConfig = ref(false)
const isSearching = ref(false)
const rerankApplied = ref(false)
const rerankModels = ref([])
const configForm = ref({
  name: '', description: '', mode: 'hybrid',
  threshold: 0.3, topK: 8, chunkSize: 1200, chunkOverlap: 200, rerankModelId: '',
})
const MODE_OPTIONS = computed(() => ([
  { value: 'hybrid', label: t('knowledgebaseDetail.modes.hybrid') },
  { value: 'dense', label: t('knowledgebaseDetail.modes.dense') },
  { value: 'keyword', label: t('knowledgebaseDetail.modes.keyword') },
]))

const logDrawerVisible = ref(false)
const documentPollTimer = ref(null)
const { drawerWidth: logDrawerWidth, resizeHandleStyle: logResizeHandleStyle, onResizeMouseDown: onLogResizeMouseDown } = useResizableDrawer({ initial: 500, min: 360, max: 1000 })
const expandedLog = ref(null)
const {
  showUploadDialog, selectedFiles, isUploading, uploadProgressLabel, uploadError,
  openUploadDialog, addUploadFiles, removeUploadFile, clearUploadFiles, submitUpload,
} = useKnowledgebaseUpload(() => route.params.id, async () => { await fetchDocuments() })

const rerankModelOptions = computed(() => [
  { label: t('knowledgebaseDetail.disableRerank'), value: '' },
  ...rerankModels.value.map(m => ({ label: m.id, value: m.id })),
])
const testRerankOptions = computed(() => [
  { label: t('knowledgebaseDetail.followKnowledgebaseConfig'), value: TEST_RERANK_FOLLOW },
  { label: t('knowledgebaseDetail.disableRerank'), value: TEST_RERANK_DISABLED },
  ...rerankModels.value.map(m => ({ label: m.id, value: m.id })),
])
const filteredDocuments = computed(() => {
  const keyword = documentQuery.value.trim().toLowerCase()
  if (!keyword) return documents.value
  return documents.value.filter(item => item.name.toLowerCase().includes(keyword))
})
const logTotalPages = computed(() => Math.max(1, Math.ceil(searchLogs.value.length / 10)))
const pagedLogs = computed(() => searchLogs.value.slice((logPage.value - 1) * 10, logPage.value * 10))
const resultTotalPages = computed(() => Math.max(1, Math.ceil(results.value.length / 5)))
const pagedResults = computed(() => results.value.slice((resultPage.value - 1) * 5, resultPage.value * 5))
const hasProcessingDocuments = computed(() => documents.value.some(item => item.status === 'processing'))

const docColumns = computed(() => ([
  {
    title: t('knowledgebaseDetail.columns.documentName'),
    key: 'name',
    ellipsis: { tooltip: true },
    render: (row) => h('div', { class: 'document-name-cell' }, [
      h(NText, { strong: true }, () => row.name),
      row.error ? h('div', { class: 'document-error-text' }, row.error) : null,
    ]),
  },
  { title: t('knowledgebaseDetail.columns.chunkCount'), key: 'chunkCount', width: 80 },
  { title: t('knowledgebaseDetail.columns.uploadedAt'), key: 'updatedAt', width: 180 },
  { title: t('knowledgebaseDetail.columns.status'), key: 'status', width: 120, render: (row) => {
    const map = { ready: 'success', processing: 'info', failed: 'error' }
    const tag = h(NTag, { type: map[row.status] || 'default', size: 'small' }, () => row.statusLabel)
    if (row.status !== 'failed' || !row.error) return tag
    return h(NTooltip, { trigger: 'hover', width: 360 }, {
      trigger: () => tag,
      default: () => row.error,
    })
  }},
  { title: t('knowledgebaseDetail.columns.actions'), key: 'actions', width: 220, render: (row) => h(NSpace, { size: 8 }, () => [
    h(NButton, { text: true, type: 'primary', size: 'small', onClick: () => downloadDocument(row) }, () => t('knowledgebaseDetail.actions.download')),
    h(NButton, { text: true, type: 'primary', size: 'small', onClick: () => router.push(`/knowledgebases/${route.params.id}/documents/${row.id}`) }, () => t('knowledgebaseDetail.actions.manageChunks')),
    h(NPopconfirm, { onPositiveClick: () => handleDeleteDocument(row) }, {
      trigger: () => h(NButton, { text: true, type: 'error', size: 'small' }, () => t('knowledgebaseDetail.actions.delete')),
      default: () => t('knowledgebaseDetail.messages.deleteDocumentConfirm', { name: row.name }),
    }),
  ])},
]))

const logColumns = computed(() => ([
  { title: t('knowledgebaseDetail.columns.time'), key: 'time', width: 170 },
  { title: t('knowledgebaseDetail.columns.query'), key: 'query', ellipsis: { tooltip: true } },
  { title: t('knowledgebaseDetail.columns.searchMode'), key: 'mode', width: 100, render: (row) => h(NTag, { size: 'tiny', bordered: false }, () => modeLabel(row.mode)) },
  { title: t('knowledgebaseDetail.columns.topK'), key: 'topK', width: 70 },
  { title: t('knowledgebaseDetail.columns.hits'), key: 'hitCount', width: 70, render: (row) => h(NTag, { type: 'info', size: 'tiny' }, () => t('knowledgebaseDetail.hitCount', { count: row.hitCount })) },
  { title: t('knowledgebaseDetail.columns.latency'), key: 'latency', width: 80, render: (row) => `${row.latency}ms` },
]))

function onVectorWeightChange() { keywordWeight.value = Math.round((1 - vectorWeight.value) * 100) / 100 }
function onKeywordWeightChange() { vectorWeight.value = Math.round((1 - keywordWeight.value) * 100) / 100 }
function onCfgVectorWeightChange() { cfgKeywordWeight.value = Math.round((1 - cfgVectorWeight.value) * 100) / 100 }
function onCfgKeywordWeightChange() { cfgVectorWeight.value = Math.round((1 - cfgKeywordWeight.value) * 100) / 100 }
function toggleLogDetail(row) { expandedLog.value = row; logDrawerVisible.value = true }
function modeLabel(mode) {
  return {
    hybrid: t('knowledgebaseDetail.modes.hybrid'),
    dense: t('knowledgebaseDetail.modes.dense'),
    keyword: t('knowledgebaseDetail.modes.keyword'),
  }[mode] || mode
}
function documentStatusLabel(status) {
  return {
    ready: t('knowledgebaseDetail.documentStatus.ready'),
    pending: t('knowledgebaseDetail.documentStatus.processing'),
    processing: t('knowledgebaseDetail.documentStatus.processing'),
    failed: t('knowledgebaseDetail.documentStatus.failed'),
  }[status] || status
}
function normalizeDocumentStatus(status) {
  if (!status || status === 'pending') return 'processing'
  return status
}
function normalizeDocument(item) {
  const status = item.error && item.status !== 'processing' ? 'failed' : normalizeDocumentStatus(item.status)
  return {
    id: item.id, name: item.original_name, chunkCount: item.chunk_count || 0,
    updatedAt: formatDateTime(item.updated_at),
    status, statusLabel: documentStatusLabel(status),
    error: item.error || '',
  }
}

async function fetchKnowledgebase() {
  const response = await withReadinessRetry(() => knowledgebaseApi.get(route.params.id))
  knowledgebase.value = response
  const retrieval = response.retrieval_config || {}
  configForm.value = {
    name: response.name || '', description: response.description || '',
    mode: retrieval.mode || 'hybrid', threshold: Number(retrieval.score_threshold ?? 0.3),
    topK: Number(retrieval.top_k ?? 8), chunkSize: response.chunk_size || 1200,
    chunkOverlap: response.chunk_overlap || 200, rerankModelId: response.rerank_model_id || '',
  }
  searchTopK.value = configForm.value.topK
  testThreshold.value = configForm.value.threshold
  testRerankSelection.value = TEST_RERANK_FOLLOW
  const vw = Number(retrieval.vector_weight ?? 0.7)
  vectorWeight.value = vw; keywordWeight.value = Math.round((1 - vw) * 100) / 100
  cfgVectorWeight.value = vw; cfgKeywordWeight.value = Math.round((1 - vw) * 100) / 100
}

async function fetchDocuments() {
  const response = await knowledgebaseApi.listDocuments(route.params.id)
  documents.value = (response.documents || []).map(normalizeDocument)
  syncDocumentPolling()
}

async function downloadDocument(doc) {
  try {
    const response = await knowledgebaseApi.downloadDocument(route.params.id, doc.id)
    const blob = new Blob([response], { type: response.type || 'application/octet-stream' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a'); a.href = url; a.download = doc.name; a.click()
    URL.revokeObjectURL(url)
  } catch (error) { message.error(extractError(error, t('knowledgebaseDetail.messages.downloadFailed'))) }
}

async function handleDeleteDocument(doc) {
  try {
    await knowledgebaseApi.deleteDocument(route.params.id, doc.id)
    documents.value = documents.value.filter(item => item.id !== doc.id)
    syncDocumentPolling()
    message.success(t('knowledgebaseDetail.messages.documentDeleted'))
  } catch (error) {
    message.error(extractError(error, t('knowledgebaseDetail.messages.deleteDocumentFailed')))
  }
}

function startDocumentPolling() {
  if (documentPollTimer.value) return
  documentPollTimer.value = window.setInterval(() => {
    void fetchDocuments()
  }, DOCUMENT_POLL_INTERVAL_MS)
}

function stopDocumentPolling() {
  if (!documentPollTimer.value) return
  window.clearInterval(documentPollTimer.value)
  documentPollTimer.value = null
}

function syncDocumentPolling() {
  if (hasProcessingDocuments.value) startDocumentPolling()
  else stopDocumentPolling()
}

async function runSearch() {
  if (!searchQuery.value.trim()) { message.warning(t('knowledgebaseDetail.messages.enterSearchQuery')); return }
  isSearching.value = true; resultPage.value = 1; rerankApplied.value = false
  try {
    const params = { query: searchQuery.value, top_k: searchTopK.value, score_threshold: testThreshold.value }
    if (testRerankSelection.value === TEST_RERANK_DISABLED) params.rerank_model_id = ''
    else if (testRerankSelection.value !== TEST_RERANK_FOLLOW) params.rerank_model_id = testRerankSelection.value
    if (configForm.value.mode === 'hybrid') { params.vector_weight = vectorWeight.value; params.keyword_weight = keywordWeight.value }
    const response = await knowledgebaseApi.search(route.params.id, params)
    rerankApplied.value = response.rerank_applied === true
    results.value = (response.hits || []).map((item, idx) => ({
      id: item.chunk_id || idx, title: item.document_name || item.title || t('knowledgebaseDetail.chunkFallback', { count: idx + 1 }),
      score: (item.score ?? item.combined_score ?? 0).toFixed(3),
      denseScore: item.dense_score != null ? item.dense_score.toFixed(3) : '-',
      keywordScore: item.keyword_score != null ? item.keyword_score.toFixed(3) : '-',
      preview: item.content?.substring(0, 300) || '',
    }))
    await saveSearchLog({
      query: searchQuery.value, mode: configForm.value.mode, strategy: response.strategy || 'default',
      top_k: searchTopK.value, hit_count: results.value.length,
      latency_ms: response.latency_ms || 0, hits: results.value.slice(0, 10),
    })
    await fetchSearchLogs()
  } catch (error) { message.error(extractError(error, t('knowledgebaseDetail.messages.searchFailed'))) }
  finally { isSearching.value = false }
}

async function saveConfig() {
  isSavingConfig.value = true
  try {
    const retrievalConfig = { mode: configForm.value.mode, score_threshold: Number(configForm.value.threshold), top_k: Number(configForm.value.topK) }
    if (configForm.value.mode === 'hybrid') { retrievalConfig.vector_weight = cfgVectorWeight.value; retrievalConfig.keyword_weight = cfgKeywordWeight.value }
    await knowledgebaseApi.update(route.params.id, {
      name: configForm.value.name, description: configForm.value.description || '',
      chunk_size: Number(configForm.value.chunkSize), chunk_overlap: Number(configForm.value.chunkOverlap),
      rerank_model_id: configForm.value.rerankModelId, retrieval_config: retrievalConfig,
    })
    await fetchKnowledgebase(); message.success(t('knowledgebaseDetail.messages.configSaved'))
  } catch (error) { message.error(extractError(error, t('knowledgebaseDetail.messages.saveConfigFailed'))) }
  finally { isSavingConfig.value = false }
}

function resetConfig() {
  const retrieval = knowledgebase.value.retrieval_config || {}
  configForm.value = {
    name: knowledgebase.value.name || '', description: knowledgebase.value.description || '',
    mode: retrieval.mode || 'hybrid', threshold: Number(retrieval.score_threshold ?? 0.3),
    topK: Number(retrieval.top_k ?? 8), chunkSize: knowledgebase.value.chunk_size || 1200,
    chunkOverlap: knowledgebase.value.chunk_overlap || 200, rerankModelId: knowledgebase.value.rerank_model_id || '',
  }
  testRerankSelection.value = TEST_RERANK_FOLLOW
  const vw = Number(retrieval.vector_weight ?? 0.7)
  cfgVectorWeight.value = vw; cfgKeywordWeight.value = Math.round((1 - vw) * 100) / 100
}

async function fetchModels() {
  try { const response = await modelsApi.list(); rerankModels.value = (response.models || []).filter(item => item.model_type === 'rerank') }
  catch (error) { message.error(extractError(error, t('knowledgebaseDetail.messages.loadModelsFailed'))) }
}

async function handleClearLogs() {
  try { await knowledgebaseApi.clearSearchLogs(route.params.id); searchLogs.value = []; logPage.value = 1; message.success(t('knowledgebaseDetail.messages.logsCleared')) }
  catch (error) { message.error(extractError(error, t('knowledgebaseDetail.messages.clearLogsFailed'))) }
}

function extractError(error, fallback) {
  return error?.response?.data?.detail?.error || error?.response?.data?.detail || error?.message || fallback
}

function normalizeSearchLog(raw) {
  return {
    id: raw.id, time: formatDateTime(raw.created_at),
    query: raw.query, mode: raw.mode || '', strategy: raw.strategy || '',
    topK: raw.top_k ?? 8, hitCount: raw.hit_count ?? 0, latency: raw.latency_ms ?? 0, hits: raw.hits || [],
  }
}

async function fetchSearchLogs() {
  try { const response = await knowledgebaseApi.listSearchLogs(route.params.id); searchLogs.value = (response.logs || []).map(normalizeSearchLog) }
  catch { /* non-critical */ }
}

async function saveSearchLog(logData) {
  try { await knowledgebaseApi.createSearchLog(route.params.id, logData) } catch { /* ignore */ }
}

onMounted(async () => {
  await Promise.all([fetchKnowledgebase(), fetchModels()])
  await Promise.all([fetchDocuments(), fetchSearchLogs()])
})
onBeforeUnmount(stopDocumentPolling)
</script>
<style scoped>
.kb-detail-page { display: flex; flex-direction: column; min-height: calc(100vh - 48px); }

/* Header */
.detail-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; }
.detail-header-left { display: flex; align-items: center; gap: 12px; }
.back-btn {
  display: flex; align-items: center; justify-content: center;
  width: 32px; height: 32px; border: 1px solid #eaecf0; border-radius: 8px;
  background: #fff; cursor: pointer; color: #667085; transition: all 0.12s;
}
.back-btn:hover { border-color: #d0d5dd; color: var(--text-primary); }
.detail-title { font-size: 18px; font-weight: 600; margin: 0; }

/* Tab bar (reuse config page pattern) */
.config-tabs {
  display: flex; gap: 4px; padding: 4px;
  background: #f4f5f7; border-radius: 10px; margin-bottom: 20px;
}
.tab-btn {
  flex: 1; display: flex; align-items: center; justify-content: center; gap: 6px;
  padding: 9px 16px; border: none; border-radius: 8px;
  background: transparent; color: #667085; font-size: 13px; font-weight: 500;
  cursor: pointer; transition: all 0.15s;
}
.tab-btn:hover { color: var(--text-primary); background: rgba(255,255,255,0.6); }
.tab-btn.active { background: #fff; color: var(--text-primary); font-weight: 600; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
.tab-btn svg { opacity: 0.6; }
.tab-btn.active svg { opacity: 1; }

/* Tab body */
.tab-body { animation: fadeIn 0.15s ease; }
@keyframes fadeIn { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }

/* Toolbar */
.tab-toolbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
.toolbar-count { font-size: 13px; color: #98a2b3; }
.document-name-cell { min-width: 0; }
.document-error-text {
  margin-top: 4px;
  color: #cf1322;
  font-size: 12px;
  line-height: 1.45;
  white-space: normal;
}

/* Empty */
.empty-state { display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 60px 0; color: #98a2b3; gap: 12px; font-size: 14px; }

/* Search layout */
.search-layout { display: grid; grid-template-columns: 280px minmax(0, 1fr); gap: 20px; }
.search-sidebar {
  background: #fff; border: 1px solid #eaecf0; border-radius: 12px; padding: 16px;
  align-self: start; position: sticky; top: 16px;
}
.sidebar-section-title {
  font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;
  color: #98a2b3; margin-bottom: 12px;
}
.param-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
.param-label { font-size: 12px; color: #667085; }
.param-val { font-size: 12px; font-weight: 600; color: var(--primary); font-variant-numeric: tabular-nums; }
.search-results { min-width: 0; }
.search-bar { display: flex; align-items: center; gap: 8px; margin-bottom: 16px; }
/* Result cards */
.result-list { display: flex; flex-direction: column; gap: 12px; }
.result-card {
  background: #fff; border: 1px solid #eaecf0; border-radius: 10px; padding: 14px 16px;
}
.result-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }
.result-title { font-size: 13px; font-weight: 600; color: var(--text-primary); }
.score-badge {
  font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 6px;
  background: var(--primary-light); color: var(--primary);
}
.result-scores { display: flex; gap: 6px; margin-bottom: 8px; flex-wrap: wrap; }
.score-tag {
  font-size: 10px; padding: 1px 6px; border-radius: 4px; font-weight: 500;
}
.score-tag.dense { background: #e6f4ff; color: #1677ff; }
.score-tag.keyword { background: #fff7e6; color: #d46b08; }
.result-preview { font-size: 13px; color: #667085; line-height: 1.6; margin: 0; }

/* Log drawer meta */
.log-meta-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }
.log-meta-item {
  display: flex; justify-content: space-between; padding: 8px 12px;
  background: #f9fafb; border-radius: 8px; font-size: 13px;
}
.log-meta-label { color: #98a2b3; }

/* Config blocks */
.config-block {
  background: #fff; border: 1px solid #eaecf0; border-radius: 12px;
  padding: 20px; margin-bottom: 16px;
}
.block-title {
  font-size: 13px; font-weight: 600; color: #344054;
  margin-bottom: 16px; padding-bottom: 10px; border-bottom: 1px solid #f2f4f7;
}
.section-desc { font-size: 13px; color: #667085; margin: 0; }
.field-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; }
.form-field { min-width: 0; }
.form-field.full { grid-column: 1 / -1; }
.field-label { display: block; font-size: 13px; font-weight: 500; color: #344054; margin-bottom: 6px; }

@media (max-width: 900px) {
  .search-layout { grid-template-columns: 1fr; }
  .search-sidebar { position: static; }
  .field-grid { grid-template-columns: 1fr; }
  .config-tabs { flex-wrap: wrap; }
  .log-meta-grid { grid-template-columns: 1fr; }
  .detail-header { flex-direction: column; align-items: flex-start; gap: 12px; }
  .search-bar { flex-wrap: wrap; }
  .tab-toolbar { flex-direction: column; align-items: flex-start; gap: 8px; }
}
@media (min-width: 901px) and (max-width: 1100px) {
  .search-layout { grid-template-columns: 240px minmax(0, 1fr); }
}
</style>
