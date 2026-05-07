<template>
  <div>
    <PageHeader :title="t('knowledgebases.title')" :show-refresh="false">
      <template #actions>
        <n-text depth="3" style="font-size: 13px;">{{ t('knowledgebases.count', { count: knowledgebases.length }) }}</n-text>
        <n-button type="primary" size="small" @click="openCreate">+ {{ t('knowledgebases.create') }}</n-button>
      </template>
    </PageHeader>

    <!-- Stats -->
    <div class="stat-row">
      <div class="stat-card">
        <div class="stat-value">{{ knowledgebases.length }}</div>
        <div class="stat-label">{{ t('knowledgebases.total') }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ totalDocuments }}</div>
        <div class="stat-label">{{ t('knowledgebases.documents') }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ totalChunks }}</div>
        <div class="stat-label">{{ t('knowledgebases.chunks') }}</div>
      </div>
    </div>

    <n-spin :show="loading">
      <div v-if="knowledgebases.length" class="kb-grid">
        <div v-for="item in knowledgebases" :key="item.id" class="kb-card" @click="goToDetail(item)">
          <div class="kb-card-header">
            <div class="kb-icon" :class="item.tone">{{ item.icon }}</div>
            <div class="kb-card-meta">
              <div class="kb-card-name">{{ item.name }}</div>
              <span class="mode-badge">{{ modeLabel(item.mode) }}</span>
            </div>
          </div>
          <p class="kb-card-desc">{{ item.description || t('knowledgebases.noDescription') }}</p>
          <div class="kb-card-stats">
            <div class="mini-stat"><span class="mini-val">{{ item.documents }}</span><span class="mini-label">{{ t('knowledgebases.documentLabel') }}</span></div>
            <div class="mini-stat"><span class="mini-val">{{ item.chunks }}</span><span class="mini-label">{{ t('knowledgebases.chunkLabel') }}</span></div>
          </div>
          <div class="kb-card-footer">
            <span class="kb-time">{{ item.updatedAt }}</span>
            <div class="kb-actions" @click.stop>
              <button class="action-link primary" @click="openEdit(item)">{{ $t('common.edit') }}</button>
              <n-popconfirm @positive-click="deleteKnowledgebase(item)">
                <template #trigger><button class="action-link danger">{{ $t('common.delete') }}</button></template>
                {{ t('knowledgebases.confirmDelete', { name: item.name }) }}
              </n-popconfirm>
            </div>
          </div>
        </div>
      </div>
      <div v-else-if="!loading" class="empty-state">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#d0d5dd" stroke-width="1.5"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>
        <p>{{ t('knowledgebases.empty') }}</p>
        <n-button type="primary" size="small" @click="openCreate">{{ t('knowledgebases.create') }}</n-button>
      </div>
    </n-spin>

    <!-- Create/Edit Modal -->
    <n-modal v-model:show="modal.visible.value" preset="card"
      :title="modal.isEdit.value ? t('knowledgebases.editTitle') : t('knowledgebases.createTitle')"
      style="width: 600px; max-width: 90vw;" :mask-closable="false">
      <div class="modal-form">
        <div class="form-field full">
          <label class="field-label">{{ t('knowledgebases.name') }} <span class="required">*</span></label>
          <n-input v-model:value="modal.form.name" :placeholder="t('knowledgebases.namePlaceholder')" />
        </div>
        <div class="form-field full">
          <label class="field-label">{{ t('knowledgebases.description') }}</label>
          <n-input v-model:value="modal.form.description" type="textarea" :rows="3" :placeholder="t('knowledgebases.descriptionPlaceholder')" />
        </div>
        <div class="form-field full">
          <label class="field-label">{{ t('knowledgebases.retrievalMode') }}</label>
          <n-radio-group v-model:value="modal.form.mode">
            <n-space>
              <n-radio v-for="opt in modeOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</n-radio>
            </n-space>
          </n-radio-group>
          <span class="field-hint">{{ modeOptions.find((option) => option.value === modal.form.mode)?.desc }}</span>
        </div>
        <div class="form-field">
          <label class="field-label">{{ t('knowledgebases.similarityThreshold') }}</label>
          <div class="slider-row"><n-slider v-model:value="modal.form.threshold" :min="0" :max="1" :step="0.01" /><span class="slider-val">{{ modal.form.threshold?.toFixed(2) }}</span></div>
        </div>
        <div class="form-field">
          <label class="field-label">{{ t('knowledgebases.resultCount') }}</label>
          <div class="slider-row"><n-slider v-model:value="modal.form.topK" :min="1" :max="20" :step="1" /><span class="slider-val">{{ t('knowledgebases.topKValue', { count: modal.form.topK }) }}</span></div>
        </div>
        <div class="form-field">
          <label class="field-label">{{ t('knowledgebases.chunkSize') }}</label>
          <div class="slider-row"><n-slider v-model:value="modal.form.chunkSize" :min="100" :max="2000" :step="50" /><span class="slider-val">{{ modal.form.chunkSize }}</span></div>
        </div>
        <div class="form-field">
          <label class="field-label">{{ t('knowledgebases.chunkOverlap') }}</label>
          <div class="slider-row"><n-slider v-model:value="modal.form.chunkOverlap" :min="50" :max="500" :step="10" /><span class="slider-val">{{ modal.form.chunkOverlap }}</span></div>
        </div>
        <div class="form-field full">
          <label class="field-label">{{ t('knowledgebases.rerankModel') }}</label>
          <n-select v-model:value="modal.form.rerankModelId" :options="rerankModelOptions" :placeholder="t('knowledgebases.disableRerank')" clearable />
        </div>
      </div>
      <template #action>
        <n-space justify="end">
          <n-button @click="modal.close()">{{ t('common.cancel') }}</n-button>
          <n-button type="primary" @click="saveKnowledgebase" :loading="saving">{{ t('common.save') }}</n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>
