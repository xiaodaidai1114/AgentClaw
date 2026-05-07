import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

describe('knowledgebase model selectors', () => {
  it('loads rerank selector options from the full model list', () => {
    const apiSource = readFileSync(resolve(process.cwd(), 'src/api/index.js'), 'utf8')
    const listSource = readFileSync(resolve(process.cwd(), 'src/views/KnowledgeBases.vue'), 'utf8')
    const detailSource = readFileSync(resolve(process.cwd(), 'src/views/KnowledgebaseDetail.vue'), 'utf8')

    expect(apiSource).toContain('list: () => api.get(\'/models\')')
    expect(listSource).toContain('const res = await modelsApi.list()')
    expect(detailSource).toContain('const response = await modelsApi.list()')
  })

  it('shows rerank as an applied post-processing state instead of a per-hit score', () => {
    const detailSource = readFileSync(resolve(process.cwd(), 'src/views/KnowledgebaseDetail.vue'), 'utf8')
    const zh = readFileSync(resolve(process.cwd(), 'src/locales/zh-CN.js'), 'utf8')
    const en = readFileSync(resolve(process.cwd(), 'src/locales/en-US.js'), 'utf8')

    expect(detailSource).toContain('response.rerank_applied')
    expect(detailSource).toContain('rerankApplied')
    expect(detailSource).not.toContain('item.rerankScore')
    expect(detailSource).not.toContain('rerank_score.toFixed')
    expect(zh).toContain('rerankApplied')
    expect(en).toContain('rerankApplied')
  })

  it('lets operators delete documents and surfaces parse failures inline', () => {
    const detailSource = readFileSync(resolve(process.cwd(), 'src/views/KnowledgebaseDetail.vue'), 'utf8')
    const zh = readFileSync(resolve(process.cwd(), 'src/locales/zh-CN.js'), 'utf8')
    const en = readFileSync(resolve(process.cwd(), 'src/locales/en-US.js'), 'utf8')

    expect(detailSource).toContain('NPopconfirm')
    expect(detailSource).toContain('handleDeleteDocument')
    expect(detailSource).toContain('knowledgebaseApi.deleteDocument')
    expect(detailSource).toContain("item.error && item.status !== 'processing' ? 'failed'")
    expect(detailSource).toContain('document-error-text')
    expect(detailSource).toContain('hasProcessingDocuments')
    expect(detailSource).toContain('startDocumentPolling')
    expect(detailSource).toContain('onBeforeUnmount(stopDocumentPolling)')
    expect(zh).toContain('deleteDocumentConfirm')
    expect(en).toContain('deleteDocumentConfirm')
  })
})
