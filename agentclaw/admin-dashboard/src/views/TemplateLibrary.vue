<template>
  <div>
    <PageHeader :title="t('templateLibrary.title')">
      <template #actions>
        <n-button size="small" @click="fetchData">{{ t('common.refresh') }}</n-button>
      </template>
    </PageHeader>

    <n-space justify="space-between" align="center" class="template-toolbar">
      <n-space :size="12" align="center" class="toolbar-left">
        <n-input v-model:value="searchQuery" :placeholder="t('templateLibrary.searchPlaceholder')" clearable style="width: 300px;">
          <template #prefix>🔍</template>
        </n-input>
        <n-select
          v-model:value="categoryFilter"
          :options="categoryOptions"
          style="width: 160px;"
          size="small"
        />
      </n-space>
      <div class="toolbar-count">{{ t('common.totalItems', { count: filteredApps.length }) }}</div>
    </n-space>

    <n-spin :show="loading">
      <div v-if="filteredApps.length" class="template-grid">
        <n-card
          v-for="app in filteredApps"
          :key="app.id"
          class="template-card"
          :bordered="true"
        >
          <template #header>
            <div class="card-header">
              <div class="template-avatar">{{ getAvatarText(app) }}</div>
              <div class="template-heading">
                <div class="template-title-row">
                  <span class="template-title">{{ app.name || app.id }}</span>
                  <n-tag v-if="app.imported" size="small" type="success" :bordered="false">
                    {{ app.registered ? t('templateLibrary.imported') : t('templateLibrary.importedNeedsReload') }}
                  </n-tag>
                </div>
                <div class="template-id">{{ app.workflow_id || app.id }}</div>
              </div>
            </div>
          </template>

          <div class="template-description">{{ app.description || t('workflows.noDescription') }}</div>

          <div class="tag-row">
            <n-tag v-for="tag in app.tags" :key="tag" size="small" :bordered="false">{{ tag }}</n-tag>
          </div>

          <div v-if="app.recommended_input" class="recommended-input">
            <div class="recommend-label">{{ t('templateLibrary.recommendedInput') }}</div>
            <div class="recommend-text">{{ app.recommended_input }}</div>
          </div>

          <div class="card-actions">
            <n-button
              v-if="app.registered"
              type="primary"
              size="small"
              @click="openWorkflow(app)"
            >
              {{ t('templateLibrary.openAgent') }}
            </n-button>
            <n-button
              v-else
              type="primary"
              size="small"
              :loading="importingId === app.id"
              @click="importTemplate(app, false)"
            >
              {{ app.imported ? t('templateLibrary.importedNeedsReload') : t('templateLibrary.importAgent') }}
            </n-button>
            <n-button
              v-if="!app.registered"
              size="small"
              :loading="importingId === app.id"
              @click="importTemplate(app, true)"
            >
              {{ t('templateLibrary.importAndOpen') }}
            </n-button>
          </div>
        </n-card>
      </div>
      <n-empty v-else :description="loading ? t('common.loading') : t('templateLibrary.empty')" />
    </n-spin>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  NButton,
  NCard,
  NEmpty,
  NInput,
  NSelect,
  NSpace,
  NSpin,
  NTag,
  useMessage,
} from 'naive-ui'
import PageHeader from '../components/PageHeader.vue'
import { templateLibraryApi, workflowsApi } from '../api'
import { withReadinessRetry } from '../utils/eventualConsistency'

const router = useRouter()
const { t } = useI18n()
const message = useMessage()

const apps = ref([])
const loading = ref(false)
const importingId = ref('')
const searchQuery = ref('')
const categoryFilter = ref('all')

const categoryOptions = computed(() => {
  const categories = [...new Set(apps.value.map(app => app.category).filter(Boolean))]
  return [
    { label: t('templateLibrary.allCategories'), value: 'all' },
    ...categories.map(category => ({ label: category, value: category })),
  ]
})

const filteredApps = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  return apps.value.filter(app => {
    if (categoryFilter.value !== 'all' && app.category !== categoryFilter.value) return false
    if (!query) return true
    const text = [
      app.id,
      app.name,
      app.description,
      app.workflow_id,
      ...(app.tags || []),
    ].join(' ').toLowerCase()
    return text.includes(query)
  })
})

async function fetchData() {
  loading.value = true
  try {
    const res = await templateLibraryApi.list()
    apps.value = res.apps || []
  } catch (error) {
    message.error(error.response?.data?.error || t('templateLibrary.loadFailed'))
  } finally {
    loading.value = false
  }
}

function updateAppImportState(result) {
  apps.value = apps.value.map(app => {
    if (app.id !== result.app_id) return app
    return {
      ...app,
      imported: result.imported,
      registered: result.registered,
      target_dir: result.target_dir,
      workflow_file: result.workflow_file,
    }
  })
}

async function importTemplate(app, openAfterImport) {
  importingId.value = app.id
  try {
    const result = await templateLibraryApi.importApp(app.id, { overwrite: false })
    updateAppImportState(result)
    message.success(result.message || t('templateLibrary.importSuccess'))
    if (openAfterImport && result.registered) {
      await waitForImportedWorkflow(result.workflow_id)
      openWorkflow({ ...app, workflow_id: result.workflow_id, registered: true })
    }
  } catch (error) {
    message.error(error.response?.data?.error || t('templateLibrary.importFailed'))
  } finally {
    importingId.value = ''
  }
}

async function waitForImportedWorkflow(workflowId) {
  await withReadinessRetry(() => workflowsApi.get(workflowId), {
    delays: [150, 300, 600, 1000],
  })
}

function openWorkflow(app) {
  const workflowId = app.workflow_id || app.id
  router.push({
    path: `/workflows/${workflowId}/chat`,
    query: app.recommended_input ? { seed_input: app.recommended_input } : {},
  })
}

function getAvatarText(app) {
  const text = app.name || app.id || '?'
  return text.charAt(0).toUpperCase()
}

onMounted(fetchData)
</script>

<style scoped>
.template-toolbar {
  margin-bottom: 16px;
}

.toolbar-left {
  min-width: 0;
}

.toolbar-count {
  color: var(--text-secondary);
  font-size: 13px;
}

.template-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 16px;
}

.template-card {
  border-radius: 8px;
  background: #fff;
}

.card-header {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.template-avatar {
  width: 40px;
  height: 40px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  font-weight: 700;
  color: #18181b;
  background: #f4f4f5;
  border: 1px solid #e4e4e7;
}

.template-heading {
  min-width: 0;
}

.template-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.template-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
}

.template-id {
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-secondary);
  font-family: monospace;
}

.template-description {
  min-height: 42px;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.55;
}

.tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 14px;
}

.recommended-input {
  margin-top: 14px;
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid #eef2f7;
  background: #fafafa;
}

.recommend-label {
  margin-bottom: 4px;
  color: var(--text-secondary);
  font-size: 12px;
}

.recommend-text {
  color: var(--text-primary);
  font-size: 13px;
  line-height: 1.5;
}

.card-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
}

@media (max-width: 640px) {
  .template-toolbar {
    align-items: stretch !important;
  }

  .toolbar-left,
  .toolbar-left :deep(.n-input),
  .toolbar-left :deep(.n-select) {
    width: 100% !important;
  }

  .template-grid {
    grid-template-columns: 1fr;
  }

  .card-actions {
    justify-content: stretch;
  }

  .card-actions :deep(.n-button) {
    flex: 1;
  }
}
</style>
