import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

describe('builtin agent settings UX', () => {
  it('hides the workflow back action for the builtin agent page', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/views/AgentChat.vue'), 'utf8')

    expect(source).toContain('!infoPanelCollapsed && !isBuiltin')
    expect(source).toContain('agentChat.backToWorkflow')
  })

  it('exposes only supported builtin agent model and memory settings', () => {
    const settingsSource = readFileSync(resolve(process.cwd(), 'src/views/Settings.vue'), 'utf8')
    const apiSource = readFileSync(resolve(process.cwd(), 'src/api/index.js'), 'utf8')
    const zh = readFileSync(resolve(process.cwd(), 'src/locales/zh-CN.js'), 'utf8')
    const en = readFileSync(resolve(process.cwd(), 'src/locales/en-US.js'), 'utf8')

    expect(settingsSource).toContain('name="builtinAgent"')
    expect(settingsSource).toContain('fetchBuiltinAgentConfig')
    expect(settingsSource).toContain('builtinNodeForm.temperature')
    expect(settingsSource).toContain('builtinNodeForm.top_p')
    expect(settingsSource).toContain('builtinNodeForm.fallback_model_id')
    expect(settingsSource).toContain('builtinNodeForm.auto_fallback')
    expect(settingsSource).toContain('builtinNodeForm.fallback_threshold')
    expect(settingsSource).toContain('builtinWorkflowForm.memory_content')
    expect(settingsSource).toContain('resetBuiltinNodeField')
    expect(settingsSource).toContain('resetBuiltinWorkflowField')
    expect(settingsSource).not.toContain('settingsApi.resetNodeField')
    expect(settingsSource).not.toContain('settingsApi.resetWorkflowField')
    expect(apiSource).toContain('resetWorkflowField')
    expect(apiSource).toContain('resetNodeField')
    expect(zh).toContain('builtinAgent')
    expect(en).toContain('builtinAgent')
  })

  it('uses icon-only reset buttons for builtin agent settings', () => {
    const settingsSource = readFileSync(resolve(process.cwd(), 'src/views/Settings.vue'), 'utf8')

    expect(settingsSource).toContain('class="reset-icon-button"')
    expect(settingsSource).toContain('aria-hidden="true">↺</span>')
    expect(settingsSource).not.toContain("{{ t('settings.builtinAgent.resetField') }}</n-button>")
  })

  it('removes unsupported builtin agent controls and keeps reset pending-save', () => {
    const settingsSource = readFileSync(resolve(process.cwd(), 'src/views/Settings.vue'), 'utf8')
    const zh = readFileSync(resolve(process.cwd(), 'src/locales/zh-CN.js'), 'utf8')
    const en = readFileSync(resolve(process.cwd(), 'src/locales/en-US.js'), 'utf8')

    for (const forbidden of [
      'builtinNodeForm.model_id',
      'builtinNodeForm.use_fast_model',
      'builtinNodeForm.max_tokens',
      'builtinNodeForm.stream',
      'builtinNodeForm.output_format',
      'builtinNodeForm.enable_memory',
      'builtinNodeForm.use_context',
      'builtinNodeForm.save_to_context',
      'builtinNodeForm.max_context_messages',
      'builtinNodeForm.enable_compression',
      'builtinNodeForm.compression_threshold',
      'builtinNodeForm.compression_model',
      'builtinNodeForm.inject_files',
    ]) {
      expect(settingsSource).not.toContain(forbidden)
    }

    expect(settingsSource).not.toContain('@click="fetchBuiltinAgentConfig">{{ t(\'common.refresh\') }}</n-button>')
    expect(settingsSource).not.toContain('settings.builtinAgent.saveNode')
    expect(settingsSource).toContain('BUILTIN_NODE_DEFAULTS')
    expect(settingsSource).toContain('builtinNodeChanged.value = true')
    expect(settingsSource).toContain('fieldResetPending')
    expect(zh).not.toContain('Temperature 与 Top P 默认保持未设置')
    expect(en).not.toContain('Temperature and Top P stay unset')
  })

  it('uses the 40000 character default limit for workflow memory counters', () => {
    const settingsSource = readFileSync(resolve(process.cwd(), 'src/views/Settings.vue'), 'utf8')
    const workflowConfigSource = readFileSync(resolve(process.cwd(), 'src/views/WorkflowConfig.vue'), 'utf8')

    expect(settingsSource).toContain('const builtinMemoryLimit = 40000')
    expect(workflowConfigSource).toContain('max: 40000')
    expect(settingsSource).not.toContain('const builtinMemoryLimit = 20000')
    expect(workflowConfigSource).not.toContain('max: 20000')
  })
})
