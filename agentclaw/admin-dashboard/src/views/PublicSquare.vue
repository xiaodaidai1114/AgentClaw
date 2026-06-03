<template>
  <main class="public-square">
    <header class="public-square-header">
      <div>
        <div class="brand">AgentClaw</div>
        <h1>{{ t('publicSquare.title') }}</h1>
      </div>
      <button class="refresh-button" type="button" @click="fetchWorkflows">
        {{ t('common.refresh') }}
      </button>
    </header>

    <div v-if="loading" class="state-box">{{ t('common.loading') }}</div>
    <div v-else-if="loadError" class="state-box error">{{ loadError }}</div>
    <div v-else-if="!workflows.length" class="state-box">{{ t('publicSquare.empty') }}</div>
    <section v-else class="public-square-grid">
      <article
        v-for="workflow in workflows"
        :key="workflow.id"
        class="agent-card"
        @click="openWorkflow(workflow)"
      >
        <div class="agent-card-top">
          <div class="agent-avatar">{{ avatarText(workflow) }}</div>
          <div class="agent-heading">
            <h2>{{ workflow.name || workflow.id }}</h2>
            <p>{{ workflow.id }}</p>
          </div>
        </div>
        <p class="agent-description">{{ workflow.description || t('workflows.noDescription') }}</p>
        <div v-if="workflow.recommended_input" class="recommended-input">
          <span>{{ t('publicSquare.recommendedInput') }}</span>
          <p>{{ workflow.recommended_input }}</p>
        </div>
        <div class="agent-footer">
          <div class="capabilities">
            <span v-if="workflow.chat_audio?.speech_input_enabled">{{ t('publicSquare.speechInput') }}</span>
            <span v-if="workflow.chat_audio?.tts_enabled">{{ t('publicSquare.tts') }}</span>
          </div>
          <button class="open-button" type="button" @click.stop="openWorkflow(workflow)">
            {{ t('publicSquare.open') }}
          </button>
        </div>
      </article>
    </section>
  </main>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { publicSquareApi } from '../api'

const router = useRouter()
const { t } = useI18n()

const workflows = ref([])
const loading = ref(false)
const loadError = ref('')

async function fetchWorkflows() {
  loading.value = true
  loadError.value = ''
  try {
    const res = await publicSquareApi.list()
    workflows.value = res.workflows || []
  } catch (error) {
    loadError.value = error.response?.data?.error || t('publicSquare.loadFailed')
  } finally {
    loading.value = false
  }
}

function openWorkflow(workflow) {
  router.push({
    name: 'PublicAgent',
    params: { id: workflow.id },
    query: { share_token: workflow.share_token },
  })
}

function avatarText(workflow) {
  return String(workflow.name || workflow.id || '?').trim().charAt(0).toUpperCase() || '?'
}

onMounted(fetchWorkflows)
</script>

<style scoped>
.public-square {
  min-height: 100vh;
  min-height: 100dvh;
  background: #f6f7f9;
  color: #18181b;
  padding: 24px;
}

.public-square-header {
  max-width: 1180px;
  margin: 0 auto 24px;
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
}

.brand {
  font-size: 13px;
  font-weight: 700;
  color: #2563eb;
  margin-bottom: 6px;
}

.public-square h1 {
  margin: 0;
  font-size: 28px;
  line-height: 1.2;
  letter-spacing: 0;
}

.refresh-button,
.open-button {
  border: 1px solid #d7dce3;
  background: #fff;
  color: #18181b;
  border-radius: 8px;
  height: 36px;
  padding: 0 14px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.open-button {
  background: #2563eb;
  border-color: #2563eb;
  color: #fff;
}

.public-square-grid {
  max-width: 1180px;
  margin: 0 auto;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
}

.agent-card {
  min-height: 250px;
  background: #fff;
  border: 1px solid #e1e5eb;
  border-radius: 8px;
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s, transform 0.15s;
}

.agent-card:hover {
  border-color: #b9c4d3;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
  transform: translateY(-1px);
}

.agent-card-top {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.agent-avatar {
  width: 42px;
  height: 42px;
  border-radius: 8px;
  background: #eff6ff;
  color: #1d4ed8;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  font-weight: 800;
  flex: 0 0 auto;
}

.agent-heading {
  min-width: 0;
}

.agent-heading h2 {
  margin: 0;
  font-size: 16px;
  line-height: 1.3;
  letter-spacing: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-heading p {
  margin: 3px 0 0;
  color: #6b7280;
  font-size: 12px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-description {
  margin: 0;
  color: #4b5563;
  font-size: 13px;
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.recommended-input {
  background: #f8fafc;
  border: 1px solid #edf0f3;
  border-radius: 8px;
  padding: 10px;
}

.recommended-input span {
  display: block;
  color: #64748b;
  font-size: 11px;
  font-weight: 700;
  margin-bottom: 4px;
}

.recommended-input p {
  margin: 0;
  color: #334155;
  font-size: 12px;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.agent-footer {
  margin-top: auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.capabilities {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  min-width: 0;
}

.capabilities span {
  font-size: 11px;
  color: #475569;
  background: #eef2f7;
  border-radius: 999px;
  padding: 3px 8px;
}

.state-box {
  max-width: 1180px;
  margin: 0 auto;
  background: #fff;
  border: 1px solid #e1e5eb;
  border-radius: 8px;
  padding: 32px;
  text-align: center;
  color: #64748b;
}

.state-box.error {
  color: #b42318;
  background: #fff7f7;
  border-color: #ffd9d6;
}

@media (max-width: 720px) {
  .public-square {
    padding: 16px;
  }

  .public-square-header {
    align-items: stretch;
    flex-direction: column;
  }

  .public-square h1 {
    font-size: 22px;
  }

  .public-square-grid {
    grid-template-columns: 1fr;
  }

  .agent-card {
    min-height: 0;
  }
}
</style>
