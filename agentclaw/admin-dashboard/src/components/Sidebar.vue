<template>
  <aside class="sidebar" :class="{ collapsed }">
    <div class="sidebar-header" v-if="!collapsed">
      <h1>⚡ AgentClaw</h1>
      <span class="version">v{{ appVersion }}</span>
    </div>
    <div class="sidebar-header" v-else>
      <h1>⚡</h1>
    </div>
    <n-menu
      v-if="!collapsed"
      :options="menuOptions"
      :value="activeKey"
      :root-indent="20"
      @update:value="handleSelect"
    />
    <n-menu
      v-else
      :options="collapsedMenuOptions"
      :value="activeKey"
      :root-indent="8"
      @update:value="handleSelect"
    />
    <div class="sidebar-footer">
      <div
        v-if="!collapsed"
        class="settings-btn"
        :class="{ active: route.path === '/settings' }"
        @click="goSettings"
      >
        <span style="margin-right: 6px;">⚙️</span>{{ $t('nav.settings') }}
      </div>
      <div
        v-else
        class="settings-btn"
        :class="{ active: route.path === '/settings' }"
        @click="goSettings"
        :title="$t('nav.settings')"
      >
        <span>⚙️</span>
      </div>
      <button class="btn-collapse" @click="emit('update:collapsed', !collapsed)" :title="collapsed ? $t('nav.expand') : $t('nav.collapse')">
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
          <path :d="collapsed ? 'M9 18l6-6-6-6' : 'M15 18l-6-6 6-6'" />
        </svg>
      </button>
    </div>
  </aside>
</template>

<script setup>
import { h, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NMenu } from 'naive-ui'
import { useI18n } from 'vue-i18n'

const props = defineProps({
  collapsed: { type: Boolean, default: false },
})
const emit = defineEmits(['update:collapsed', 'select'])

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const appVersion = __APP_VERSION__

const baseMenuItems = computed(() => [
  { label: t('nav.builtin'), key: '/builtin', icon: '⚡' },
  { label: t('nav.templates'), key: '/templates', icon: '📦' },
  { label: t('nav.workflows'), key: '/workflows', icon: '🤖' },
  { label: t('nav.knowledgebases'), key: '/knowledgebases', icon: '📚' },
  { label: t('nav.scheduler'), key: '/scheduler', icon: '⏰' },
  { label: t('nav.channels'), key: '/channels', icon: '📡' },
  { label: t('nav.dashboard'), key: '/dashboard', icon: '📊' },
])

const menuOptions = computed(() => baseMenuItems.value.map(item => ({
  label: () => h('span', null, [
    h('span', { style: 'margin-right: 8px' }, item.icon),
    item.label
  ]),
  key: item.key,
})))

const collapsedMenuOptions = computed(() => baseMenuItems.value.map(item => ({
  label: () => h('span', { title: item.label, style: 'font-size: 16px; display: flex; justify-content: center;' }, item.icon),
  key: item.key,
})))

const activeKey = computed(() => {
  const path = route.path
  if (path === '/' || path === '/builtin') return '/builtin'
  if (path.startsWith('/templates')) return '/templates'
  if (path === '/dashboard' || path.startsWith('/traces')) return '/dashboard'
  if (path.startsWith('/workflows')) return '/workflows'
  if (path.startsWith('/scheduler')) return '/scheduler'
  if (path.startsWith('/channels')) return '/channels'
  if (path.startsWith('/knowledgebases')) return '/knowledgebases'
  return ''
})

function handleSelect(key) {
  router.push(key)
  emit('select', key)
}

function goSettings() {
  router.push('/settings')
  emit('select', '/settings')
}
</script>

<style scoped>
.sidebar {
  position: fixed;
  top: 0;
  left: 0;
  width: var(--sidebar-width);
  height: 100vh;
  background: var(--bg-white);
  border-right: 1px solid var(--border);
  z-index: 100;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  transition: width 0.2s;
}

.sidebar.collapsed {
  width: 56px;
}

.sidebar-header {
  padding: 20px;
  display: flex;
  align-items: center;
  gap: 8px;
  border-bottom: 1px solid var(--border);
}

.sidebar.collapsed .sidebar-header {
  padding: 16px 0;
  justify-content: center;
}

.sidebar-header h1 {
  font-size: 18px;
  font-weight: 700;
  margin: 0;
}

.version {
  font-size: 11px;
  color: var(--text-secondary);
  background: var(--bg-light);
  padding: 2px 6px;
  border-radius: 4px;
}

.sidebar-footer {
  margin-top: auto;
  padding: 12px 16px;
  border-top: 1px solid var(--border);
}

.sidebar.collapsed .sidebar-footer {
  padding: 8px;
}

.settings-btn {
  display: flex;
  align-items: center;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 13px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}

.sidebar.collapsed .settings-btn {
  justify-content: center;
  padding: 8px;
}

.settings-btn:hover {
  background: var(--bg-light);
  color: var(--text-primary);
}

.settings-btn.active {
  background: var(--primary-light, #e8f4fd);
  color: var(--primary, #18a058);
}

.btn-collapse {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  margin-top: 8px;
  padding: 6px;
  background: transparent;
  border: 1px solid var(--border, #e4e4e7);
  border-radius: 6px;
  cursor: pointer;
  color: var(--text-secondary, #a1a1aa);
  transition: all 0.2s;
}

.btn-collapse:hover {
  background: var(--bg-light);
  color: var(--text-primary);
}

@media (max-width: 1024px) {
  .sidebar {
    display: none;
  }

  .sidebar.mobile-main-sidebar {
    position: static;
    display: flex;
    width: min(82vw, 280px);
    height: 100vh;
    height: 100dvh;
    box-shadow: 24px 0 52px -34px rgba(15,23,42,0.65);
  }

  .sidebar.mobile-main-sidebar .btn-collapse {
    display: none;
  }
}
</style>
