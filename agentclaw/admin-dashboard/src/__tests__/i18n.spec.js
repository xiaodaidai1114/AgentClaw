import { beforeEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

describe('i18n bootstrap', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('defaults to English when browser language starts with en', async () => {
    vi.stubGlobal('navigator', { language: 'en-US' })
    const { createAppI18n, DEFAULT_LOCALE_KEY } = await import('../i18n/index.js')
    const i18n = createAppI18n()
    expect(i18n.global.locale.value).toBe('en-US')
    expect(DEFAULT_LOCALE_KEY).toBe('agentclaw.admin.locale')
  })

  it('persists locale changes to localStorage', async () => {
    vi.stubGlobal('navigator', { language: 'zh-CN' })
    const { createAppI18n, setLocale } = await import('../i18n/index.js')
    const i18n = createAppI18n()
    setLocale(i18n, 'en-US')
    expect(i18n.global.locale.value).toBe('en-US')
    expect(localStorage.getItem('agentclaw.admin.locale')).toBe('en-US')
  })

  it('precompiles locale strings into message functions so strict CSP does not need unsafe-eval', async () => {
    vi.stubGlobal('navigator', { language: 'zh-CN' })
    const { createAppI18n } = await import('../i18n/index.js')
    const i18n = createAppI18n()

    expect(typeof i18n.global.getLocaleMessage('zh-CN').common.save).toBe('function')
    expect(i18n.global.t('common.totalItems', { count: 3 })).toBe('共 3 条')
    expect(i18n.global.t('agentChat.permissionHint.high')).toBe('低/中风险工具可自动执行，写文件、安装包、sudo 等高风险工具会先请求确认。')
  })

  it('updates locale when called with the composer that useI18n returns', async () => {
    vi.stubGlobal('navigator', { language: 'zh-CN' })
    const { createAppI18n, setLocale } = await import('../i18n/index.js')
    const i18n = createAppI18n()

    setLocale(i18n.global, 'en-US')

    expect(i18n.global.locale.value).toBe('en-US')
    expect(localStorage.getItem('agentclaw.admin.locale')).toBe('en-US')
    expect(document.documentElement.lang).toBe('en-US')
  })

  it('renders the locale switch in settings instead of the app shell', () => {
    const appSource = readFileSync(resolve(process.cwd(), 'src/App.vue'), 'utf8')
    const settingsSource = readFileSync(resolve(process.cwd(), 'src/views/Settings.vue'), 'utf8')

    expect(appSource).not.toContain('<LocaleSwitch')
    expect(settingsSource).toContain('<LocaleSwitch')
  })

  it('binds Naive UI locale to the current i18n locale instead of hardcoding zh-CN', () => {
    const appSource = readFileSync(resolve(process.cwd(), 'src/App.vue'), 'utf8')

    expect(appSource).toContain(':locale="naiveLocale"')
    expect(appSource).toContain(':date-locale="naiveDateLocale"')
    expect(appSource).toContain("const { locale } = useI18n()")
    expect(appSource).not.toContain(':locale="zhCN"')
    expect(appSource).not.toContain(':date-locale="dateZhCN"')
  })

  it('does not leave hardcoded Chinese knowledge-base UI copy in the list page', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/views/KnowledgeBases.vue'), 'utf8')

    expect(source).not.toContain('>文档<')
    expect(source).not.toContain('>分块<')
    expect(source).not.toContain('请输入知识库名称')
    expect(source).not.toContain('请先填写知识库名称')
    expect(source).not.toContain('知识库列表加载失败')
  })

  it('localizes builtin workflow metadata and node descriptions for English', async () => {
    vi.stubGlobal('navigator', { language: 'zh-CN' })
    const { createAppI18n, setLocale } = await import('../i18n/index.js')
    const {
      localizeBuiltinRuntimeStep,
      localizeBuiltinWorkflow,
      localizeBuiltinNodeConfig,
    } = await import('../utils/builtinWorkflowI18n.js')
    const AgentChat = (await import('../views/AgentChat.vue')).default

    const i18n = createAppI18n()
    setLocale(i18n, 'en-US')

    const localizedWorkflow = localizeBuiltinWorkflow({
      id: '__builtin__',
      description: '你的全能 AI 助手，可以构建智能体、搜索网页、执行代码、读写文件、调用 API',
      welcome: '你好！我是你的全能 AI 助手，可以构建智能体、搜索网页、执行代码、读写文件、调用 API，你说什么我就做什么',
      input_schema: {
        properties: {
          user_input: { description: '发送给 AI 助手的消息' },
          model: { description: '指定使用的模型 ID（留空使用默认模型）' },
        },
      },
    }, i18n.global.t)

    expect(localizedWorkflow.description).toBe('Your all-purpose AI assistant for building agents, running code, reading and writing files, handling documents, and calling APIs.')
    expect(localizedWorkflow.welcome).toBe('Hi! I am your all-purpose AI assistant. I can build agents, run code, read and write files, handle documents, and call APIs. Tell me what you need and I will get to work.')
    expect(localizedWorkflow.input_schema.properties.user_input.description).toBe('Message to send to the AI assistant')
    expect(localizedWorkflow.input_schema.properties.model.description).toBe('Model ID to use for this run (leave empty to use the default model)')

    const localizedNode = localizeBuiltinNodeConfig(
      { description: '初始化智能体' },
      '__builtin__',
      'builtin_init',
      i18n.global.t,
    )

    expect(localizedNode.description).toBe('Initialize agent')

    const localizedRuntimeStep = localizeBuiltinRuntimeStep(
      { id: 'unknown-node', name: '智能体思考中...' },
      '__builtin__',
      i18n.global.t,
    )

    expect(localizedRuntimeStep.name).toBe('Agent is thinking...')

    const runtimeContext = {
      nodeSteps: [],
      thinkingStatus: null,
      currentWorkflowId: '__builtin__',
      scrollToBottom: vi.fn(),
      ensureProcessVisibleForFirstRun: vi.fn(),
      getNodeTypeLabel: () => 'Agent',
      $t: i18n.global.t.bind(i18n.global),
    }

    runtimeContext.localizeNodeStep = AgentChat.methods.localizeNodeStep.bind(runtimeContext)

    AgentChat.methods.handleStreamEvent.call(runtimeContext, {
      event: 'node_started',
      data: {
        node_id: 'builtin_init',
        node_type: 'agent',
        title: '初始化智能体',
      },
    })

    expect(runtimeContext.nodeSteps).toHaveLength(1)
    expect(runtimeContext.nodeSteps[0].name).toBe('Initialize agent')
  })
})
