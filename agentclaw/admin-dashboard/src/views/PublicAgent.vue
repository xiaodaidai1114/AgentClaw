<template>
  <div class="public-agent-page">
    <AgentChat
      :public-mode="true"
      :workflow-id="workflowId"
      :share-token="shareToken"
      :public-room-id="publicRoomId"
      :public-room-token="publicRoomToken"
    />
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
const publicRoomId = computed(() => String(route.query.room_id || ''))
const roomTokenRef = ref(String(route.query.room_token || ''))
const publicRoomToken = computed(() => roomTokenRef.value)

function roomTokenStorageKey(roomId) {
  return `agentclaw.publicRoom.${roomId}.token`
}

function shareTokenStorageKey(workflowId) {
  return `agentclaw.publicAgent.${workflowId}.shareToken`
}

watch(
  () => [route.params.id, route.query.share_token, route.query.token, route.query.room_id, route.query.room_token],
  ([workflowIdValue, shareTokenQuery, tokenQuery, roomIdQuery, roomTokenQuery]) => {
    const currentWorkflowId = String(workflowIdValue || '')
    const nextToken = String(shareTokenQuery || tokenQuery || '')
    if (nextToken) {
      shareTokenRef.value = nextToken
      if (currentWorkflowId) sessionStorage.setItem(shareTokenStorageKey(currentWorkflowId), nextToken)
    } else if (currentWorkflowId && !shareTokenRef.value) {
      shareTokenRef.value = sessionStorage.getItem(shareTokenStorageKey(currentWorkflowId)) || ''
    }
    const nextRoomId = String(roomIdQuery || '')
    const nextRoomToken = String(roomTokenQuery || '')
    if (nextRoomToken) {
      roomTokenRef.value = nextRoomToken
      if (nextRoomId) sessionStorage.setItem(roomTokenStorageKey(nextRoomId), nextRoomToken)
    } else if (nextRoomId && !roomTokenRef.value) {
      roomTokenRef.value = sessionStorage.getItem(roomTokenStorageKey(nextRoomId)) || ''
    }
    if (shareTokenQuery || tokenQuery || roomTokenQuery) {
      const query = { ...route.query }
      delete query.share_token
      delete query.token
      delete query.room_token
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
