import { computed, onBeforeUnmount, ref, unref } from 'vue'
import { useI18n } from 'vue-i18n'
import { knowledgebaseApi } from '../api'

const POLL_INTERVAL_MS = 1500

function fileFingerprint(file) {
  return [file.name, file.size, file.lastModified].join(':')
}

function resolveKnowledgebaseId(source) {
  const value = unref(source)
  return typeof value === 'function' ? value() : value
}

function normalizeQueueStatus(status) {
  if (status === 'ready') return 'success'
  if (status === 'failed') return 'failed'
  if (status === 'processing') return 'processing'
  return status
}

function createQueueItem(file) {
  return {
    id: fileFingerprint(file),
    file,
    documentId: '',
    status: 'queued',
    error: '',
  }
}

export function useKnowledgebaseUpload(knowledgebaseId, onUploaded) {
  const { t } = useI18n()
  const showUploadDialog = ref(false)
  const selectedFiles = ref([])
  const isQueueRunning = ref(false)
  const isPolling = ref(false)
  const pollTimer = ref(null)
  const uploadError = ref('')

  function extractError(error) {
    return error.response?.data?.detail?.error || error.response?.data?.error || error.message || t('knowledgebaseUpload.uploadFailed')
  }

  const hasProcessingItems = computed(() => selectedFiles.value.some((item) => item.status === 'processing'))
  const isUploading = computed(() => isQueueRunning.value)
  const queuedCount = computed(() => selectedFiles.value.filter((item) => item.status === 'queued').length)
  const uploadProgressLabel = computed(() => {
    const total = selectedFiles.value.length
    if (!total) return ''
    const uploading = selectedFiles.value.filter((item) => item.status === 'uploading').length
    const processing = selectedFiles.value.filter((item) => item.status === 'processing').length
    const success = selectedFiles.value.filter((item) => item.status === 'success').length
    const failed = selectedFiles.value.filter((item) => item.status === 'failed').length
    if (uploading) return t('knowledgebaseUpload.queueUploading', { processing, success, failed })
    if (processing) return t('knowledgebaseUpload.processingInBackground', { processing, success, failed })
    if (success || failed) return t('knowledgebaseUpload.queueCompleted', { success, failed })
    return t('knowledgebaseUpload.filesQueued', { count: queuedCount.value })
  })

  function openUploadDialog() {
    uploadError.value = ''
    showUploadDialog.value = true
  }

  function closeUploadDialog() {
    showUploadDialog.value = false
  }

  function addUploadFiles(files) {
    const nextFiles = Array.isArray(files) ? files : Array.from(files || [])
    if (!nextFiles.length) return
    const merged = new Map(selectedFiles.value.map((item) => [item.id, item]))
    nextFiles.forEach((file) => {
      const id = fileFingerprint(file)
      if (!merged.has(id)) merged.set(id, createQueueItem(file))
    })
    selectedFiles.value = [...merged.values()]
    uploadError.value = ''
  }

  function removeUploadFile(index) {
    const item = selectedFiles.value[index]
    if (!item || item.status === 'uploading' || item.status === 'processing') return
    selectedFiles.value = selectedFiles.value.filter((_, fileIndex) => fileIndex !== index)
  }

  function clearUploadFiles() {
    if (isUploading.value) return
    selectedFiles.value = []
    uploadError.value = ''
  }

  async function pollDocumentStatuses() {
    const resolvedKnowledgebaseId = resolveKnowledgebaseId(knowledgebaseId)
    const trackedItems = selectedFiles.value.filter((item) => item.documentId && item.status === 'processing')
    if (!resolvedKnowledgebaseId || !trackedItems.length || isPolling.value) {
      if (!trackedItems.length) stopPolling()
      return
    }
    isPolling.value = true
    try {
      const response = await knowledgebaseApi.listDocuments(resolvedKnowledgebaseId)
      const documents = new Map((response.documents || []).map((item) => [item.id, item]))
      let changed = false
      trackedItems.forEach((item) => {
        const document = documents.get(item.documentId)
        if (!document) return
        const nextStatus = normalizeQueueStatus(document.status)
        const nextError = document.error || ''
        if (item.status !== nextStatus || item.error !== nextError) {
          item.status = nextStatus
          item.error = nextError
          changed = true
        }
      })
      if (changed) await onUploaded?.()
    } catch (error) {
      uploadError.value = extractError(error)
    } finally {
      isPolling.value = false
      if (!hasProcessingItems.value) stopPolling()
    }
  }

  function startPolling() {
    if (pollTimer.value || !hasProcessingItems.value) return
    pollTimer.value = window.setInterval(() => {
      void pollDocumentStatuses()
    }, POLL_INTERVAL_MS)
    void pollDocumentStatuses()
  }

  function stopPolling() {
    if (!pollTimer.value) return
    window.clearInterval(pollTimer.value)
    pollTimer.value = null
  }

  async function runUploadQueue() {
    const resolvedKnowledgebaseId = resolveKnowledgebaseId(knowledgebaseId)
    if (!resolvedKnowledgebaseId) {
      uploadError.value = t('knowledgebaseUpload.missingKnowledgebaseId')
      return
    }
    if (isQueueRunning.value) return
    isQueueRunning.value = true
    uploadError.value = ''
    try {
      while (true) {
        const nextItem = selectedFiles.value.find((item) => item.status === 'queued')
        if (!nextItem) break
        nextItem.status = 'uploading'
        nextItem.error = ''
        try {
          const formData = new FormData()
          formData.append('file', nextItem.file)
          const response = await knowledgebaseApi.uploadDocument(resolvedKnowledgebaseId, formData)
          nextItem.documentId = response.id || ''
          nextItem.error = response.error || ''
          nextItem.status = normalizeQueueStatus(response.status)
          await onUploaded?.()
          if (nextItem.status === 'processing') startPolling()
        } catch (error) {
          nextItem.status = 'failed'
          nextItem.error = extractError(error)
        }
      }
    } finally {
      isQueueRunning.value = false
      if (hasProcessingItems.value) startPolling()
    }
  }

  function submitUpload() {
    if (!queuedCount.value || isQueueRunning.value) return
    void runUploadQueue()
  }

  onBeforeUnmount(() => {
    stopPolling()
  })

  return {
    showUploadDialog,
    selectedFiles,
    isUploading,
    uploadProgressLabel,
    uploadError,
    openUploadDialog,
    closeUploadDialog,
    addUploadFiles,
    removeUploadFile,
    clearUploadFiles,
    submitUpload,
  }
}
