<template>
  <div class="public-agent-page">
    <AgentChat :public-mode="true" :workflow-id="workflowId" :share-token="shareToken" />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import AgentChat from './AgentChat.vue'

const route = useRoute()
const workflowId = computed(() => route.params.id)
const shareToken = computed(() => String(route.query.share_token || route.query.token || ''))
</script>

<style scoped>
.public-agent-page {
  min-height: 100vh;
  background: #f8fafc;
}

@media (max-width: 768px) {
  .public-agent-page {
    padding: 0;
  }
}
</style>
