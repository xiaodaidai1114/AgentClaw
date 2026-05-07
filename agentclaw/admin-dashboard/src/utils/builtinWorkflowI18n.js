const BUILTIN_WORKFLOW_ID = '__builtin__'

const BUILTIN_TEXT = {
  description: {
    'zh-CN': '你的全能 AI 助手，可以构建智能体、执行代码、读写文件、处理文档、调用 API',
    'en-US': 'Your all-purpose AI assistant for building agents, running code, reading and writing files, handling documents, and calling APIs.',
  },
  welcome: {
    'zh-CN': '你好！我是你的全能 AI 助手，可以构建智能体、执行代码、读写文件、处理文档、调用 API，你说什么我就做什么',
    'en-US': 'Hi! I am your all-purpose AI assistant. I can build agents, run code, read and write files, handle documents, and call APIs. Tell me what you need and I will get to work.',
  },
}

const BUILTIN_LEGACY_TEXT = {
  description: [
    '你的全能 AI 助手，可以构建智能体、搜索网页、执行代码、读写文件、调用 API',
    'Your all-purpose AI assistant for building agents, searching the web, running code, reading and writing files, and calling APIs.',
  ],
  welcome: [
    '你好！我是你的全能 AI 助手，可以构建智能体、搜索网页、执行代码、读写文件、调用 API，你说什么我就做什么',
    'Hi! I am your all-purpose AI assistant. I can build agents, search the web, run code, read and write files, and call APIs. Tell me what you need and I will get to work.',
  ],
}

const BUILTIN_INPUT_META = {
  user_input: {
    labelKey: 'builtinAgent.fields.userInput',
    descriptionKey: 'builtinAgent.inputs.userInput',
    descriptions: {
      'zh-CN': '发送给 AI 助手的消息',
      'en-US': 'Message to send to the AI assistant',
    },
  },
  model: {
    labelKey: 'builtinAgent.fields.model',
    descriptionKey: 'builtinAgent.inputs.model',
    descriptions: {
      'zh-CN': '指定使用的模型 ID（留空使用默认模型）',
      'en-US': 'Model ID to use for this run (leave empty to use the default model)',
    },
  },
}

const BUILTIN_NODE_META = {
  builtin_init: {
    key: 'builtinAgent.nodes.builtinInit',
    descriptions: {
      'zh-CN': '初始化智能体',
      'en-US': 'Initialize agent',
    },
  },
  smart_prefilter: {
    key: 'builtinAgent.nodes.smartPrefilter',
    descriptions: {
      'zh-CN': '正在智能筛选...',
      'en-US': 'Smart prefilter in progress...',
    },
  },
  agent: {
    key: 'builtinAgent.nodes.agent',
    descriptions: {
      'zh-CN': '智能体思考中...',
      'en-US': 'Agent is thinking...',
    },
  },
}

function isKnownBuiltinValue(value, localizedValues, aliases = []) {
  if (value == null || value === '') return true
  return Object.values(localizedValues).includes(value) || aliases.includes(value)
}

function localizeDefaultText(value, localizedValues, localeKey, t, aliases = []) {
  if (!isKnownBuiltinValue(value, localizedValues, aliases)) return value
  return t(localeKey)
}

function localizeInputSchema(inputSchema, t) {
  if (!inputSchema?.properties) return inputSchema

  const properties = Object.fromEntries(
    Object.entries(inputSchema.properties).map(([name, schema]) => {
      const meta = BUILTIN_INPUT_META[name]
      if (!meta) return [name, schema]
      return [name, { ...schema, description: t(meta.descriptionKey) }]
    }),
  )

  return { ...inputSchema, properties }
}

function localizeFormConfig(formConfig, t) {
  if (!Array.isArray(formConfig)) return formConfig

  return formConfig.map((field) => {
    const meta = BUILTIN_INPUT_META[field.name]
    if (!meta) return field
    return {
      ...field,
      label: t(meta.labelKey),
      description: t(meta.descriptionKey),
    }
  })
}

