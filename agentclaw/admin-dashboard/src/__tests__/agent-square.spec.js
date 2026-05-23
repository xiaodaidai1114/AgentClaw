import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

describe('Template Library workflow separation', () => {
  it('adds a Template Library route and keeps Agent Square out of the UI', () => {
    const routerSource = readFileSync(resolve(process.cwd(), 'src/router/index.js'), 'utf8')
    const sidebarSource = readFileSync(resolve(process.cwd(), 'src/components/Sidebar.vue'), 'utf8')

    expect(routerSource).toContain("path: '/templates'")
    expect(routerSource).toContain("name: 'TemplateLibrary'")
    expect(routerSource).toContain("TemplateLibrary.vue")
    expect(sidebarSource).toContain("t('nav.templates')")
    expect(sidebarSource).toContain("key: '/templates'")
    expect(sidebarSource).toContain("path.startsWith('/templates')")
    expect(routerSource).not.toContain("path: '/agent-square'")
    expect(routerSource).not.toContain("name: 'AgentSquare'")
    expect(routerSource).not.toContain("AgentSquare.vue")
    expect(sidebarSource).not.toContain("t('nav.agentSquare')")
    expect(sidebarSource).not.toContain("key: '/agent-square'")
    expect(sidebarSource).not.toContain("path.startsWith('/agent-square')")
  })

  it('keeps unimported templates out of the workflow list', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/views/Workflows.vue'), 'utf8')

    expect(source).not.toContain('agentFilter')
    expect(source).not.toContain("value: 'agent_square'")
    expect(source).not.toContain('workflows.filterAgentSquare')
    expect(source).not.toContain("workflowsApi.list({ include_builtin: true })")
    expect(source).toContain("workflowsApi.list({ include_builtin: false })")
    expect(source).not.toContain('wf.agent_square_app_id')
  })

  it('imports templates and opens imported agents with the recommended input', () => {
    const templateSource = readFileSync(resolve(process.cwd(), 'src/views/TemplateLibrary.vue'), 'utf8')
    const chatSource = readFileSync(resolve(process.cwd(), 'src/views/AgentChat.vue'), 'utf8')

    expect(templateSource).toContain('templateLibraryApi.list')
    expect(templateSource).toContain('templateLibraryApi.importApp')
    expect(templateSource).toContain('openWorkflow(app)')
    expect(templateSource).toContain('seed_input')
    expect(templateSource).toContain('app.recommended_input')
    expect(templateSource).toContain('v-if="!app.registered"')
    expect(templateSource).not.toContain(':disabled="app.imported && !app.registered"')
    expect(chatSource).toContain('function getRouteSeedInput')
    expect(chatSource).toContain('} else if (seedInput) {')
    expect(chatSource).toContain('seedInput && !this.inputText && this.userInputFieldName')
    expect(chatSource).toContain('this.inputText = seedInput')
  })
})
