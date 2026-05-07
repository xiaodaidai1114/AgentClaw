<template>
  <header class="page-header">
    <div class="header-left">
      <n-breadcrumb v-if="breadcrumbs.length">
        <n-breadcrumb-item v-for="(item, index) in breadcrumbs" :key="index">
          <router-link v-if="item.to" :to="item.to">{{ item.text }}</router-link>
          <span v-else>{{ item.text }}</span>
        </n-breadcrumb-item>
      </n-breadcrumb>
      <h2 v-else>{{ title }}</h2>
    </div>
    <n-space class="header-right" :size="12" align="center">
      <slot name="actions">
        <n-select
          v-if="showTimeSelector"
          v-model:value="selectedTime"
          :options="timeOptions"
          :style="{ width: '150px' }"
          size="small"
          @update:value="$emit('time-change', $event)"
        />
      </slot>
    </n-space>
  </header>
</template>

<script setup>
import { computed, ref } from 'vue'
import { NBreadcrumb, NBreadcrumbItem, NSelect, NSpace } from 'naive-ui'
import { useI18n } from 'vue-i18n'

const props = defineProps({
  title: { type: String, default: '' },
  breadcrumbs: { type: Array, default: () => [] },
  showTimeSelector: { type: Boolean, default: false },
  showRefresh: { type: Boolean, default: true },
  defaultTime: { type: String, default: '24h' },
})

defineEmits(['time-change', 'refresh'])

const selectedTime = ref(props.defaultTime)
const { t } = useI18n()

const timeOptions = computed(() => [
  { label: t('pageHeader.time24h'), value: '24h' },
  { label: t('pageHeader.time7d'), value: '7d' },
  { label: t('pageHeader.time30d'), value: '30d' },
])
</script>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.page-header h2 {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
}
</style>
