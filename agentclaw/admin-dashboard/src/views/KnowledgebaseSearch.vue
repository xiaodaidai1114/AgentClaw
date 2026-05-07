<template>
  <div>
    <!-- Header -->
    <n-space justify="space-between" align="center" style="margin-bottom: 20px;">
      <n-space align="center" :size="12">
        <n-button text @click="router.push(`/knowledgebases/${route.params.id}`)">
          <template #icon><span style="font-size: 16px;">&larr;</span></template>
        </n-button>
        <n-h2 style="margin: 0;">{{ t('knowledgebaseSearch.pageTitle', { name: knowledgebase.name }) }}</n-h2>
      </n-space>
      <n-statistic :label="t('knowledgebaseSearch.currentResults')" :value="searchResults.length" />
    </n-space>

    <!-- Main layout -->
    <div class="search-layout">
      <!-- Config sidebar -->
      <n-card :title="t('knowledgebaseSearch.searchConfig')" size="small">
        <template #header-extra>
          <n-tag size="tiny" :bordered="false">{{ t('knowledgebaseSearch.boundKnowledgebase') }}</n-tag>
        </template>
        <div style="display: flex; flex-direction: column; gap: 12px;">
          <n-descriptions :column="1" label-placement="left" size="small" bordered>
            <n-descriptions-item :label="t('knowledgebaseSearch.mode')">{{ knowledgebase.mode }}</n-descriptions-item>
            <n-descriptions-item :label="t('knowledgebaseSearch.threshold')">{{ knowledgebase.threshold }}</n-descriptions-item>
            <n-descriptions-item label="Top K">{{ knowledgebase.topK }}</n-descriptions-item>
            <n-descriptions-item label="Embedding">{{ knowledgebase.embedding }}</n-descriptions-item>
            <n-descriptions-item label="Rerank">{{ knowledgebase.rerank }}</n-descriptions-item>
          </n-descriptions>
        </div>
      </n-card>

      <!-- Search panel -->
      <n-card :title="t('knowledgebaseSearch.searchWorkbench')" size="small">
        <n-space style="margin-bottom: 12px;">
          <n-input
            v-model:value="searchQuery"
            :placeholder="t('knowledgebaseSearch.queryPlaceholder')"
            clearable
            style="flex: 1; min-width: 300px;"
          />
          <n-button type="primary" :loading="isSearching" @click="runSearch">{{ t('knowledgebaseSearch.runSearch') }}</n-button>
        </n-space>

        <n-space justify="space-between" style="margin-bottom: 12px;">
          <n-text depth="3">{{ t('knowledgebaseSearch.pipelineSummary', { count: searchResults.length }) }}</n-text>
          <n-text depth="3">{{ t('knowledgebaseSearch.currentKnowledgebase', { name: knowledgebase.name }) }}</n-text>
        </n-space>

        <div v-if="searchResults.length" style="display: flex; flex-direction: column; gap: 12px;">
          <n-card v-for="result in highlightedResults" :key="result.id" size="small">
            <template #header>
              <n-space justify="space-between" align="center">
                <n-text strong>{{ result.title }}</n-text>
                <n-tag :type="scoreType(result.scoreValue)" size="small">{{ result.score }}</n-tag>
              </n-space>
            </template>
            <div v-html="result.previewHtml" style="font-size: 13px; line-height: 1.6; color: #555;" />
            <n-space style="margin-top: 10px;" :size="12">
              <n-text depth="3" style="font-size: 12px;">Dense {{ result.dense }}</n-text>
              <n-text depth="3" style="font-size: 12px;">BM25 {{ result.bm25 }}</n-text>
              <n-text depth="3" style="font-size: 12px;">{{ result.source }}</n-text>
            </n-space>
            <template #action>
              <n-button size="tiny" @click="copyResult(result.preview)">{{ t('knowledgebaseSearch.copyContent') }}</n-button>
            </template>
          </n-card>
        </div>
        <n-empty v-else :description="t('knowledgebaseSearch.emptyHint')" style="padding: 60px 0;" />
      </n-card>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import {
  NSpace, NH2, NButton, NCard, NInput, NText, NTag,
  NStatistic, NDescriptions, NDescriptionsItem, NEmpty, useMessage,
} from 'naive-ui'
import { knowledgebaseApi } from '../api'
import { highlightTextSafe } from '../utils/sanitize'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const { t } = useI18n()

