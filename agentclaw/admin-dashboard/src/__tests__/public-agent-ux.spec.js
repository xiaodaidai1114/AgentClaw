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
    const inputSource = readFileSync(resolve(process.cwd(), 'src/components/chat/ChatInput.vue'), 'utf8')
    const sidebarSource = readFileSync(resolve(process.cwd(), 'src/components/chat/ChatSidebar.vue'), 'utf8')
    const appSource = readFileSync(resolve(process.cwd(), 'src/App.vue'), 'utf8')
    const globalSource = readFileSync(resolve(process.cwd(), 'src/styles/global.css'), 'utf8')

    expect(source).toContain('@media (max-width: 1024px)')
    expect(source).toContain('.chat-main { min-width: 0; }')
    expect(source).toContain('.chat-main { flex: 1; min-width: 0;')
    expect(source).toContain('overflow-x: hidden;')
    expect(source).toContain('mobile-chat-header')
    expect(source).toContain('mobile-conversation-toggle')
    expect(source).toContain('mobile-config-toggle')
    expect(source).toContain('mobile-sidebar-overlay')
    expect(source).toContain('mobile-config-open')
    expect(source).toContain('height: 100dvh;')
    expect(source).not.toContain('.chat-sidebar { display: none; }')
    expect(appSource).toContain('mobile-main-nav-toggle')
    expect(appSource).toContain('mobile-main-sidebar-overlay')
    expect(globalSource).toContain('@media (max-width: 1024px)')
    expect(globalSource).toContain('margin-left: 0;')
    expect(inputSource).toContain('env(safe-area-inset-bottom)')
    expect(inputSource).toContain('@media (max-width: 1024px)')
    expect(sidebarSource).toContain('@media (hover: none)')
  })

  it('prevents chat content from overflowing narrow screens', () => {
    const messageSource = readFileSync(resolve(process.cwd(), 'src/components/chat/ChatMessage.vue'), 'utf8')
    const streamingSource = readFileSync(resolve(process.cwd(), 'src/components/chat/StreamingMessage.vue'), 'utf8')
    const inputSource = readFileSync(resolve(process.cwd(), 'src/components/chat/ChatInput.vue'), 'utf8')

    expect(messageSource).toContain('.message-wrapper { width: 100%; min-width: 0;')
    expect(messageSource).toContain('.message { width: 100%; min-width: 0;')
    expect(messageSource).toContain('.message-content { min-width: 0;')
    expect(messageSource).toContain('@media (max-width: 1024px)')
    expect(messageSource).toContain('.message-wrapper { padding: 0 12px; }')
    expect(messageSource).toContain('.tool-args-summary')
    expect(messageSource).toContain('max-width: min(180px, 44vw);')

    expect(streamingSource).toContain('.message-wrapper { width: 100%; min-width: 0;')
    expect(streamingSource).toContain('.message { width: 100%; min-width: 0;')
    expect(streamingSource).toContain('.message-content { min-width: 0;')
    expect(streamingSource).toContain('@media (max-width: 1024px)')
    expect(streamingSource).toContain('.message-wrapper { padding: 0 12px; }')
    expect(streamingSource).toContain('.tool-args-summary')
    expect(streamingSource).toContain('max-width: min(180px, 44vw);')

    expect(inputSource).toContain('.input-wrapper {')
    expect(inputSource).toContain('min-width: 0;')
    expect(inputSource).toContain('.toolbar-left,')
    expect(inputSource).toContain('.toolbar-right { min-width: 0;')
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
    expect(chatSource).toContain('mobile-header-actions')
    expect(chatSource).toContain('mobile-model-toggle')
    expect(chatSource).toContain('mobile-model-dropdown')
    expect(sidebarSource).toContain('role="button"')
    expect(sidebarSource).toContain('@keydown.enter.prevent')
    expect(toolPanelSource).toContain('details-close')
    expect(toolPanelSource).toContain('aria-label')
  })

  it('shows recent conversations on public shared agent pages without exposing admin panels', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/views/AgentChat.vue'), 'utf8')

    expect(source).toContain('<ChatSidebar')
    expect(source).not.toContain('<ChatSidebar v-if="!isPublicMode"')
    expect(source).toContain('<div v-if="!isPublicMode" class="info-panel"')
  })

  it('keeps public shared agent chat within the viewport', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/views/AgentChat.vue'), 'utf8')

    expect(source).toContain("'public-chat': isPublicMode")
    expect(source).toContain('.agent-chat.public-chat {')
    expect(source).toContain('margin: 0;')
    expect(source).toContain('width: 100%;')
    expect(source).toContain('height: 100vh;')
    expect(source).toContain('height: 100dvh;')
  })
})
