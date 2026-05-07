<template>
  <div>
    <PageHeader :title="t('workflows.title')" @refresh="fetchData" />

    <!-- 工具栏 -->
    <n-space justify="space-between" align="center" style="margin-bottom: 16px;">
      <n-input v-model:value="searchQuery" :placeholder="t('workflows.searchPlaceholder')" clearable style="width: 300px;">
        <template #prefix>🔍</template>
      </n-input>
      <n-space :size="12">
        <n-select
          v-model:value="sortBy"
          :options="sortOptions"
          style="width: 160px;"
          size="small"
        />
        <n-button-group size="small">
          <n-button :type="viewMode === 'grid' ? 'primary' : 'default'" @click="viewMode = 'grid'">{{ t('workflows.grid') }}</n-button>
          <n-button :type="viewMode === 'table' ? 'primary' : 'default'" @click="viewMode = 'table'">{{ t('workflows.table') }}</n-button>
        </n-button-group>
      </n-space>
    </n-space>

    <!-- 卡片视图 -->
    <div v-if="viewMode === 'grid'" class="workflows-grid">
      <n-card
        v-for="wf in filteredWorkflows"
        :key="wf.id"
        hoverable
        :class="['agent-card', { 'warning-card': wf.stats_24h?.execution_count > 0 && wf.stats_24h?.success_rate < 90 }]"
        @click="$router.push(`/workflows/${wf.id}/chat`)"
        style="cursor: pointer;"
      >
        <template #header>
          <div class="card-top">
            <div class="card-main">
              <div class="agent-avatar">
                {{ getAvatarText(wf) }}
              </div>
              <div class="agent-copy">
                <div class="agent-title-row">
                  <span class="agent-title">
                    {{ wf.name || wf.id }}
                  </span>
                  <n-tag size="small" :bordered="false">{{ wf.version }}</n-tag>
                </div>
                <div class="agent-subtitle">{{ wf.id }}</div>
              </div>
            </div>
            <n-tag v-if="wf.stats_24h?.running_count > 0" :type="getRuntimeTagType(wf)" size="small" round>
              {{ getRuntimeLabel(wf) }}
            </n-tag>
          </div>
        </template>
        <div class="card-desc">{{ wf.description || t('workflows.noDescription') }}</div>
        <div class="card-stats">
          <div class="stat-item">
            <div class="stat-label">{{ t('workflows.token24h') }}</div>
            <div class="stat-value">{{ formatTokens(wf.stats_24h?.total_tokens || 0) }}</div>
          </div>
          <div class="stat-item">
            <div class="stat-label">{{ t('workflows.execution24h') }}</div>
            <div class="stat-value">{{ wf.stats_24h?.execution_count || 0 }}</div>
          </div>
          <div class="stat-item">
            <div class="stat-label">{{ t('workflows.successRate24h') }}</div>
            <div class="stat-value" :style="{ color: getSuccessRateColor(wf.stats_24h?.success_rate) }">
              {{ formatPercent(wf.stats_24h?.success_rate) }}
            </div>
          </div>
          <div class="stat-item">
            <div class="stat-label">{{ t('workflows.avgDuration24h') }}</div>
            <div class="stat-value">{{ formatDuration(wf.stats_24h?.avg_duration_ms) }}</div>
          </div>
        </div>
        <div class="card-actions">
          <span class="card-meta">{{ t('workflows.lastExecution24h') }} {{ formatLastExecution(wf.stats_24h?.last_execution_time) }}</span>
          <n-space :size="8" justify="end">
            <n-button size="small" @click.stop="router.push(`/workflows/${wf.id}`)">{{ t('common.detail') }}</n-button>
          </n-space>
        </div>
      </n-card>
    </div>

    <!-- 表格视图 -->
    <n-card v-else>
      <n-data-table :columns="columns" :data="filteredWorkflows" :bordered="false" size="small" />
    </n-card>
  </div>
</template>

<script setup>
import { h, ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  NCard, NSpace, NInput, NSelect, NButton, NButtonGroup, NTag,
  NDataTable
} from 'naive-ui'
import PageHeader from '../components/PageHeader.vue'
import { workflowsApi } from '../api'
import { formatDuration, formatTokens } from '../composables/useFormatters'

const router = useRouter()
const { t } = useI18n()
const workflows = ref([])
const searchQuery = ref('')
const sortBy = ref('execution')
const viewMode = ref('grid')

const sortOptions = computed(() => [
  { label: t('workflows.sortExecution'), value: 'execution' },
  { label: t('workflows.sortName'), value: 'name' },
  { label: t('workflows.sortSuccessRate'), value: 'success_rate' },
])

const filteredWorkflows = computed(() => {
  let result = workflows.value.filter(wf => wf.id !== '__builtin__')
  if (searchQuery.value) {
    const q = searchQuery.value.toLowerCase()
    result = result.filter(wf => wf.id.toLowerCase().includes(q) || (wf.name || '').toLowerCase().includes(q))
  }
  result.sort((a, b) => {
    if (sortBy.value === 'name') return (a.name || a.id).localeCompare(b.name || b.id)
    if (sortBy.value === 'success_rate') return (b.stats_24h?.success_rate ?? -1) - (a.stats_24h?.success_rate ?? -1)
    return (b.stats_24h?.execution_count || 0) - (a.stats_24h?.execution_count || 0)
  })
  return result
})

