<template>
  <div class="public-agent-page">
    <AgentChat :public-mode="true" :workflow-id="workflowId" :share-token="shareToken" />
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AgentChat from './AgentChat.vue'

const route = useRoute()
const router = useRouter()
const workflowId = computed(() => route.params.id)
const shareTokenRef = ref(String(route.query.share_token || route.query.token || ''))
const shareToken = computed(() => shareTokenRef.value)

watch(
  () => [route.query.share_token, route.query.token],
  ([shareTokenQuery, tokenQuery]) => {
    const nextToken = String(shareTokenQuery || tokenQuery || '')
    if (nextToken) shareTokenRef.value = nextToken
    if (shareTokenQuery || tokenQuery) {
      const query = { ...route.query }
      delete query.share_token
      delete query.token
      router.replace({ query })
    }
  },
  { immediate: true }
)
</script>

<style scoped>
.public-agent-page {
  min-height: 100vh;
  min-height: 100dvh;
  height: 100vh;
  height: 100dvh;
  overflow: hidden;
  background: #f8fafc;
}

@media (max-width: 768px) {
  .public-agent-page {
    padding: 0;
  }
}
</style>
