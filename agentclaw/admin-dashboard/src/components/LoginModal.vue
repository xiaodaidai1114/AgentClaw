<template>
  <n-modal v-model:show="show" :mask-closable="false" :close-on-esc="false">
    <n-card :title="$t('auth.title')" style="width: 420px;" :bordered="false" size="huge">
      <n-space vertical :size="16">
        <n-text depth="3">{{ $t('auth.hint') }}</n-text>
        <n-input
          v-model:value="token"
          type="password"
          :placeholder="$t('auth.tokenPlaceholder')"
          show-password-on="click"
          @keyup.enter="handleLogin"
          autofocus
        />
        <n-text v-if="error" type="error">{{ error }}</n-text>
        <n-button
          type="primary"
          block
          :loading="loading"
          :disabled="!token"
          @click="handleLogin"
        >
          {{ $t('auth.login') }}
        </n-button>
      </n-space>
    </n-card>
  </n-modal>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { NModal, NCard, NInput, NButton, NSpace, NText } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import { clearAdminToken, setAdminToken, getAdminToken } from '../api'

const show = ref(false)
const token = ref('')
const error = ref('')
const loading = ref(false)
const { t } = useI18n()

function checkAuth() {
  if (!getAdminToken()) {
    show.value = true
  }
}

async function handleLogin() {
  if (!token.value) return

  loading.value = true
  error.value = ''

  try {
    setAdminToken(token.value)

    const response = await fetch('/admin/workflows', {
      headers: { 'Authorization': `Bearer ${token.value}` }
    })

    if (response.ok) {
      show.value = false
      window.location.reload()
    } else {
      error.value = t('auth.invalidToken')
      clearAdminToken()
    }
  } catch (e) {
    error.value = t('auth.connectionFailed')
    clearAdminToken()
  } finally {
    loading.value = false
  }
}

function onAuthRequired() {
  show.value = true
}

onMounted(() => {
  checkAuth()
  window.addEventListener('admin-auth-required', onAuthRequired)
})

onUnmounted(() => {
  window.removeEventListener('admin-auth-required', onAuthRequired)
})
</script>
