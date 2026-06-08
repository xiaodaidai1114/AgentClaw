<template>
  <div class="public-rooms-page">
    <header class="public-rooms-header">
      <div>
        <h2>公开会话</h2>
        <p>管理公开多人会话、参与者和房间内聊天记录。</p>
      </div>
      <n-button type="primary" secondary :loading="loading" @click="fetchRooms">刷新</n-button>
    </header>

    <div class="public-rooms-toolbar">
      <n-input
        v-model:value="workflowFilter"
        clearable
        placeholder="按智能体 ID 筛选"
        @keyup.enter="resetAndFetch"
        @clear="resetAndFetch"
      />
      <n-select
        v-model:value="statusFilter"
        :options="statusOptions"
        placeholder="状态"
        @update:value="resetAndFetch"
      />
      <n-button secondary @click="resetAndFetch">搜索</n-button>
    </div>

    <n-data-table
      :columns="roomColumns"
      :data="rooms"
      :loading="loading"
      :bordered="false"
      size="small"
      scroll-x="max-content"
      :pagination="false"
      class="public-rooms-table"
    />
    <div class="public-rooms-pagination">
      <span>共 {{ total }} 个公开会话</span>
      <n-pagination
        v-model:page="page"
        :page-size="pageSize"
        :item-count="total"
        @update:page="fetchRooms"
      />
    </div>

    <n-drawer v-model:show="detailOpen" width="720">
      <n-drawer-content title="公开会话详情" closable>
        <n-spin :show="detailLoading">
          <div v-if="selectedDetail" class="public-room-detail">
            <n-descriptions label-placement="left" :column="1" size="small" bordered>
              <n-descriptions-item label="房间 ID">{{ selectedDetail.room.id }}</n-descriptions-item>
              <n-descriptions-item label="智能体">{{ selectedDetail.room.workflow_name || selectedDetail.room.workflow_id }}</n-descriptions-item>
              <n-descriptions-item label="状态">
                <n-tag :type="statusTagType(selectedDetail.room.lifecycle_status)" size="small">
                  {{ statusLabel(selectedDetail.room.lifecycle_status) }}
                </n-tag>
              </n-descriptions-item>
              <n-descriptions-item label="创建时间">{{ formatTime(selectedDetail.room.created_at) }}</n-descriptions-item>
              <n-descriptions-item label="过期时间">{{ formatTime(selectedDetail.room.expires_at) }}</n-descriptions-item>
            </n-descriptions>

            <section class="detail-section">
              <div class="detail-section-head">
                <h3>参与者</h3>
                <span>{{ selectedDetail.participants.length }} 人</span>
              </div>
              <n-data-table
                :columns="participantColumns"
                :data="selectedDetail.participants"
                :bordered="false"
                size="small"
                scroll-x="max-content"
                :pagination="false"
              />
            </section>

            <section class="detail-section">
              <div class="detail-section-head">
                <h3>智能体对话</h3>
                <span>{{ conversationMessages.length }} 条</span>
              </div>
              <n-empty v-if="conversationMessages.length === 0" description="暂无智能体对话" />
              <div v-else class="message-list">
                <article v-for="(message, index) in conversationMessages" :key="`conv-${index}`" class="message-row">
                  <strong>{{ message.role === 'user' ? (message.sender?.nickname || '玩家') : '智能体' }}</strong>
                  <p>{{ message.content }}</p>
                </article>
              </div>
            </section>

            <section class="detail-section">
              <div class="detail-section-head">
                <h3>玩家聊天</h3>
                <span>{{ selectedDetail.chat_messages.length }} 条</span>
              </div>
              <n-empty v-if="selectedDetail.chat_messages.length === 0" description="暂无玩家聊天" />
              <div v-else class="message-list">
                <article v-for="message in selectedDetail.chat_messages" :key="message.id" class="message-row">
                  <strong>{{ message.nickname || '玩家' }}</strong>
                  <time>{{ formatTime(message.created_at) }}</time>
                  <p>{{ message.content }}</p>
                </article>
              </div>
            </section>
          </div>
        </n-spin>
      </n-drawer-content>
    </n-drawer>
  </div>
</template>

<script setup>
import { computed, h, onMounted, ref } from 'vue'
import {
  NButton,
  NDataTable,
  NDescriptions,
  NDescriptionsItem,
  NDrawer,
  NDrawerContent,
  NEmpty,
  NInput,
  NPagination,
  NPopconfirm,
  NSelect,
  NSpin,
  NTag,
  useMessage,
} from 'naive-ui'
import { publicRoomsAdminApi } from '../api'

const message = useMessage()
const rooms = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 50
const loading = ref(false)
const detailLoading = ref(false)
const detailOpen = ref(false)
const selectedDetail = ref(null)
const workflowFilter = ref('')
const statusFilter = ref('')

const statusOptions = [
  { label: '全部状态', value: '' },
  { label: '公开中', value: 'active' },
  { label: '运行中', value: 'running' },
  { label: '已过期', value: 'expired' },
  { label: '已删除', value: 'deleted' },
]

const conversationMessages = computed(() => selectedDetail.value?.conversation?.messages || [])

function statusLabel(status) {
  return {
    active: '公开中',
    running: '运行中',
    expired: '已过期',
    deleted: '已删除',
  }[status] || '未知'
}

function statusTagType(status) {
  return {
    active: 'success',
    running: 'info',
    expired: 'warning',
    deleted: 'default',
  }[status] || 'default'
}

function formatTime(value) {
  const ms = Number(value || 0)
  if (!ms) return '-'
  return new Date(ms).toLocaleString()
}