<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  NButton, NInput, NSelect, NSlider, NRadioGroup, NRadio,
  NSpace, NText, NSpin, NModal, NPopconfirm, useMessage,
} from 'naive-ui'
import PageHeader from '../components/PageHeader.vue'
import { knowledgebaseApi, modelsApi } from '../api'
import { useModalForm } from '../composables/useModalForm'

const router = useRouter()
const message = useMessage()
const { t } = useI18n()
const knowledgebases = ref([])
const rerankModels = ref([])
const loading = ref(false)
const saving = ref(false)
const modeOptions = computed(() => ([
  { value: 'hybrid', label: t('knowledgebases.modes.hybrid.label'), desc: t('knowledgebases.modes.hybrid.description') },
  { value: 'dense', label: t('knowledgebases.modes.dense.label'), desc: t('knowledgebases.modes.dense.description') },
  { value: 'keyword', label: t('knowledgebases.modes.keyword.label'), desc: t('knowledgebases.modes.keyword.description') },
]))

const totalDocuments = computed(() => knowledgebases.value.reduce((sum, item) => sum + item.documents, 0))
const totalChunks = computed(() => knowledgebases.value.reduce((sum, item) => sum + item.chunks, 0))
const rerankModelOptions = computed(() => [
  { label: t('knowledgebases.disableRerank'), value: '' },
  ...rerankModels.value.map(m => ({ label: m.id, value: m.id })),
])
const modeLabel = (mode) => modeOptions.value.find((option) => option.value === mode)?.label || mode

const modal = useModalForm(() => ({
  id: '', name: '', description: '', mode: 'hybrid',
  threshold: 0.3, topK: 8, chunkSize: 1200, chunkOverlap: 200,
  rerankModelId: '', retrieval_config: {},
}))

function openCreate() { modal.openCreate() }
function openEdit(item) {
  modal.openEdit({
    id: item.id, name: item.name, description: item.description || '',
    mode: item.mode, threshold: item.threshold === '-' ? 0.3 : Number(item.threshold ?? 0.3),
    topK: item.topK === '-' ? 8 : item.topK,
    chunkSize: item.chunk_size || 1200, chunkOverlap: item.chunk_overlap || 200,
    rerankModelId: item.rerank_model_id || '', retrieval_config: item.retrieval_config || {},
  })
}
function goToDetail(item) { router.push(`/knowledgebases/${item.id}`) }

async function saveKnowledgebase() {
  if (!modal.form.name?.trim()) { message.warning(t('knowledgebases.messages.fillNameFirst')); return }
  saving.value = true
  const payload = {
    name: modal.form.name, description: modal.form.description || '',
    chunk_size: Number(modal.form.chunkSize), chunk_overlap: Number(modal.form.chunkOverlap),
    rerank_model_id: modal.form.rerankModelId || '',
    retrieval_config: {
      ...(modal.form.retrieval_config || {}),
      mode: modal.form.mode, score_threshold: Number(modal.form.threshold),
      top_k: Number(modal.form.topK || 0) || undefined,
    },
  }
  try {
    if (modal.form.id) {
      await knowledgebaseApi.update(modal.form.id, payload)
      message.success(t('knowledgebases.messages.updateSuccess', { name: modal.form.name }))
    } else {
      await knowledgebaseApi.create(payload)
      message.success(t('knowledgebases.messages.createSuccess', { name: modal.form.name }))
    }
    modal.close(); await fetchKnowledgebases()
  } catch (e) { message.error(extractError(e, t('knowledgebases.messages.saveFailed'))) }
  finally { saving.value = false }
}

async function deleteKnowledgebase(item) {
  try {
    await knowledgebaseApi.delete(item.id)
    message.success(t('knowledgebases.messages.deleted', { name: item.name }))
    await fetchKnowledgebases()
  } catch (e) {
    message.error(extractError(e, t('knowledgebases.messages.deleteFailed')))
  }
}

function normalizeKnowledgebase(item) {
  const retrieval = item.retrieval_config || {}
  return {
    ...item, documents: item.document_count || 0, chunks: item.chunk_count || 0,
    mode: retrieval.mode || item.metadata?.mode || 'hybrid',
    threshold: retrieval.score_threshold ?? '-', topK: retrieval.top_k ?? '-',
    icon: item.is_default ? '📘' : '🧱', tone: item.is_default ? 'blue' : 'purple',
    updatedAt: formatRelative(item.updated_at),
  }
}

