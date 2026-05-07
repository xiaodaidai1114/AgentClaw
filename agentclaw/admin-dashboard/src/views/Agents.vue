<template>
  <div>
    <PageHeader :title="t('agents.title')" :show-refresh="false" />

    <n-spin :show="loading">
      <div class="agents-grid">
        <n-card
          v-for="agent in agents"
          :key="agent.id"
          hoverable
          @click="$router.push(`/workflows/${agent.id}/chat`)"
          style="cursor: pointer;"
        >
          <template #header>
            <n-space align="center" :size="12">
              <div class="agent-avatar" :style="{ background: getAvatarColor(agent.id) }">
                {{ agent.name?.charAt(0)?.toUpperCase() || '?' }}
              </div>
              <div>
                <div style="font-weight: 500;">{{ agent.name }}</div>
                <n-text depth="3" style="font-size: 12px;">v{{ agent.version }}</n-text>
              </div>
            </n-space>
          </template>
          <n-ellipsis :line-clamp="3" style="font-size: 13px; color: var(--text-secondary); min-height: 60px;">
            {{ agent.description || t('workflows.noDescription') }}
          </n-ellipsis>
          <n-divider style="margin: 12px 0;" />
          <n-space justify="space-between" align="center">
            <n-tag size="small" :bordered="false" type="info">{{ t('agents.nodeCount', { count: agent.node_count || 0 }) }}</n-tag>
            <n-space :size="12" style="font-size: 12px; color: var(--text-secondary);">
              <span>👁 {{ agent.view_count || 0 }}</span>
              <span>👍 {{ agent.like_count || 0 }}</span>
            </n-space>
          </n-space>
        </n-card>
      </div>

      <n-empty v-if="!loading && agents.length === 0" :description="t('agents.empty')" style="padding: 60px;">
        <template #extra>
          <n-button type="primary" @click="$router.push('/workflows')">{{ t('agents.openWorkflowManagement') }}</n-button>
        </template>
      </n-empty>
    </n-spin>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { NCard, NSpace, NText, NTag, NDivider, NEllipsis, NEmpty, NButton, NSpin } from 'naive-ui'
import PageHeader from '../components/PageHeader.vue'
import { workflowsApi } from '../api'

const { t } = useI18n()
const agents = ref([])
const loading = ref(true)

const avatarColors = [
  'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
  'linear-gradient(135deg, #f093fb 0%, #f5576c 100%)',
  'linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)',
  'linear-gradient(135deg, #43e97b 0%, #38f9d7 100%)',
  'linear-gradient(135deg, #fa709a 0%, #fee140 100%)',
  'linear-gradient(135deg, #a8edea 0%, #fed6e3 100%)',
  'linear-gradient(135deg, #d299c2 0%, #fef9d7 100%)',
  'linear-gradient(135deg, #89f7fe 0%, #66a6ff 100%)',
]

function getAvatarColor(id) {
  const hash = id.split('').reduce((acc, c) => acc + c.charCodeAt(0), 0)
  return avatarColors[hash % avatarColors.length]
}

async function loadAgents() {
  loading.value = true
  try {
    const res = await workflowsApi.list()
    agents.value = (res.workflows || []).filter(wf => wf.id !== '__builtin__')
  } catch (e) {
    console.error('加载智能体列表失败:', e)
  } finally {
    loading.value = false
  }
}

onMounted(loadAgents)
</script>

<style scoped>
.agents-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
}

.agent-avatar {
  width: 40px;
  height: 40px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  font-weight: 600;
  color: #fff;
  flex-shrink: 0;
}
</style>