async function fetchRooms() {
  loading.value = true
  try {
    const data = await publicRoomsAdminApi.list({
      page: page.value,
      page_size: pageSize,
      workflow_id: workflowFilter.value.trim(),
      status: statusFilter.value,
    })
    rooms.value = data.rooms || []
    total.value = data.total || 0
  } catch (error) {
    message.error(error.response?.data?.detail || error.message || '加载公开会话失败')
  } finally {
    loading.value = false
  }
}

function resetAndFetch() {
  page.value = 1
  fetchRooms()
}

async function openDetail(roomId) {
  detailOpen.value = true
  detailLoading.value = true
  try {
    selectedDetail.value = await publicRoomsAdminApi.get(roomId)
  } catch (error) {
    message.error(error.response?.data?.detail || error.message || '加载公开会话详情失败')
  } finally {
    detailLoading.value = false
  }
}

async function deleteRoom(roomId) {
  try {
    await publicRoomsAdminApi.delete(roomId)
    message.success('公开会话已删除')
    if (selectedDetail.value?.room?.id === roomId) detailOpen.value = false
    await fetchRooms()
  } catch (error) {
    message.error(error.response?.data?.detail || error.message || '删除公开会话失败')
  }
}

async function kickParticipant(ownerId) {
  const roomId = selectedDetail.value?.room?.id
  if (!roomId || !ownerId) return
  try {
    await publicRoomsAdminApi.kickParticipant(roomId, ownerId)
    message.success('已踢出用户')
    await openDetail(roomId)
    await fetchRooms()
  } catch (error) {
    message.error(error.response?.data?.detail || error.message || '踢出用户失败')
  }
}

const roomColumns = computed(() => [
  {
    title: '房间',
    key: 'id',
    minWidth: 220,
    render: (row) => h(NButton, { text: true, type: 'primary', onClick: () => openDetail(row.id) }, () => row.id),
  },
  { title: '智能体', key: 'workflow_name', minWidth: 160 },
  {
    title: '状态',
    key: 'lifecycle_status',
    width: 90,
    render: (row) => h(NTag, { type: statusTagType(row.lifecycle_status), size: 'small' }, () => statusLabel(row.lifecycle_status)),
  },
  { title: '参与者', key: 'participant_count', width: 80 },
  { title: '创建时间', key: 'created_at', minWidth: 160, render: (row) => formatTime(row.created_at) },
  { title: '过期时间', key: 'expires_at', minWidth: 160, render: (row) => formatTime(row.expires_at) },
  {
    title: '操作',
    key: 'actions',
    width: 150,
    fixed: 'right',
    render: (row) => h('div', { class: 'table-actions' }, [
      h(NButton, { text: true, type: 'primary', size: 'small', onClick: () => openDetail(row.id) }, () => '详情'),
      h(NPopconfirm, { onPositiveClick: () => deleteRoom(row.id) }, {
        trigger: () => h(NButton, { text: true, type: 'error', size: 'small' }, () => '删除'),
        default: () => '删除后公开链接将无法继续访问。',
      }),
    ]),
  },
])

const participantColumns = computed(() => [
  { title: '昵称', key: 'nickname', minWidth: 120 },
  { title: 'Owner ID', key: 'owner_id', minWidth: 220 },
  { title: '最近活跃', key: 'last_seen_at', minWidth: 160, render: (row) => formatTime(row.last_seen_at) },
  {
    title: '状态',
    key: 'kicked_at',
    width: 90,
    render: (row) => row.kicked_at
      ? h(NTag, { type: 'warning', size: 'small' }, () => '已踢出')
      : h(NTag, { type: 'success', size: 'small' }, () => '可访问'),
  },
  {
    title: '操作',
    key: 'actions',
    width: 90,
    render: (row) => row.kicked_at
      ? null
      : h(NPopconfirm, { onPositiveClick: () => kickParticipant(row.owner_id) }, {
        trigger: () => h(NButton, { text: true, type: 'error', size: 'small' }, () => '踢出'),
        default: () => '该用户将无法再用当前 session 进入房间。',
      }),
  },
])

onMounted(fetchRooms)
</script>

<style scoped>
.public-rooms-page {
  min-height: 100%;
  padding: 24px;
  background: #f8fafc;
}

.public-rooms-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.public-rooms-header h2 {
  margin: 0;
  font-size: 22px;
  line-height: 1.3;
  color: #0f172a;
}

.public-rooms-header p {
  margin: 6px 0 0;
  color: #64748b;
  font-size: 13px;
}

.public-rooms-toolbar {
  display: grid;
  grid-template-columns: minmax(220px, 320px) 160px auto;
  gap: 10px;
  align-items: center;
  margin-bottom: 12px;
}

.public-rooms-table {
  background: #fff;
}

.public-rooms-pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 12px;
  color: #64748b;
  font-size: 13px;
}

.table-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.public-room-detail {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.detail-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.detail-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.detail-section-head h3 {
  margin: 0;
  font-size: 15px;
  color: #111827;
}

.detail-section-head span {
  color: #64748b;
  font-size: 12px;
}

.message-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.message-row {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 10px 12px;
  background: #fff;
}

.message-row strong {
  color: #0f172a;
  font-size: 13px;
}

.message-row time {
  margin-left: 8px;
  color: #94a3b8;
  font-size: 12px;
}

.message-row p {
  margin: 6px 0 0;
  color: #334155;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

@media (max-width: 768px) {
  .public-rooms-page {
    padding: 14px;
  }

  .public-rooms-header {
    align-items: stretch;
    flex-direction: column;
  }

  .public-rooms-toolbar {
    grid-template-columns: 1fr;
  }

  .public-rooms-pagination {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
