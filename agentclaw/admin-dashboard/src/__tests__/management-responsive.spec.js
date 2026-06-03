import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

describe('management pages responsive layout safeguards', () => {
  it('lets common page headers wrap actions on narrow screens', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/components/PageHeader.vue'), 'utf8')

    expect(source).toContain('.page-header {')
    expect(source).toContain('min-width: 0;')
    expect(source).toContain('flex-wrap: wrap;')
    expect(source).toContain('.header-left')
    expect(source).toContain('.header-right')
    expect(source).toContain('@media (max-width: 640px)')
  })

  it('keeps channel configuration controls and tables inside the viewport', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/views/Channels.vue'), 'utf8')

    expect(source).toContain('class="channels-page"')
    expect(source).toContain('class="channel-filter-card"')
    expect(source).toContain('class="channel-filter-space"')
    expect(source).toContain('class="table-scroll"')
    expect(source).toContain('scroll-x="max-content"')
    expect(source).toContain('@media (max-width: 1024px)')
    expect(source).toContain('.channel-filter-space :deep(.n-input)')
    expect(source).toContain('width: 100% !important;')
  })

  it('keeps dashboard overview cards and tables responsive', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/views/Dashboard.vue'), 'utf8')

    expect(source).toContain('class="dashboard-page"')
    expect(source).toContain('class="overview-toolbar-space"')
    expect(source).toContain('class="table-scroll"')
    expect(source).toContain('scroll-x="max-content"')
    expect(source).toContain('@media (max-width: 1024px)')
    expect(source).toContain('.overview-toolbar-space :deep(.n-select)')
    expect(source).toContain('width: 100% !important;')
  })

  it('keeps execution traces list filters, table, and pagination responsive', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/views/Traces.vue'), 'utf8')

    expect(source).toContain('class="traces-page"')
    expect(source).toContain('class="trace-filter-card"')
    expect(source).toContain('class="trace-filter-space"')
    expect(source).toContain('class="table-scroll"')
    expect(source).toContain('class="trace-pagination"')
    expect(source).toContain(':scroll-x="traceTableScrollX"')
    expect(source).toContain('const traceTableScrollX = 970')
    expect(source).toContain('@media (max-width: 1024px)')
    expect(source).toContain('.trace-filter-space :deep(.n-date-picker)')
    expect(source).toContain('width: 100% !important;')
  })

  it('keeps execution trace detail cards, code blocks, timeline, and drawer responsive', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/views/TraceDetail.vue'), 'utf8')

    expect(source).toContain('class="trace-detail-page"')
    expect(source).toContain('class="trace-summary-space"')
    expect(source).toContain('class="timeline-header-space"')
    expect(source).toContain('class="timeline-node-meta"')
    expect(source).toContain('class="code-scroll"')
    expect(source).toContain('class="trace-error-pre"')
    expect(source).toContain('class="trace-answer"')
    expect(source).toContain(':width="responsiveDrawerWidth"')
    expect(source).toContain('@media (max-width: 1024px)')
  })

  it('keeps workflow detail overview, graph, drawer, and history table responsive', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/views/WorkflowDetail.vue'), 'utf8')
    const graphSource = readFileSync(resolve(process.cwd(), 'src/components/WorkflowGraph.vue'), 'utf8')

    expect(source).toContain('class="workflow-detail-page"')
    expect(source).toContain('class="workflow-summary-space"')
    expect(source).toContain('class="table-scroll"')
    expect(source).toContain('scroll-x="max-content"')
    expect(source).toContain(':width="responsiveDrawerWidth"')
    expect(source).toContain('@media (max-width: 1024px)')
    expect(source).toContain('.workflow-summary-space :deep(.n-text)')

    expect(graphSource).toContain('min-width: 0;')
    expect(graphSource).toContain('.workflow-svg')
    expect(graphSource).toContain('.graph-legend')
    expect(graphSource).toContain('@media (max-width: 640px)')
  })
})
