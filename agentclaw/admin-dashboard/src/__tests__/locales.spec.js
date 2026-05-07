import { describe, expect, it } from 'vitest'
import zhCN from '../locales/zh-CN'
import enUS from '../locales/en-US'

function flattenKeys(obj, prefix = '') {
  return Object.entries(obj).flatMap(([key, value]) => {
    const nextKey = prefix ? `${prefix}.${key}` : key
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      return flattenKeys(value, nextKey)
    }
    return [nextKey]
  })
}

describe('locale catalogs', () => {
  it('keep locale keys aligned and include the active i18n rollout sections', () => {
    const zhKeys = flattenKeys(zhCN).sort()
    const enKeys = flattenKeys(enUS).sort()
    const requiredPrefixes = [
      'workflowConfig',
      'workflowDebug',
      'agentChat',
      'settingsForm',
      'agents',
      'knowledgebaseDocumentDetail',
      'knowledgebaseSearch',
      'schedulerPage',
      'traceDetail',
      'cronBuilder',
      'documentUploadDialog',
      'knowledgebaseUpload',
      'chatSidebar',
      'jsonCodeBlock',
      'streamingMessage',
      'todoCard',
      'schedulerDetail',
      'schedulerJobForm',
      'knowledgebaseDetail',
      'channelLogs',
      'promptsPage',
      'promptConfigPanel',
      'chatInput',
      'chatMessage',
      'confirmDialog',
    ]

    expect(enKeys).toEqual(zhKeys)

    for (const prefix of requiredPrefixes) {
      expect(zhKeys.some(key => key.startsWith(`${prefix}.`))).toBe(true)
    }
  })
})