const columns = computed(() => [
  { title: t('workflows.title'), key: 'id', render: (row) => h('div', { style: 'display: flex; gap: 12px; align-items: center;' }, [
    h('div', { class: 'agent-avatar', style: { width: '36px', height: '36px', fontSize: '16px' } }, getAvatarText(row)),
    h('div', null, [
      h('div', { style: 'font-weight: 500' }, row.name || row.id),
      h('div', { style: 'font-size: 12px; color: var(--text-secondary)' }, row.id),
    ]),
  ])},
  { title: t('dashboard.version'), key: 'version', width: 80, render: (row) => h(NTag, { size: 'small', bordered: false }, { default: () => row.version }) },
  { title: t('dashboard.status'), key: 'status', width: 80, render: (row) => row.stats_24h?.running_count > 0
    ? h(NTag, { type: 'info', size: 'small', round: true }, { default: () => t('workflows.running') })
    : t('workflows.none') },
  { title: t('workflows.token24h'), key: 'tokens', width: 110, render: (row) => formatTokens(row.stats_24h?.total_tokens || 0) },
  { title: t('workflows.execution24h'), key: 'exec', width: 100, render: (row) => row.stats_24h?.execution_count || 0 },
  { title: t('workflows.successRate24h'), key: 'rate', width: 90, render: (row) => h('span', {
    style: `color: ${getSuccessRateColor(row.stats_24h?.success_rate)}`
  }, formatPercent(row.stats_24h?.success_rate)) },
  { title: t('workflows.avgDuration24h'), key: 'dur', width: 110, render: (row) => formatDuration(row.stats_24h?.avg_duration_ms) },
  { title: t('workflows.lastExecution24h'), key: 'last', width: 110, render: (row) => formatLastExecution(row.stats_24h?.last_execution_time) },
  { title: t('dashboard.actions'), key: 'actions', width: 120, render: (row) => h(NSpace, { size: 8 }, () => [
    h(NButton, { text: true, size: 'small', onClick: () => router.push(`/workflows/${row.id}/chat`) }, { default: () => t('common.experience') }),
    h(NButton, { text: true, type: 'primary', size: 'small', onClick: () => router.push(`/workflows/${row.id}`) }, { default: () => t('common.detail') }),
  ]) },
])

async function fetchData() {
  try {
    const res = await workflowsApi.list()
    workflows.value = res.workflows
  } catch (e) {
    console.error('Failed to fetch workflows:', e)
  }
}

function formatPercent(val) {
  if (val == null) return '-'
  return `${Number(val).toFixed(1)}%`
}

function formatLastExecution(val) {
  if (!val) return t('workflows.none')
  const diff = Date.now() - new Date(val).getTime()
  if (diff < 60000) return t('workflows.justNow')
  if (diff < 3600000) return t('workflows.minutesAgo', { count: Math.floor(diff / 60000) })
  if (diff < 86400000) return t('workflows.hoursAgo', { count: Math.floor(diff / 3600000) })
  return t('workflows.daysAgo', { count: Math.floor(diff / 86400000) })
}

function getSuccessRateColor(rate) {
  if (rate == null) return 'var(--text-secondary)'
  if (rate >= 95) return 'var(--success)'
  if (rate >= 90) return 'var(--warning)'
  return 'var(--error)'
}

function getRuntimeLabel(workflow) {
  return workflow.stats_24h?.running_count > 0 ? t('workflows.running') : t('workflows.idle')
}

function getRuntimeTagType(workflow) {
  return workflow.stats_24h?.running_count > 0 ? 'success' : 'default'
}

function getAvatarText(workflow) {
  const text = workflow.name || workflow.id || '?'
  return text.charAt(0).toUpperCase()
}

onMounted(fetchData)
</script>

<style scoped>
.workflows-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 20px;
}

.agent-card {
  border-radius: 12px;
  border: 1px solid var(--border);
  background: #fff;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.agent-card:hover {
  border-color: #d4d4d8;
  box-shadow: 0 6px 18px rgba(15, 23, 42, 0.06);
}

.warning-card {
  border-color: rgba(245, 158, 11, 0.45);
}

.card-top {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

.card-main {
  display: flex;
  gap: 12px;
  min-width: 0;
}

.agent-avatar {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  font-weight: 700;
  color: #18181b;
  background: #f4f4f5;
  border: 1px solid #e4e4e7;
  flex-shrink: 0;
}

.agent-copy {
  min-width: 0;
}

.agent-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.agent-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
}

.agent-subtitle {
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-secondary);
  font-family: monospace;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.card-desc {
  margin-top: 4px;
  font-size: 13px;
  line-height: 1.5;
  color: var(--text-secondary);
  min-height: 38px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-stats {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-top: 14px;
}

.stat-item {
  padding: 10px 12px;
  border-radius: 10px;
  background: #fafafa;
  border: 1px solid #f1f5f9;
}

.stat-label {
  font-size: 12px;
  color: var(--text-secondary);
}

.stat-value {
  margin-top: 4px;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}

.card-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid #f4f4f5;
}

.card-meta {
  font-size: 12px;
  color: var(--text-secondary);
}

@media (max-width: 900px) {
  .workflows-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .card-stats,
  .card-actions {
    grid-template-columns: 1fr;
  }

  .card-actions {
    display: grid;
  }
}
</style>
