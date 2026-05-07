<template>
  <Teleport to="body">
      <div v-if="modelValue" class="upload-overlay" @click.self="closeDialog">
        <div class="upload-dialog">
          <div class="upload-header">
            <div>
            <h3>{{ dialogTitle }}</h3>
            <p>{{ progressLabel || t('documentUploadDialog.filesQueued', { count: files.length }) }}</p>
          </div>
          <button class="icon-btn" :disabled="uploading" @click="closeDialog">✕</button>
        </div>

        <div class="upload-picker">
          <div>
            <strong>{{ files.length ? t('documentUploadDialog.selectedFiles') : t('documentUploadDialog.selectDocument') }}</strong>
            <span>{{ files.length ? t('documentUploadDialog.totalFilesSize', { count: files.length, size: formatSize(totalSize) }) : t('documentUploadDialog.multiSelectHint') }}</span>
          </div>
          <div class="upload-picker-actions">
            <button class="btn-default" @click="pickFiles">{{ files.length ? t('documentUploadDialog.continueAdding') : t('documentUploadDialog.selectFiles') }}</button>
            <button v-if="files.length" class="btn-default" :disabled="uploading" @click="$emit('clear')">{{ t('documentUploadDialog.clear') }}</button>
          </div>
          <input ref="inputRef" type="file" class="hidden-input" multiple @change="handleSelect">
        </div>

        <div v-if="errorText" class="upload-error">{{ errorText }}</div>

        <div v-if="files.length" class="upload-list">
          <div v-for="(item, index) in files" :key="item.id || fileKey(item.file || item)" class="upload-item">
            <div class="upload-item-meta">
              <div class="upload-item-top">
                <strong>{{ item.file?.name || item.name }}</strong>
                <span class="upload-status" :class="`upload-status--${item.status || 'queued'}`">{{ statusText(item.status) }}</span>
              </div>
              <span>{{ formatSize(item.file?.size || item.size || 0) }}</span>
              <span v-if="item.error" class="upload-item-error">{{ item.error }}</span>
            </div>
            <button class="btn-link" :disabled="isActive(item.status)" @click="$emit('remove', index)">{{ t('documentUploadDialog.remove') }}</button>
          </div>
        </div>
        <div v-else class="upload-empty">
          <strong>{{ t('documentUploadDialog.noFilesSelected') }}</strong>
          <span>{{ t('documentUploadDialog.selectFilesToImport') }}</span>
        </div>

        <div class="upload-footer">
          <button class="btn-default" @click="closeDialog">{{ uploading ? t('documentUploadDialog.close') : t('common.cancel') }}</button>
          <button class="btn-primary" :disabled="!queuedCount || uploading" @click="$emit('submit')">
            {{ uploading ? t('documentUploadDialog.queueProcessing') : t('documentUploadDialog.startUpload', { count: queuedCount }) }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  files: { type: Array, default: () => [] },
  uploading: { type: Boolean, default: false },
  progressLabel: { type: String, default: '' },
  errorText: { type: String, default: '' },
  title: { type: String, default: '' },
})

const emit = defineEmits(['update:modelValue', 'select', 'remove', 'clear', 'submit'])
const { t } = useI18n()
const inputRef = ref(null)
const dialogTitle = computed(() => props.title || t('documentUploadDialog.title'))
const totalSize = computed(() => props.files.reduce((sum, item) => sum + (item?.file?.size || item?.size || 0), 0))
const queuedCount = computed(() => props.files.filter((item) => (item?.status || 'queued') === 'queued').length)

function closeDialog() {
  emit('update:modelValue', false)
}

function pickFiles() {
  inputRef.value?.click()
}

function handleSelect(event) {
  const files = Array.from(event.target.files || [])
  if (files.length) emit('select', files)
  event.target.value = ''
}

function fileKey(file) {
  return [file.name, file.size, file.lastModified].join(':')
}

function isActive(status) {
  return status === 'uploading' || status === 'processing'
}

function statusText(status) {
  return {
    queued: t('documentUploadDialog.status.queued'),
    uploading: t('documentUploadDialog.status.uploading'),
    processing: t('documentUploadDialog.status.processing'),
    failed: t('documentUploadDialog.status.failed'),
    success: t('documentUploadDialog.status.success'),
  }[status || 'queued']
}

function formatSize(size) {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}
</script>

<style scoped>
.upload-overlay { position: fixed; inset: 0; z-index: 2000; display: flex; align-items: center; justify-content: center; padding: 20px; background: rgba(15, 23, 42, 0.36); backdrop-filter: blur(6px); }
.upload-dialog { width: min(720px, 100%); max-height: min(760px, calc(100vh - 40px)); display: flex; flex-direction: column; gap: 16px; padding: 20px; border-radius: 20px; background: #fff; box-shadow: 0 24px 60px rgba(15, 23, 42, 0.18); }
.upload-header, .upload-footer, .upload-picker, .upload-item { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.upload-header h3 { margin: 0; font-size: 18px; }
.upload-header p { margin: 6px 0 0; color: #64748b; font-size: 13px; }
.icon-btn { width: 36px; height: 36px; border: 1px solid var(--border); border-radius: 10px; background: #fff; cursor: pointer; }
.upload-picker { padding: 16px; border: 1px dashed #bfd3f2; border-radius: 16px; background: #f8fbff; }
.upload-picker strong, .upload-item strong { display: block; }
.upload-picker span, .upload-item span { color: #64748b; font-size: 13px; }
.upload-picker-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.upload-error { padding: 10px 12px; border-radius: 12px; background: #fff1f0; color: #cf1322; font-size: 13px; }
.upload-list { display: grid; gap: 10px; max-height: 320px; overflow: auto; padding-right: 4px; }
.upload-item { padding: 12px 14px; border: 1px solid #e8edf5; border-radius: 14px; background: #fff; }
.upload-item-meta { min-width: 0; }
.upload-item-top { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.upload-item-meta strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.upload-item-error { color: #cf1322; }
.upload-status { display: inline-flex; align-items: center; justify-content: center; min-width: 64px; height: 24px; padding: 0 10px; border-radius: 999px; font-size: 12px; font-weight: 600; white-space: nowrap; }
.upload-status--queued { background: #f1f5f9; color: #475569; }
.upload-status--uploading { background: #e6f4ff; color: #1677ff; }
.upload-status--processing { background: #fff7e6; color: #d46b08; }
.upload-status--failed { background: #fff1f0; color: #cf1322; }
.upload-status--success { background: #f6ffed; color: #389e0d; }
.upload-empty { display: flex; min-height: 180px; flex-direction: column; align-items: center; justify-content: center; gap: 8px; border: 1px dashed #d8e1ee; border-radius: 16px; background: #fbfdff; color: #64748b; text-align: center; }
.upload-empty strong { color: var(--text-primary); }
.upload-footer { padding-top: 4px; }
.hidden-input { display: none; }
.btn-link { color: var(--primary); text-decoration: none; }
@media (max-width: 720px) {
  .upload-overlay { padding: 12px; }
  .upload-dialog { padding: 16px; }
  .upload-header, .upload-picker, .upload-footer, .upload-item { align-items: flex-start; flex-direction: column; }
  .icon-btn { align-self: flex-end; }
  .upload-footer button { width: 100%; }
}
</style>
