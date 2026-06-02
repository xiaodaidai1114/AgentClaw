<template>
  <n-config-provider :theme-overrides="themeOverrides" :locale="naiveLocale" :date-locale="naiveDateLocale">
    <n-message-provider>
      <n-dialog-provider>
        <div class="layout" :class="{ 'public-layout': isPublicRoute, 'sidebar-collapsed': sidebarCollapsed }">
          <Sidebar v-if="!isPublicRoute" v-model:collapsed="sidebarCollapsed" />
          <button v-if="!isPublicRoute" class="mobile-main-nav-toggle" type="button" @click="mobileSidebarOpen = true">
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
          <div v-if="!isPublicRoute && mobileSidebarOpen" class="mobile-main-sidebar-overlay" @click.self="mobileSidebarOpen = false">
            <Sidebar class="mobile-main-sidebar" :collapsed="false" @update:collapsed="mobileSidebarOpen = false" @select="mobileSidebarOpen = false" />
          </div>
          <main class="main-content">
            <router-view v-if="isPublicRoute || hasAuthenticatedAdmin" :key="routeViewKey" />
          </main>
          <LoginModal v-if="!isPublicRoute" />
        </div>
      </n-dialog-provider>
    </n-message-provider>
  </n-config-provider>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { NConfigProvider, NMessageProvider, NDialogProvider, zhCN, enUS, dateZhCN, dateEnUS } from 'naive-ui'
import Sidebar from './components/Sidebar.vue'
import LoginModal from './components/LoginModal.vue'
import { getAdminToken } from './api'

const route = useRoute()
const sidebarCollapsed = ref(false)
const mobileSidebarOpen = ref(false)
const hasAuthenticatedAdmin = ref(!!getAdminToken())
const { locale } = useI18n()

const themeOverrides = {
  common: {
    primaryColor: '#1890ff',
    primaryColorHover: '#40a9ff',
    primaryColorPressed: '#096dd9',
  }
}

const isPublicRoute = computed(() => {
  if (route.meta?.public === true) return true
  return false
})

const naiveLocale = computed(() => locale.value === 'en-US' ? enUS : zhCN)
const naiveDateLocale = computed(() => locale.value === 'en-US' ? dateEnUS : dateZhCN)
const chatRouteNames = new Set(['AgentChat', 'BuiltinAgent', 'PublicAgent'])
const routeViewKey = computed(() => {
  const routeName = String(route.name || '')
  if (chatRouteNames.has(routeName)) return route.fullPath
  return routeName || route.path
})

function refreshAdminAuthState() {
  hasAuthenticatedAdmin.value = !!getAdminToken()
}

function onAdminAuthRequired() {
  hasAuthenticatedAdmin.value = false
}

onMounted(() => {
  window.addEventListener('admin-auth-required', onAdminAuthRequired)
  window.addEventListener('admin-auth-updated', refreshAdminAuthState)
})

onUnmounted(() => {
  window.removeEventListener('admin-auth-required', onAdminAuthRequired)
  window.removeEventListener('admin-auth-updated', refreshAdminAuthState)
})
</script>

<style scoped>
.mobile-main-nav-toggle,
.mobile-main-sidebar-overlay {
  display: none;
}

@media (max-width: 1024px) {
  .mobile-main-nav-toggle {
    position: fixed;
    top: calc(10px + env(safe-area-inset-top));
    left: 10px;
    z-index: 210;
    width: 38px;
    height: 38px;
    border: 1px solid var(--border, #e8e8e8);
    border-radius: 8px;
    background: rgba(255,255,255,0.96);
    color: var(--text-primary, #262626);
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 0;
    box-shadow: var(--shadow, 0 2px 8px rgba(0,0,0,0.08));
  }

  .mobile-main-sidebar-overlay {
    position: fixed;
    inset: 0;
    z-index: 300;
    background: rgba(15,23,42,0.36);
    display: flex;
  }
}
</style>
