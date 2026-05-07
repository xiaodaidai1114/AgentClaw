<template>
  <div class="chat-sidebar" :class="{ collapsed }">
    <div class="sidebar-header" v-if="!collapsed">
      <span class="sidebar-title">{{ $t('chatSidebar.recentConversations') }}</span>
      <button class="btn-icon-ghost" :title="$t('chatSidebar.createConversation')" @click="$emit('new-conversation')">
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M12 5v14M5 12h14"/>
        </svg>
      </button>
    </div>
    <div class="history-section" v-if="!collapsed">
      <div
        v-for="conv in conversations"
        :key="conv.id"
        class="history-item"
        :class="{ active: conv.id === activeId }"
        role="button"
        tabindex="0"
        @click="$emit('select', conv.id)"
        @keydown.enter.prevent="$emit('select', conv.id)"
        @keydown.space.prevent="$emit('select', conv.id)"
      >
        <div class="history-left">
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>
          <span class="history-title">{{ conv.title || $t('chatSidebar.newConversation') }}</span>
        </div>
        <div class="history-right">
          <span class="history-time mono-font">{{ formatTime(conv) }}</span>
          <button
            class="history-delete-btn"
            :title="$t('chatSidebar.deleteConversation')"
            @click.stop="$emit('delete', conv.id)"
          >
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/>
              <line x1="10" y1="11" x2="10" y2="17"/>
              <line x1="14" y1="11" x2="14" y2="17"/>
            </svg>
          </button>
        </div>
      </div>
      <div v-if="conversations.length === 0" class="empty-hint">{{ $t('chatSidebar.noHistory') }}</div>
    </div>
    <button class="btn-toggle" @click="$emit('update:collapsed', !collapsed)">
      {{ collapsed ? '→' : '←' }}
    </button>
  </div>
</template>

<script>
export default {
  name: 'ChatSidebar',
  props: {
    conversations: { type: Array, default: () => [] },
    activeId: { type: String, default: '' },
    collapsed: { type: Boolean, default: false },
  },
  emits: ['new-conversation', 'select', 'delete', 'update:collapsed'],
  methods: {
    formatTime(conv) {
      if (!conv.updated_at && !conv.created_at) return ''
      const ts = conv.updated_at || conv.created_at
      const d = new Date(typeof ts === 'number' ? ts : ts)
      const now = new Date()
      if (d.toDateString() === now.toDateString()) {
        return d.toTimeString().slice(0, 5)
      }
      const yesterday = new Date(now)
      yesterday.setDate(yesterday.getDate() - 1)
      if (d.toDateString() === yesterday.toDateString()) return this.$t('chatSidebar.yesterday')
      return `${d.getMonth() + 1}/${d.getDate()}`
    },
  },
}
</script>

<style scoped>
.chat-sidebar {
  width: 260px;
  background: var(--bg-sidebar, #fbfbfb);
  border-right: 1px solid var(--border-base, #e4e4e7);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  transition: width 0.2s;
}
.chat-sidebar.collapsed { width: 48px; }

.sidebar-header {
  padding: 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.sidebar-title { font-size: 13px; font-weight: 600; color: var(--text-muted, #a1a1aa); text-transform: uppercase; letter-spacing: 0.5px; }

.btn-icon-ghost {
  background: transparent; border: none; color: var(--text-sec, #52525b);
  cursor: pointer; padding: 6px; border-radius: var(--radius-sm, 8px);
  display: flex; align-items: center; justify-content: center; transition: all 0.2s ease;
}
.btn-icon-ghost:hover { background: var(--border-base, #e4e4e7); color: var(--text-main, #18181b); }

.history-section { flex: 1; overflow-y: auto; padding: 8px 12px; }

.history-item {
  padding: 8px 10px; margin-bottom: 4px; border-radius: var(--radius-sm, 8px); cursor: pointer;
  display: flex; align-items: center; justify-content: space-between; gap: 10px;
  color: var(--text-sec, #52525b); transition: all 0.2s ease; border: 1px solid transparent;
}
.history-item:hover { background: var(--bg-hover, #f1f1f1); color: var(--text-main, #18181b); }
.history-item.active { background: var(--bg-app, #fff); color: var(--text-main, #18181b); font-weight: 500; border-color: var(--border-base, #e4e4e7); box-shadow: var(--shadow-sm); }

.history-left { display: flex; align-items: center; gap: 8px; overflow: hidden; flex: 1; }
.history-title { font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.history-right { position: relative; width: 32px; display: flex; justify-content: flex-end; align-items: center; }
.history-time { font-size: 11px; color: var(--text-muted, #a1a1aa); transition: opacity 0.2s; }
.history-delete-btn {
  position: absolute; right: -4px; opacity: 0; background: transparent; border: none;
  color: var(--text-muted, #a1a1aa); cursor: pointer; padding: 4px; border-radius: 4px;
  display: flex; align-items: center; justify-content: center; transition: all 0.2s;
}
.history-item:hover .history-time { opacity: 0; }
.history-item:hover .history-delete-btn { opacity: 1; }
.history-delete-btn:hover { background: #fee2e2; color: var(--danger-main, #ef4444); }

.empty-hint { text-align: center; color: var(--text-muted, #a1a1aa); font-size: 13px; padding: 24px 0; }

.btn-toggle {
  margin: 8px; padding: 6px; background: transparent; border: 1px solid var(--border-base, #e4e4e7);
  border-radius: 6px; cursor: pointer; color: var(--text-muted, #a1a1aa); font-size: 12px;
  transition: all 0.2s;
}
.btn-toggle:hover { background: var(--bg-hover, #f1f1f1); color: var(--text-main, #18181b); }

.mono-font { font-family: var(--font-mono, ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace); }
</style>
