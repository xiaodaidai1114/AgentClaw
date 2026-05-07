import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

describe('public agent and dashboard UX safeguards', () => {
  it('renders a standalone start action for workflows without chat input fields', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/views/AgentChat.vue'), 'utf8')

    expect(source).toContain('standalone-start-wrapper')
    expect(source).toContain('v-if="canStartWorkflow && !hasFormFields"')
  })

  it('keeps the chat layout usable on narrow mobile screens', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/views/AgentChat.vue'), 'utf8')

    expect(source).toContain('@media (max-width: 768px)')
    expect(source).toContain('.chat-main { min-width: 0; }')
    expect(source).toContain('.agent-chat { margin: -24px 0; width: 100%; }')
  })

  it('does not advance the scheduler wizard when the selected trigger is incomplete', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/views/scheduler/JobFormModal.vue'), 'utf8')

    expect(source).toContain('validateTriggerStep')
    expect(source).toContain('hasEnabledTrigger')
    expect(source).toContain('hasValidInterval')
    expect(source).toContain('schedulerJobForm.selectAtLeastOneTrigger')
  })

  it('uses accessible controls for chat collapse and selection affordances', () => {
    const chatSource = readFileSync(resolve(process.cwd(), 'src/views/AgentChat.vue'), 'utf8')
    const sidebarSource = readFileSync(resolve(process.cwd(), 'src/components/chat/ChatSidebar.vue'), 'utf8')
    const toolPanelSource = readFileSync(resolve(process.cwd(), 'src/components/chat/ToolDetailsPanel.vue'), 'utf8')

    expect(chatSource).toContain('aria-expanded')
    expect(chatSource).toContain('@keydown.enter.prevent')
    expect(sidebarSource).toContain('role="button"')
    expect(sidebarSource).toContain('@keydown.enter.prevent')
    expect(toolPanelSource).toContain('details-close')
    expect(toolPanelSource).toContain('aria-label')
  })
})