function localizeBuiltinNode(node, t) {
  if (!node) return node
  const meta = BUILTIN_NODE_META[node.id]
  if (!meta) return node

  return {
    ...node,
    description: localizeDefaultText(node.description, meta.descriptions, meta.key, t),
  }
}

function getBuiltinRuntimeNodeMeta(step) {
  if (!step) return null

  if (step.id && BUILTIN_NODE_META[step.id]) {
    return BUILTIN_NODE_META[step.id]
  }

  const knownValues = [step.name, step.title, step.description].filter(Boolean)
  if (knownValues.length === 0) return null

  return Object.values(BUILTIN_NODE_META).find((meta) =>
    knownValues.some((value) => Object.values(meta.descriptions).includes(value)),
  ) || null
}

export function isBuiltinWorkflowId(workflowId) {
  return workflowId === BUILTIN_WORKFLOW_ID
}

export function localizeBuiltinWorkflow(workflow, t) {
  if (!workflow || !isBuiltinWorkflowId(workflow.id) || typeof t !== 'function') return workflow

  const localizedWorkflow = {
    ...workflow,
    description: localizeDefaultText(workflow.description, BUILTIN_TEXT.description, 'builtinAgent.description', t, BUILTIN_LEGACY_TEXT.description),
    welcome: localizeDefaultText(workflow.welcome, BUILTIN_TEXT.welcome, 'builtinAgent.welcome', t, BUILTIN_LEGACY_TEXT.welcome),
  }

  if (workflow.input_schema) {
    localizedWorkflow.input_schema = localizeInputSchema(workflow.input_schema, t)
  }

  if (workflow.form_config) {
    localizedWorkflow.form_config = localizeFormConfig(workflow.form_config, t)
  }

  if (Array.isArray(workflow.nodes)) {
    localizedWorkflow.nodes = workflow.nodes.map((node) => localizeBuiltinNode(node, t))
  }

  return localizedWorkflow
}

export function localizeBuiltinWorkflowConfig(config, workflowId, t) {
  if (!config || !isBuiltinWorkflowId(workflowId) || typeof t !== 'function') return config

  return {
    ...config,
    description: localizeDefaultText(config.description, BUILTIN_TEXT.description, 'builtinAgent.description', t, BUILTIN_LEGACY_TEXT.description),
    welcome: localizeDefaultText(config.welcome, BUILTIN_TEXT.welcome, 'builtinAgent.welcome', t, BUILTIN_LEGACY_TEXT.welcome),
  }
}

export function localizeBuiltinNodeConfig(config, workflowId, nodeId, t) {
  if (!config || !isBuiltinWorkflowId(workflowId) || typeof t !== 'function') return config

  const meta = BUILTIN_NODE_META[nodeId]
  if (!meta) return config

  return {
    ...config,
    description: localizeDefaultText(config.description, meta.descriptions, meta.key, t),
  }
}

export function localizeBuiltinRuntimeStep(step, workflowId, t) {
  if (!step || !isBuiltinWorkflowId(workflowId) || typeof t !== 'function') return step

  const meta = getBuiltinRuntimeNodeMeta(step)
  if (!meta) return step

  const localizedStep = { ...step }

  if (typeof localizedStep.name === 'string') {
    localizedStep.name = localizeDefaultText(localizedStep.name, meta.descriptions, meta.key, t)
  }

  if (typeof localizedStep.title === 'string') {
    localizedStep.title = localizeDefaultText(localizedStep.title, meta.descriptions, meta.key, t)
  }

  if (typeof localizedStep.description === 'string') {
    localizedStep.description = localizeDefaultText(localizedStep.description, meta.descriptions, meta.key, t)
  }

  return localizedStep
}

export function localizeBuiltinRuntimeSteps(steps, workflowId, t) {
  if (!Array.isArray(steps)) return steps
  return steps.map((step) => localizeBuiltinRuntimeStep(step, workflowId, t))
}