function formatRelative(value) {
  if (!value) return t('knowledgebases.relativeTime.justNowUpdated')
  const diffHours = Math.round((Date.now() - new Date(value).getTime()) / 3600000)
  if (diffHours <= 1) return t('knowledgebases.relativeTime.withinOneHour')
  if (diffHours < 24) return t('knowledgebases.relativeTime.hoursAgo', { count: diffHours })
  return t('knowledgebases.relativeTime.daysAgo', { count: Math.round(diffHours / 24) })
}

function extractError(error, fallback) {
  return error?.response?.data?.detail?.error || error?.response?.data?.detail || error?.message || fallback
}

async function fetchKnowledgebases() {
  loading.value = true
  try { const res = await knowledgebaseApi.list(); knowledgebases.value = (res.knowledgebases || []).map(normalizeKnowledgebase) }
  catch (e) { message.error(extractError(e, t('knowledgebases.messages.fetchListFailed'))) }
  finally { loading.value = false }
}

async function fetchModels() {
  try {
    const res = await modelsApi.list()
    rerankModels.value = (res.models || []).filter(m => m.model_type === 'rerank')
  } catch (e) {
    console.error('Failed to load rerank models:', e)
    message.error(t('knowledgebases.messages.fetchModelsFailed'))
  }
}

onMounted(() => Promise.all([fetchKnowledgebases(), fetchModels()]))
</script>
<style scoped>
/* Stats row */
.stat-row {
  display: flex; gap: 12px; margin-bottom: 20px;
}
.stat-card {
  flex: 1; padding: 16px 20px;
  background: #fff; border: 1px solid #eaecf0; border-radius: 12px;
}
.stat-value { font-size: 24px; font-weight: 700; color: var(--text-primary); }
.stat-label { font-size: 12px; color: #667085; margin-top: 2px; }

/* KB Grid */
.kb-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 16px;
}
.kb-card {
  background: #fff; border: 1px solid #eaecf0; border-radius: 14px;
  padding: 20px; cursor: pointer; transition: all 0.15s;
}
.kb-card:hover { border-color: #d0d5dd; box-shadow: 0 4px 12px rgba(0,0,0,0.06); transform: translateY(-1px); }
.kb-card-header { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.kb-icon {
  width: 40px; height: 40px; border-radius: 10px;
  display: flex; align-items: center; justify-content: center; font-size: 20px; flex-shrink: 0;
}
.kb-icon.blue { background: #eff6ff; }
.kb-icon.purple { background: #f5f3ff; }
.kb-icon.orange { background: #fff7ed; }
.kb-card-meta { min-width: 0; }
.kb-card-name { font-size: 15px; font-weight: 600; color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mode-badge {
  display: inline-block; font-size: 10px; padding: 1px 6px; border-radius: 4px;
  background: #f2f4f7; color: #667085; margin-top: 2px;
}
.kb-card-desc {
  font-size: 13px; color: #667085; line-height: 1.5; margin: 0 0 14px;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
  min-height: 40px;
}
.kb-card-stats { display: flex; gap: 8px; margin-bottom: 14px; }
.mini-stat {
  flex: 1; padding: 8px; border-radius: 8px; background: #f9fafb; text-align: center;
}
.mini-val { display: block; font-size: 18px; font-weight: 700; color: var(--text-primary); }
.mini-label { font-size: 11px; color: #98a2b3; }
.kb-card-footer {
  display: flex; align-items: center; justify-content: space-between;
  padding-top: 12px; border-top: 1px solid #f2f4f7;
}
.kb-time { font-size: 12px; color: #98a2b3; }
.kb-actions { display: flex; gap: 12px; }
.action-link {
  background: none; border: none; font-size: 12px; font-weight: 500;
  cursor: pointer; padding: 0; transition: opacity 0.12s;
}
.action-link:hover { opacity: 0.7; }
.action-link.primary { color: var(--primary); }
.action-link.danger { color: var(--error); }

/* Empty */
.empty-state {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  padding: 80px 0; color: #98a2b3; gap: 12px; font-size: 14px;
}

/* Modal form */
.modal-form { display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; }
.form-field { min-width: 0; }
.form-field.full { grid-column: 1 / -1; }
.field-label { display: block; font-size: 13px; font-weight: 500; color: #344054; margin-bottom: 6px; }
.field-hint { font-size: 12px; color: #98a2b3; margin-top: 4px; display: block; }
.required { color: var(--error); }
.slider-row { display: flex; align-items: center; gap: 12px; }
.slider-val { font-size: 12px; font-weight: 500; color: #667085; min-width: 48px; text-align: right; font-variant-numeric: tabular-nums; }

@media (max-width: 900px) {
  .stat-row { flex-direction: column; }
  .kb-grid { grid-template-columns: 1fr; }
  .modal-form { grid-template-columns: 1fr; }
  .kb-card-footer { flex-direction: column; align-items: flex-start; gap: 8px; }
}
@media (min-width: 901px) and (max-width: 1200px) {
  .kb-grid { grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); }
}
</style>
