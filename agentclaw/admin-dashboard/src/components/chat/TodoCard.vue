<template>
  <div class="todo-inline-card">
    <div class="todo-header">
      <div class="todo-header-left">
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 11l3 3L22 4M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11"/></svg>
        {{ $t('todoCard.executionPlan') }}
      </div>
      <div class="todo-progress mono-font">{{ $t('todoCard.completedProgress', { completed: completedCount, total: items.length }) }}</div>
    </div>
    <div class="todo-list">
      <div v-for="(item, i) in items" :key="i" class="todo-item" :class="item.status === 'completed' ? 'completed' : item.status === 'in_progress' ? 'active' : ''">
        <div class="todo-checkbox">
          <svg v-if="item.status === 'completed'" viewBox="0 0 24 24" width="10" height="10" fill="none" stroke="white" stroke-width="3"><path d="M20 6L9 17l-5-5"/></svg>
          <span v-else-if="item.status === 'in_progress'" class="spinner-dot"></span>
        </div>
        <div class="todo-content">
          <div>{{ item.content }}</div>
          <div v-if="item.status === 'in_progress' && item.activeForm" class="todo-active">{{ item.activeForm }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  name: 'TodoCard',
  props: {
    items: { type: Array, default: () => [] },
  },
  computed: {
    completedCount() {
      return this.items.filter(i => i.status === 'completed').length
    },
  },
}
</script>

<style scoped>
.mono-font { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
.todo-inline-card { width: 100%; max-width: 520px; background: var(--bg-main, #fff); border: 1px solid var(--border-color, #e2e8f0); border-radius: 10px; box-shadow: 0 1px 2px 0 rgba(0,0,0,0.05); overflow: hidden; margin: 4px 0; }
.todo-header { padding: 10px 14px; background: var(--bg-panel, #f8fafc); border-bottom: 1px solid var(--border-color, #e2e8f0); display: flex; align-items: center; justify-content: space-between; font-size: 13px; font-weight: 600; color: var(--text-main, #0f172a); }
.todo-header-left { display: flex; align-items: center; gap: 8px; }
.todo-progress { font-size: 11px; color: var(--text-muted, #94a3b8); font-weight: 500; background: #e2e8f0; padding: 2px 8px; border-radius: 12px; }
.todo-list { display: flex; flex-direction: column; }
.todo-item { display: flex; gap: 12px; padding: 12px 14px; border-bottom: 1px solid #f1f5f9; transition: background 0.2s; }
.todo-item:last-child { border-bottom: none; }
.todo-checkbox { width: 16px; height: 16px; border-radius: 4px; border: 2px solid var(--text-muted, #94a3b8); display: flex; align-items: center; justify-content: center; flex-shrink: 0; margin-top: 2px; }
.todo-item.completed .todo-checkbox { background: var(--success-color, #10b981); border-color: var(--success-color, #10b981); }
.todo-item.active .todo-checkbox { border-color: var(--accent-color, #3b82f6); }
.todo-content { flex: 1; font-size: 13px; line-height: 1.5; color: var(--text-main, #0f172a); }
.todo-item.completed .todo-content { text-decoration: line-through; color: var(--text-muted, #94a3b8); }
.todo-active { font-size: 12px; color: var(--accent-color, #3b82f6); margin-top: 2px; }
.spinner-dot { width: 8px; height: 8px; border: 2px solid var(--accent-color, #3b82f6); border-top-color: transparent; border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { 100% { transform: rotate(360deg); } }
</style>