const searchQuery = ref('')
const searchResults = ref([])
const isSearching = ref(false)
const knowledgebase = ref({ name: t('knowledgebaseSearch.defaultKnowledgebaseName'), mode: '-', threshold: '-', topK: '-', embedding: '-', rerank: '-' })

const highlightedResults = computed(() => {
  const terms = searchQuery.value.split(/\s+/).map(t => t.trim()).filter(Boolean)
  return searchResults.value.map(item => ({
    ...item,
    previewHtml: highlightText(item.preview, terms),
  }))
})

function highlightText(text, terms) {
  return highlightTextSafe(text, terms)
}

function scoreType(score) {
  if (score >= 0.8) return 'success'
  if (score >= 0.5) return 'info'
  return 'warning'
}

async function copyResult(text) {
  try {
    if (navigator?.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
    } else {
      const ta = document.createElement('textarea')
      ta.value = text
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
    }
    message.success(t('knowledgebaseSearch.copied'))
  } catch {
    message.info(text)
  }
}

async function fetchKnowledgebase() {
  try {
    const res = await knowledgebaseApi.get(route.params.id)
    const retrieval = res.retrieval_config || {}
    knowledgebase.value = {
      name: res.name || t('knowledgebaseSearch.defaultKnowledgebaseName'),
      mode: retrieval.mode || 'hybrid',
      threshold: retrieval.score_threshold ?? 0.3,
      topK: retrieval.top_k ?? 8,
      embedding: res.embedding_model_id || '-',
      rerank: res.rerank_model_id || '-',
    }
  } catch (e) {
    console.error('Failed to fetch knowledgebase:', e)
  }
}

async function runSearch() {
  if (!searchQuery.value.trim()) {
    message.warning(t('knowledgebaseSearch.enterQuery'))
    return
  }
  isSearching.value = true
  try {
    const retrieval = knowledgebase.value
    const params = {
      query: searchQuery.value,
      top_k: Number(retrieval.topK || 8),
      mode: retrieval.mode || 'hybrid',
      score_threshold: Number(retrieval.threshold ?? 0.3),
    }
    const response = await knowledgebaseApi.search(route.params.id, params)
    searchResults.value = (response.hits || []).map(item => ({
      id: item.chunk_id,
      title: item.document_name || t('knowledgebaseSearch.unknownDocument'),
      score: Number(item.score || 0).toFixed(2),
      scoreValue: Number(item.score || 0),
      dense: item.dense_score ? Number(item.dense_score).toFixed(2) : '-',
      bm25: item.keyword_score ? Number(item.keyword_score).toFixed(2) : '-',
      source: `Chunk-${item.chunk_index}`,
      preview: item.content,
    }))
    message.success(t('knowledgebaseSearch.searchCompleted', { count: searchResults.value.length }))
  } catch (error) {
    message.error(error?.response?.data?.detail || t('knowledgebaseSearch.searchFailed'))
  } finally {
    isSearching.value = false
  }
}

onMounted(fetchKnowledgebase)
</script>

<style scoped>
.search-layout {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  gap: 16px;
}

:deep(mark.kb-search-highlight) {
  background: #fff3bf;
  color: #614700;
  border-radius: 4px;
  padding: 0 3px;
}

@media (max-width: 900px) {
  .search-layout {
    grid-template-columns: 1fr;
    min-height: auto;
  }
}
</style>
