<template>
  <n-config-provider :theme-overrides="themeOverrides" :locale="naiveLocale" :date-locale="naiveDateLocale">
    <n-message-provider>
      <n-dialog-provider>
        <div class="layout" :class="{ 'public-layout': isPublicRoute, 'sidebar-collapsed': sidebarCollapsed }">
          <Sidebar v-if="!isPublicRoute" v-model:collapsed="sidebarCollapsed" />
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
