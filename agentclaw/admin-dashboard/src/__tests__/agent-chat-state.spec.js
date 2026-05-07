import { afterEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import AgentChat from '../views/AgentChat.vue'
import ChatMessage from '../components/chat/ChatMessage.vue'
import { clearAdminToken, setAdminToken } from '../api'
import { agentRunManager } from '../utils/agentRunManager'

describe('AgentChat conversation runtime state', () => {
  afterEach(() => {
    agentRunManager.clear()
  })

  it('resets token counters when switching or creating conversations', () => {
    const ctx = {
      streamingContent: 'old stream',
      reasoningContent: 'old reasoning',
      currentToolCalls: [{ id: 'tool' }],
      nodeSteps: [{ id: 'node' }],
      todoItems: [{ content: 'todo' }],
      currentPromptTokens: 123,
      currentCompletionTokens: 456,
      currentContextTokens: 20000,
      thinkingStatus: { text: 'thinking' },
      workflowStatus: 'finished',
      streamEndedByWorkflowEvent: true,
      currentTaskId: 'task-1',
    }

    AgentChat.methods.resetConversationRuntimeState.call(ctx)

    expect(ctx.currentPromptTokens).toBe(0)
    expect(ctx.currentCompletionTokens).toBe(0)
    expect(ctx.currentContextTokens).toBe(0)
    expect(ctx.streamingContent).toBe('')
    expect(ctx.reasoningContent).toBe('')
    expect(ctx.currentToolCalls).toEqual([])
    expect(ctx.nodeSteps).toEqual([])
    expect(ctx.todoItems).toEqual([])
    expect(ctx.workflowStatus).toBe('idle')
    expect(ctx.currentTaskId).toBe(null)
  })

  it('maps model permission level to tool confirmation request fields', () => {
    const ctx = {
      toolConfirmationLevel: 'medium',
    }

    const required = AgentChat.computed.toolConfirmationRequired.call(ctx)

    expect(required).toBe(true)
    expect(ctx.toolConfirmationLevel).toBe('medium')
  })

  it('marks running steps and tools as cancelled when aborting', () => {
    const ctx = {
      nodeSteps: [{
        id: 'agent',
        status: 'running',
        startTime: Date.now() - 1200,
        toolCalls: [{ id: 'tool-1', status: 'running' }],
        segments: [{ type: 'tool', id: 'tool-1', status: 'running' }],
      }],
      currentToolCalls: [{ id: 'tool-1', status: 'running' }],
      $t: (key) => key,
    }

    AgentChat.methods.markRunningStepsCancelled.call(ctx, 'cancelled')

    expect(ctx.nodeSteps[0].status).toBe('cancelled')
    expect(ctx.nodeSteps[0].toolCalls[0].status).toBe('failed')
    expect(ctx.nodeSteps[0].segments[0].status).toBe('failed')
    expect(ctx.currentToolCalls[0].status).toBe('failed')
  })


  it('archives intermediate streaming text into running step before tool display', () => {
    const ctx = {
      streamingContent: '我先检查项目结构。',
      nodeSteps: [{ id: 'agent', status: 'running', segments: [] }],
    }

    AgentChat.methods.archiveStreamingContentToStep.call(ctx, 'agent')

    expect(ctx.streamingContent).toBe('')
    expect(ctx.nodeSteps[0].segments).toEqual([{ type: 'assistant-note', content: '我先检查项目结构。' }])
  })

  it('auto-expands process details for the first process event in an empty conversation', () => {
    const ctx = {
      processCollapsed: true,
      messages: [{ role: 'user', content: 'hello' }],
      nodeSteps: [],
      reasoningContent: '',
    }

    AgentChat.methods.ensureProcessVisibleForFirstRun.call(ctx)

    expect(ctx.processCollapsed).toBe(false)
  })

  it('keeps input disabled while the conversation is initializing', () => {
    const ctx = {
      isInitializing: true,
      userInputFieldName: 'query',
      workflowStatus: 'idle',
    }

    const enabled = AgentChat.computed.inputEnabled.call(ctx)

    expect(enabled).toBe(false)
  })

  it('allows no-input workflows to show a standalone start action', () => {
    const ctx = {
      isInitializing: false,
      conversationId: 'conv-1',
      userInputFieldName: '',
      workflowStatus: 'idle',
    }

    expect(AgentChat.computed.canStartWorkflow.call(ctx)).toBe(true)
  })

  it('validates chat input before sending', async () => {
    const ctx = {
      inputText: '<script>alert(1)</script>',
      inputError: '',
      isStreaming: false,
      isInitializing: false,
      conversationId: 'conv-1',
      validateInput: AgentChat.methods.validateInput,
      $t: (key) => key,
    }

    await AgentChat.methods.sendMessage.call(ctx)

    expect(ctx.inputError).toBe('agentChat.inputContainsForbiddenChars')
  })

  it('does not abort an active workflow when the chat view unmounts', () => {
    const ctx = {
      inputErrorTimer: 123,
      abortRequest: vi.fn(),
    }

    AgentChat.beforeUnmount.call(ctx)

    expect(ctx.inputErrorTimer).toBe(null)
    expect(ctx.abortRequest).not.toHaveBeenCalled()
  })

  it('creates a new conversation during streaming by navigating without resetting the active run', async () => {
    const messages = [{ role: 'user', content: 'long running task' }]
    const ctx = {
      isStreaming: true,
      workflowLoadError: '',
      isPublicMode: false,
      currentWorkflowId: 'workflow-1',
      shareToken: '',
      conversationId: 'conv-running',
      conversations: [{ id: 'conv-running', title: 'Running', messages }],
      messages,
      convApi: {
        create: vi.fn(async () => ({ id: 'conv-new', title: 'New conversation', messages: [] })),
      },
      $route: { query: { conversation_id: 'conv-running' } },
      $router: { replace: vi.fn() },
      saveConversationsToLocal: vi.fn(),
      createConversationShell: AgentChat.methods.createConversationShell,
      navigateToConversation: AgentChat.methods.navigateToConversation,
      resetConversationRuntimeState: () => {
        throw new Error('active stream should not be reset')
      },
      $t: (key) => key,
    }

    await AgentChat.methods.newConversation.call(ctx)

    expect(ctx.convApi.create).toHaveBeenCalledWith('workflow-1', null, 'admin', '')
    expect(ctx.messages).toBe(messages)
    expect(ctx.conversations[0].id).toBe('conv-new')
    expect(ctx.$router.replace).toHaveBeenCalledWith({ query: { conversation_id: 'conv-new' } })
  })

  it('switches conversations during streaming by navigating without loading over the active run', async () => {
    const messages = [{ role: 'user', content: 'still running' }]
    const ctx = {
      isStreaming: true,
      conversationId: 'conv-running',
      messages,
      $route: { query: { conversation_id: 'conv-running' } },
      $router: { replace: vi.fn() },
      navigateToConversation: AgentChat.methods.navigateToConversation,
      resetConversationRuntimeState: () => {
        throw new Error('active stream should not be reset')
      },
    }

    await AgentChat.methods.loadConversation.call(ctx, 'conv-target')

    expect(ctx.messages).toBe(messages)
    expect(ctx.$router.replace).toHaveBeenCalledWith({ query: { conversation_id: 'conv-target' } })
  })

  it('merges conversation local cache so background runs do not overwrite each other', () => {
    localStorage.clear()
    localStorage.setItem('agent_conversations_workflow-1', JSON.stringify([
      { id: 'conv-other', title: 'Other fresh', messages: [{ role: 'assistant', content: 'fresh' }], updated_at: 300 },
    ]))
    const ctx = {
      isPublicMode: false,
      currentWorkflowId: 'workflow-1',
      conversationId: 'conv-running',
      conversations: [
        { id: 'conv-running', title: 'Running done', messages: [{ role: 'assistant', content: 'done' }], updated_at: 400 },
        { id: 'conv-other', title: 'Other stale', messages: [{ role: 'assistant', content: 'stale' }], updated_at: 100 },
      ],
    }

    AgentChat.methods.saveConversationsToLocal.call(ctx)

    const stored = JSON.parse(localStorage.getItem('agent_conversations_workflow-1'))
    expect(stored.find(item => item.id === 'conv-running').messages[0].content).toBe('done')
    expect(stored.find(item => item.id === 'conv-other').messages[0].content).toBe('fresh')
  })

  it('removes deleted conversations from local cache instead of merging them back', async () => {
    localStorage.clear()
    localStorage.setItem('agent_conversations_workflow-1', JSON.stringify([
      { id: 'conv-deleted', title: 'Deleted', messages: [], updated_at: 300 },
      { id: 'conv-keep', title: 'Keep', messages: [], updated_at: 200 },
    ]))
    const ctx = {
      isPublicMode: false,
      currentWorkflowId: 'workflow-1',
      shareToken: '',
      conversationId: 'conv-keep',
      deleteConversationDialog: { visible: true, conversationId: 'conv-deleted' },
      conversations: [
        { id: 'conv-deleted', title: 'Deleted', messages: [], updated_at: 300 },
        { id: 'conv-keep', title: 'Keep', messages: [], updated_at: 200 },
      ],
      convApi: { delete: vi.fn(async () => {}) },
      saveConversationsToLocal: AgentChat.methods.saveConversationsToLocal,
    }

    await AgentChat.methods.confirmDeleteConversation.call(ctx)

    const stored = JSON.parse(localStorage.getItem('agent_conversations_workflow-1'))
    expect(stored.map(item => item.id)).toEqual(['conv-keep'])
    expect(ctx.convApi.delete).toHaveBeenCalledWith('workflow-1', 'conv-deleted', '')
  })

  it('keeps conversations visible when remote deletion does not delete a row', async () => {
    localStorage.clear()
    localStorage.setItem('agent_conversations_workflow-1', JSON.stringify([
      { id: 'conv-still-remote', title: 'Remote', messages: [], updated_at: 300 },
      { id: 'conv-keep', title: 'Keep', messages: [], updated_at: 200 },
    ]))
    const ctx = {
      isPublicMode: false,
      currentWorkflowId: 'workflow-1',
      shareToken: '',
      conversationId: 'conv-keep',
      deleteConversationDialog: { visible: true, conversationId: 'conv-still-remote' },
      conversations: [
        { id: 'conv-still-remote', title: 'Remote', messages: [], updated_at: 300 },
        { id: 'conv-keep', title: 'Keep', messages: [], updated_at: 200 },
      ],
      convApi: { delete: vi.fn(async () => ({ success: false })) },
      saveConversationsToLocal: AgentChat.methods.saveConversationsToLocal,
      setTimedInputError: vi.fn(),
      $t: (key) => key,
    }

    await AgentChat.methods.confirmDeleteConversation.call(ctx)

    const stored = JSON.parse(localStorage.getItem('agent_conversations_workflow-1'))
    expect(stored.map(item => item.id)).toEqual(['conv-still-remote', 'conv-keep'])
    expect(ctx.conversations.map(item => item.id)).toEqual(['conv-still-remote', 'conv-keep'])
    expect(ctx.setTimedInputError).toHaveBeenCalledWith('agentChat.deleteConversationFailed')
  })

  it('keys chat routes by full path so conversation changes detach active runs into old instances', () => {
    const appSource = readFileSync(resolve(process.cwd(), 'src/App.vue'), 'utf8')

    expect(appSource).toContain(':key="routeViewKey"')
    expect(appSource).toContain('chatRouteNames')
    expect(appSource).toContain("'AgentChat'")
    expect(appSource).toContain("'BuiltinAgent'")
    expect(appSource).toContain("'PublicAgent'")
    expect(appSource).toContain('route.fullPath')
  })

  it('reattaches a remounted conversation view to an active background run', () => {
    const key = agentRunManager.makeKey({
      isPublicMode: false,
      workflowId: 'workflow-1',
      conversationId: 'conv-running',
    })
    agentRunManager.startRun(key, {
      abort: vi.fn(),
      snapshot: {
        conversationId: 'conv-running',
        isStreaming: true,
        workflowStatus: 'running',
        streamingContent: 'first chunk',
        reasoningContent: 'thinking',
        messages: [{ role: 'user', content: 'long task' }],
        nodeSteps: [{ id: 'agent', status: 'running' }],
        currentToolCalls: [],
        todoItems: [],
        thinkingStatus: { text: 'agentChat.thinking' },
        currentTaskId: 'task-1',
        streamEndedByWorkflowEvent: false,
        currentPromptTokens: 10,
        currentCompletionTokens: 2,
        currentContextTokens: 100,
        approvalMode: false,
      },
    })
    const ctx = {
      isPublicMode: false,
      currentWorkflowId: 'workflow-1',
      conversationId: 'conv-running',
      messages: [],
      streamingContent: '',
      reasoningContent: '',
      currentToolCalls: [],
      nodeSteps: [],
      todoItems: [],
      thinkingStatus: null,
      currentTaskId: null,
      workflowStatus: 'idle',
      streamEndedByWorkflowEvent: false,
      currentPromptTokens: 0,
      currentCompletionTokens: 0,
      currentContextTokens: 0,
      approvalMode: false,
      isStreaming: false,
      runUnsubscribe: null,
      activeRunKey: '',
      scrollToBottom: vi.fn(),
    }

    const attached = AgentChat.methods.attachActiveRun.call(ctx, 'conv-running')

    expect(attached).toBe(true)
    expect(ctx.isStreaming).toBe(true)
    expect(ctx.workflowStatus).toBe('running')
    expect(ctx.streamingContent).toBe('first chunk')
    expect(ctx.nodeSteps).toEqual([{ id: 'agent', status: 'running' }])

    agentRunManager.updateRun(key, {
      ...agentRunManager.getSnapshot(key),
      streamingContent: 'first chunk second chunk',
      currentCompletionTokens: 5,
    })

    expect(ctx.streamingContent).toBe('first chunk second chunk')
    expect(ctx.currentCompletionTokens).toBe(5)
  })

  it('lets a reattached conversation cancel the original background request', async () => {
    const abort = vi.fn(async () => {})
    const key = agentRunManager.makeKey({
      isPublicMode: false,
      workflowId: 'workflow-1',
      conversationId: 'conv-running',
    })
    agentRunManager.startRun(key, {
      abort,
      snapshot: {
        conversationId: 'conv-running',
        isStreaming: true,
        workflowStatus: 'running',
        messages: [{ role: 'user', content: 'long task' }],
      },
    })
    const ctx = {
      isPublicMode: false,
      currentWorkflowId: 'workflow-1',
      conversationId: 'conv-running',
      abortController: null,
      currentTaskId: null,
      workflowStatus: 'running',
      thinkingStatus: { text: 'running' },
      isStreaming: true,
      nodeSteps: [],
      currentToolCalls: [],
      $t: (key) => key,
      markRunningStepsCancelled: AgentChat.methods.markRunningStepsCancelled,
      publishRunSnapshot: vi.fn(),
    }

    await AgentChat.methods.abortRequest.call(ctx)

    expect(abort).toHaveBeenCalledOnce()
  })

  it('uses the anonymous public run endpoint without Authorization in public mode', async () => {
    const fetchCalls = []
    vi.stubGlobal('fetch', vi.fn(async (...args) => {
      fetchCalls.push(args)
      return {
        ok: true,
        body: {
          getReader: () => ({
            read: async () => ({ done: true }),
          }),
        },
      }
    }))

    const ctx = {
      isPublicMode: true,
      publicSessionReady: true,
      ensurePublicSession: vi.fn(async () => {}),
      formData: {},
      userInputFieldName: 'question',
      selectedModel: '',
      isBuiltin: false,
      preFilterEnabled: true,
      toolConfirmationRequired: false,
      toolConfirmationLevel: 'off',
      attachedFiles: [{ original_name: 'secret.txt', file_path: 'uploads/secret.txt', mime_type: 'text/plain', size: 12 }],
      currentWorkflowId: 'workflow-1',
      conversationId: 'conversation-1',
      abortController: null,
      streamEndedByWorkflowEvent: false,
      workflowStatus: 'finished',
      streamingContent: '',
      currentToolCalls: [],
      nodeSteps: [],
      reasoningContent: '',
      approvalMode: false,
      handleSseLine: () => {},
    }

    try {
      await AgentChat.methods.streamRequest.call(ctx, 'hello')
    } finally {
      vi.unstubAllGlobals()
    }

    const [url, options] = fetchCalls[0]
    expect(url).toBe('/api/public/workflows/workflow-1/run')
    expect(options.headers.Authorization).toBeUndefined()
    expect(options.headers['X-AgentClaw-Public-Session']).toBe('1')
    expect(options.credentials).toBe('same-origin')
    expect(ctx.ensurePublicSession).toHaveBeenCalledOnce()
    expect(JSON.parse(options.body)).toMatchObject({
      response_mode: 'streaming',
      conversation_id: 'conversation-1',
      inputs: { question: 'hello' },
      user: 'hello',
    })
    expect(JSON.parse(options.body).files).toBeUndefined()
  })

  it('keeps anonymous public conversation lists scoped to local storage', async () => {
    const remoteList = vi.fn(async () => {
      throw new Error('public list should not be called')
    })
    localStorage.clear()
    localStorage.setItem('public_conv_workflow-1', JSON.stringify([
      { id: 'conv-local', title: 'Local conversation', messages: [] },
    ]))
    const ctx = {
      isPublicMode: true,
      currentWorkflowId: 'workflow-1',
      conversations: [],
      convApi: { list: remoteList },
    }

    await AgentChat.methods.loadConversations.call(ctx)

    expect(remoteList).not.toHaveBeenCalled()
    expect(ctx.conversations).toEqual([
      { id: 'conv-local', title: 'Local conversation', messages: [] },
    ])
  })

  it('prompts for admin auth instead of calling protected upload status without a token', async () => {
    localStorage.clear()
    clearAdminToken()
    const authEvents = []
    window.addEventListener('admin-auth-required', () => authEvents.push('required'), { once: true })
    const fetchSpy = vi.fn(async () => {
      throw new Error('protected upload status should not be called without a token')
    })
    vi.stubGlobal('fetch', fetchSpy)

    const ctx = {
      isPublicMode: false,
      uploadAvailable: true,
    }

    try {
      await AgentChat.methods.checkUploadStatus.call(ctx)
    } finally {
      vi.unstubAllGlobals()
    }

    expect(fetchSpy).not.toHaveBeenCalled()
    expect(ctx.uploadAvailable).toBe(false)
    expect(authEvents).toEqual(['required'])
  })

  it('clears a stale admin token and prompts for login when model loading is unauthorized', async () => {
    setAdminToken('stale-token')
    const authEvents = []
    window.addEventListener('admin-auth-required', () => authEvents.push('required'), { once: true })
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: false,
      status: 401,
      text: async () => 'Unauthorized',
      json: async () => ({ code: 'UNAUTHORIZED' }),
    })))

    const ctx = {
      isPublicMode: false,
      models: [{ id: 'old-model' }],
      selectedModel: 'old-model',
    }

    try {
      await AgentChat.methods.loadModels.call(ctx)
    } finally {
      vi.unstubAllGlobals()
    }

    expect(localStorage.getItem('admin_token')).toBe(null)
    expect(authEvents).toEqual(['required'])
  })

  it('does not fetch unknown public conversations from the server', async () => {
    const remoteGet = vi.fn(async () => ({
      id: 'conv-remote',
      messages: [{ role: 'assistant', content: 'remote history' }],
    }))
    const ctx = {
      isPublicMode: true,
      isStreaming: false,
      conversationLoadSeq: 0,
      attachedFiles: ['file'],
      showAllMessages: true,
      messages: [{ role: 'user', content: 'local draft' }],
      nodeSteps: [],
      conversations: [],
      convApi: { get: remoteGet },
      resetConversationRuntimeState: AgentChat.methods.resetConversationRuntimeState,
    }

    await AgentChat.methods.loadConversation.call(ctx, 'conv-remote')

    expect(remoteGet).not.toHaveBeenCalled()
    expect(ctx.conversationId).toBeUndefined()
  })

  it('keeps a routed admin conversation id when the remote conversation is missing', async () => {
    const remoteGet = vi.fn(async () => {
      const error = new Error('Conversation not found')
      error.response = { status: 404 }
      throw error
    })
    const ctx = {
      isPublicMode: false,
      isStreaming: false,
      conversationLoadSeq: 0,
      attachedFiles: ['file'],
      showAllMessages: true,
      messages: [{ role: 'user', content: 'local draft' }],
      nodeSteps: [],
      conversations: [],
      currentWorkflowId: '__builtin__',
      workflowWelcome: '',
      convApi: { get: remoteGet },
      $route: { query: { conversation_id: 'conv-local' } },
      $router: { replace: vi.fn() },
      $t: (key) => key,
      resetConversationRuntimeState: AgentChat.methods.resetConversationRuntimeState,
      normalizeAssistantMessages: (messages) => messages,
      loadFeedbackFromDb: () => {},
      restoreInterruptState: () => {},
      scrollToBottom: () => {},
      saveConversationsToLocal: vi.fn(),
    }

    await AgentChat.methods.loadConversation.call(ctx, 'conv-local')

    expect(remoteGet).toHaveBeenCalledWith('__builtin__', 'conv-local', undefined)
    expect(ctx.conversationId).toBe('conv-local')
    expect(ctx.conversations[0]).toMatchObject({ id: 'conv-local', messages: [] })
    expect(ctx.saveConversationsToLocal).toHaveBeenCalled()
  })

  it('restores a stable conversation id before starting a workflow run', async () => {
    setAdminToken('admin-token')
    const fetchCalls = []
    vi.stubGlobal('fetch', vi.fn(async (...args) => {
      fetchCalls.push(args)
      return {
        ok: true,
        body: {
          getReader: () => ({
            read: async () => ({ done: true }),
          }),
        },
      }
    }))

    const ctx = {
      isPublicMode: false,
      formData: {},
      userInputFieldName: 'query',
      selectedModel: '',
      isBuiltin: false,
      preFilterEnabled: true,
      toolConfirmationRequired: false,
      toolConfirmationLevel: 'off',
      attachedFiles: [],
      currentWorkflowId: '__builtin__',
      conversationId: '',
      conversations: [],
      workflowWelcome: '',
      $route: { query: { conversation_id: 'conv-restored' } },
      $router: { replace: vi.fn() },
      $t: (key) => key,
      saveConversationsToLocal: vi.fn(),
      abortController: null,
      streamEndedByWorkflowEvent: false,
      workflowStatus: 'finished',
      streamingContent: '',
      currentToolCalls: [],
      nodeSteps: [],
      reasoningContent: '',
      approvalMode: false,
      handleSseLine: () => {},
      generateId: AgentChat.methods.generateId,
    }

    try {
      await AgentChat.methods.streamRequest.call(ctx, 'hello')
    } finally {
      vi.unstubAllGlobals()
    }

    expect(ctx.conversationId).toBe('conv-restored')
    expect(ctx.conversations[0]).toMatchObject({ id: 'conv-restored', messages: [] })
    expect(JSON.parse(fetchCalls[0][1].body)).toMatchObject({
      workflow_id: '__builtin__',
      conversation_id: 'conv-restored',
      inputs: { query: 'hello' },
    })
  })

  it('disables chat actions when the workflow failed to load', () => {
    const ctx = {
      workflowLoadError: 'Workflow missing',
      isInitializing: false,
      conversationId: 'conv-1',
      userInputFieldName: 'query',
      workflowStatus: 'idle',
      $t: (key) => key,
    }

    expect(AgentChat.computed.inputEnabled.call(ctx)).toBe(false)
    expect(AgentChat.computed.canStartWorkflow.call(ctx)).toBe(false)
    expect(AgentChat.computed.inputPlaceholder.call(ctx)).toBe('agentChat.workflowUnavailable')
  })

  it('does not let late conversation loads overwrite a running first stream', async () => {
    const ctx = {
      isStreaming: true,
      attachedFiles: ['file'],
      showAllMessages: true,
      messages: [{ role: 'user', content: 'first question' }],
      nodeSteps: [{ id: 'agent', status: 'running' }],
      conversations: [],
      currentWorkflowId: '__builtin__',
      convApi: {
        get: async () => ({
          id: 'conv-old',
          messages: [{ role: 'assistant', content: 'old message' }],
        }),
      },
      $route: { query: { conversation_id: 'conv-old' } },
      $router: { replace: () => {} },
      resetConversationRuntimeState: () => {
        throw new Error('must not reset active stream')
      },
      normalizeAssistantMessages: (messages) => messages,
      loadFeedbackFromDb: () => {},
      restoreInterruptState: () => {},
      scrollToBottom: () => {},
    }

    await AgentChat.methods.loadConversation.call(ctx, 'conv-old')

    expect(ctx.messages).toEqual([{ role: 'user', content: 'first question' }])
    expect(ctx.nodeSteps).toEqual([{ id: 'agent', status: 'running' }])
  })

  it('parses a final SSE data line without a trailing newline', () => {
    const events = []
    const ctx = {
      handleStreamEvent: (event) => events.push(event),
    }

    AgentChat.methods.handleSseLine.call(ctx, 'data: {"event":"node_started","data":{"node_id":"agent"}}')

    expect(events).toEqual([{ event: 'node_started', data: { node_id: 'agent' } }])
  })

  it('flushes the stream decoder before parsing the final SSE event', async () => {
    setAdminToken('admin-token')
    const events = []
    const finalEvent = 'data: {"event":"message","data":{"content":"完成"}}'

    class DeferredTextDecoder {
      constructor() {
        this.buffer = ''
      }

      decode(value, options) {
        if (value && options?.stream) {
          this.buffer += finalEvent
          return ''
        }
        const output = this.buffer
        this.buffer = ''
        return output
      }
    }

    vi.stubGlobal('TextDecoder', DeferredTextDecoder)
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true,
      body: {
        getReader: () => {
          let reads = 0
          return {
            read: async () => {
              reads += 1
              if (reads === 1) return { done: false, value: new Uint8Array([1]) }
              return { done: true }
            },
          }
        },
      },
    })))

    const ctx = {
      isPublicMode: false,
      formData: {},
      userInputFieldName: 'query',
      selectedModel: '',
      isBuiltin: false,
      preFilterEnabled: true,
      toolConfirmationRequired: false,
      toolConfirmationLevel: 'off',
      attachedFiles: [],
      currentWorkflowId: 'workflow-1',
      conversationId: 'conversation-1',
      abortController: null,
      streamEndedByWorkflowEvent: false,
      workflowStatus: 'finished',
      streamingContent: '',
      currentToolCalls: [],
      nodeSteps: [],
      reasoningContent: '',
      approvalMode: false,
      handleSseLine: (line) => AgentChat.methods.handleSseLine.call(ctx, line),
      handleStreamEvent: (event) => events.push(event),
      $t: (key) => key,
    }

    try {
      await AgentChat.methods.streamRequest.call(ctx, null)
    } finally {
      vi.unstubAllGlobals()
    }

    expect(events).toEqual([{ event: 'message', data: { content: '完成' } }])
  })

  it('keeps the user collapse preference when process history already exists', () => {
    const ctx = {
      processCollapsed: true,
      messages: [{ role: 'assistant', content: 'done', nodeSteps: [{ id: 'agent' }] }],
      nodeSteps: [],
      reasoningContent: '',
    }

    AgentChat.methods.ensureProcessVisibleForFirstRun.call(ctx)

    expect(ctx.processCollapsed).toBe(true)
  })


  it('marks a node as failed when model call fails', () => {
    const ctx = {
      nodeSteps: [{ id: 'agent', status: 'running', startTime: Date.now() - 500 }],
    }

    AgentChat.methods.markNodeStepFailed.call(ctx, 'agent', 'model timeout')

    expect(ctx.nodeSteps[0].status).toBe('failed')
    expect(ctx.nodeSteps[0].error).toBe('model timeout')
  })

  it('keeps the next pending confirmation visible after resolving the previous one', async () => {
    setAdminToken('admin-token')
    const pendingFetches = []
    const originalFetch = global.fetch
    global.fetch = (...args) => new Promise(resolve => pendingFetches.push({ args, resolve }))

    const ctx = {
      confirmDialog: { visible: false, submitting: false, confirmId: '', action: '', description: '', requireSudo: false, sudoPassword: '' },
      confirmQueue: [],
      thinkingStatus: {},
      $t: (key, params) => params?.action ? `${key}:${params.action}` : key,
    }
    ctx.showConfirmDialog = AgentChat.methods.showConfirmDialog.bind(ctx)
    ctx.showNextConfirmDialog = AgentChat.methods.showNextConfirmDialog.bind(ctx)

    AgentChat.methods.handleConfirmRequest.call(ctx, { confirm_id: 'first', action: 'first', description: '', require_sudo: false })
    const submitPromise = AgentChat.methods.submitConfirmDialog.call(ctx, true)
    AgentChat.methods.handleConfirmRequest.call(ctx, { confirm_id: 'second', action: 'second', description: '', require_sudo: false })

    pendingFetches[0].resolve({ ok: true, json: async () => ({ success: true }) })
    await submitPromise
    global.fetch = originalFetch

    expect(pendingFetches[0].args[0]).toContain('/api/confirm/first')
    expect(ctx.confirmDialog.visible).toBe(true)
    expect(ctx.confirmDialog.confirmId).toBe('second')
  })

  it('shows model retry status without ending the workflow', () => {
    const ctx = {
      nodeSteps: [{ id: 'agent', status: 'running' }],
      thinkingStatus: null,
      workflowStatus: 'running',
      $t: (key, params) => {
        if (key === 'agentChat.modelRetryingWithReason') return `retry ${params.attempt}/${params.max}: ${params.reason}`
        if (key === 'agentChat.modelRetrying') return `retry ${params.attempt}/${params.max}`
        return key
      },
      scrollToBottom: () => {},
    }

    AgentChat.methods.handleStreamEvent.call(ctx, {
      event: 'model_retry',
      data: { node_id: 'agent', attempt: 1, max_attempts: 3, error: 'post-tool response was not valid JSON' },
    })

    expect(ctx.thinkingStatus.text).toBe('retry 1/3: post-tool response was not valid JSON')
    expect(ctx.workflowStatus).toBe('running')
    expect(ctx.nodeSteps[0].warning).toBe('retry 1/3: post-tool response was not valid JSON')
  })

  it('keeps an empty post-tool separator without showing feedback', () => {
    const step = {
      segments: [
        { type: 'tool', id: 'a', name: 'read_file' },
        { type: 'tool-separator', content: '' },
        { type: 'tool', id: 'b', name: 'read_file' },
      ],
    }

    const segments = ChatMessage.methods.getDisplaySegments(step)

    expect(segments).toHaveLength(3)
    expect(segments[0].tools).toHaveLength(1)
    expect(segments[1].type).toBe('tool-separator')
    expect(segments[2].tools).toHaveLength(1)
  })


})
