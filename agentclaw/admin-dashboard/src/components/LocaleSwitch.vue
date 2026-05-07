<template>
  <n-select
    :value="locale"
    :options="options"
    size="small"
    style="width: 120px;"
    @update:value="handleChange"
  />
</template>

<script setup>
import { computed } from 'vue'
import { NSelect } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import { LOCALE_OPTIONS, setLocale } from '../i18n'

const i18n = useI18n()

const locale = computed(() => i18n.locale.value)
const options = computed(() => LOCALE_OPTIONS.map((item) => ({
  ...item,
  label: item.value === 'zh-CN' ? i18n.t('locale.zhCN') : i18n.t('locale.enUS'),
})))

function handleChange(value) {
  setLocale(i18n, value)
}
</script>
