import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'


describe('ChatInput HumanNode action layout', () => {
  it('renders input action buttons above the input container', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/components/chat/ChatInput.vue'), 'utf8')
    const template = source.match(/<template>([\s\S]*?)<\/template>/)?.[1] || ''
    const actionsIndex = template.indexOf('class="input-actions"')
    const containerIndex = template.indexOf('class="input-container"')
    const actionsStyle = source.match(/\.input-actions\s*\{([\s\S]*?)\}/)?.[1] || ''

    expect(actionsIndex).toBeGreaterThan(-1)
    expect(containerIndex).toBeGreaterThan(-1)
    expect(actionsIndex).toBeLessThan(containerIndex)
    expect(actionsStyle).toContain('justify-content: flex-start')
  })
})

describe('AgentChat workflow start layout', () => {
  it('keeps the form-only workflow start action outside the collapsible form body', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/views/AgentChat.vue'), 'utf8')
    const template = source.match(/<template>([\s\S]*?)<\/template>/)?.[1] || ''
    const bodyStart = template.indexOf('class="config-body"')
    const formStartTagIndex = template.indexOf('<div v-if="workflowStartHint"')
    const formStartIndex = template.indexOf('class="form-start-bar"', formStartTagIndex)

    expect(bodyStart).toBeGreaterThan(-1)
    expect(formStartTagIndex).toBeGreaterThan(bodyStart)
    expect(formStartIndex).toBeGreaterThan(formStartTagIndex)
    expect(template.slice(bodyStart, formStartTagIndex)).not.toContain('class="btn-start"')
  })

  it('gives the workflow start button a non-transparent fallback background', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/views/AgentChat.vue'), 'utf8')
    const buttonStyle = source.match(/\.btn-start\s*\{([\s\S]*?)\}/)?.[1] || ''
    const hoverStyle = source.match(/\.btn-start:hover\s*\{([\s\S]*?)\}/)?.[1] || ''

    expect(buttonStyle).toContain('background: var(--primary-color, #18181b)')
    expect(hoverStyle).toContain('background: var(--primary-hover, #000000)')
  })
})
