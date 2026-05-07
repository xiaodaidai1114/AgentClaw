<template>
  <div class="workflow-debug">
    <!-- Header -->
    <div class="debug-header">
      <div class="header-top">
        <div class="header-left">
          <button class="btn-back" @click="goBack">← {{ $t('workflowDebug.back') }}</button>
        </div>
        <div class="header-center">
          <h1>🐛 {{ $t('workflowDebug.title') }}: {{ workflowName }}</h1>
          <span class="workflow-id">{{ $t('workflowDebug.workflowId') }}: {{ workflowId }}</span>
        </div>
        <div class="header-info">
          <div class="info-row">
            <span class="info-label">{{ $t('workflowDebug.conversationId') }}:</span>
            <span class="info-value">{{ session?.thread_id || threadId || '-' }}</span>
          </div>
          <div class="info-row">
            <span class="info-label">{{ $t('workflowDebug.executed') }}:</span>
            <span class="info-value">{{ $t('workflowDebug.executedNodes', { executed: executedCount, total: nodes.length }) }}</span>
          </div>
          <div class="info-row">
            <span class="info-label">{{ $t('workflowDebug.totalTime') }}:</span>
            <span class="info-value">{{ totalTime }}</span>
          </div>
        </div>
      </div>

      <!-- Control Panel -->
      <div class="control-panel">
        <div class="control-item">
          <label>{{ $t('workflowDebug.status') }}:</label>
          <span :class="['status-badge', statusClass]">{{ statusText }}</span>
        </div>

        <div class="control-item">
          <label>{{ $t('workflowDebug.current') }}:</label>
          <span class="current-node">{{ session?.current_node || '-' }}</span>
          <span v-if="currentNodeType" class="node-type-badge" :class="currentNodeType">
            {{ currentNodeType.toUpperCase() }}
          </span>
        </div>

        <div class="control-actions">
          <button @click="startDebug" class="btn-success" :disabled="loading || isRunning">
            ▶ {{ $t('workflowDebug.start') }}
          </button>
          <template v-if="session">
            <button @click="resume" class="btn-primary" :disabled="loading || !isPaused">
              {{ $t('workflowDebug.resume') }}
            </button>
            <button @click="step" class="btn-primary" :disabled="loading || !isPaused">
              {{ $t('workflowDebug.step') }}
            </button>
            <button @click="stop" class="btn-danger" :disabled="loading || isStopped">
              {{ $t('workflowDebug.stop') }}
            </button>
          </template>
        </div>
      </div>
    </div>

    <div v-if="notice" class="debug-notice" :class="notice.type">
      <span>{{ notice.message }}</span>
      <button type="button" @click="notice = null">×</button>
    </div>

    <!-- Human Node Alert -->
    <div v-if="isHumanNode" class="human-alert">
      <div class="human-alert-icon">👤</div>
        <div class="human-alert-content">
          <div class="human-alert-title">🔴 {{ $t('workflowDebug.humanBreakpointTitle') }}</div>
          <div class="human-alert-message">
          {{ $t('workflowDebug.humanPausedAt') }}：<strong>{{ session?.current_node }}</strong><br>
          <span class="human-hint">{{ $t('workflowDebug.humanBreakpointHint') }}</span>
        </div>
      </div>
      <div class="human-alert-actions">
        <button class="btn-success" @click="showHumanInputModal">📝 {{ $t('workflowDebug.submitAndContinue') }}</button>
      </div>
    </div>

    <!-- Main Content - 3 columns -->
    <div class="debug-content">
      <!-- Left: Nodes List + History -->
      <div class="left-panels">
        <!-- Nodes List -->
        <div class="debug-panel nodes-panel">
          <div class="panel-header">
            <h3>📋 {{ $t('workflowDebug.nodeList') }}</h3>
            <button class="btn-text" @click="clearAllBreakpoints">{{ $t('workflowDebug.clearBreakpoints') }}</button>
          </div>
          <div class="nodes-list">
            <div
              v-for="node in displayNodes"
              :key="node.id"
              :class="['node-card', {
                'has-breakpoint': hasBreakpoint(node.id),
                'current': session?.current_node === node.id,
                'executed': isNodeExecuted(node.id),
                'parallel': node.type === 'parallel',
                'human': node.type === 'human'
              }]"
              :style="node.indent ? { marginLeft: '20px', opacity: 0.7 } : {}"
              @click="selectNode(node)"
            >
              <div class="node-header">
                <div class="node-left">
                  <input
                    type="checkbox"
                    class="breakpoint-checkbox"
                    :checked="hasBreakpoint(node.id)"
                    :disabled="node.disabled || isRunning"
                    @change.stop="toggleBreakpoint(node.id)"
                  />
                  <span class="node-name">{{ node.indent ? '↳ ' : '' }}{{ node.id }}</span>
                </div>
                <span class="node-type" :class="node.type">{{ getNodeTypeLabel(node.type) }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- History -->
        <div class="debug-panel history-panel">
          <div class="panel-header">
            <h3>📜 {{ $t('workflowDebug.history') }}</h3>
          </div>
          <div v-if="!session || !history.length" class="empty-state">
            {{ $t('workflowDebug.noHistory') }}
          </div>
          <div v-else class="history-list">
            <div
              v-for="(item, index) in history"
              :key="index"
              :class="['history-item', item.type]"
            >
              <div class="history-header">
                <span class="history-action">{{ item.action }}</span>
                <span class="history-time">{{ formatTime(item.timestamp) }}</span>
              </div>
              <div v-if="item.detail" class="history-detail">{{ item.detail }}</div>
            </div>
          </div>
        </div>
      </div>

      <!-- Center: Graph + State -->
      <div class="center-panels">
        <!-- Workflow Graph -->
        <div class="debug-panel graph-panel">
          <div class="panel-header">
            <h3>🔄 {{ $t('workflowDebug.graph') }}</h3>
            <div class="legend-inline">
              <span style="color: #1976d2;">●</span> {{ $t('workflowDebug.legend.current') }}
              <span style="margin-left: 10px; opacity: 0.5;">●</span> {{ $t('workflowDebug.legend.executed') }}
              <span style="margin-left: 10px; color: #f57c00;">●</span> {{ $t('workflowDebug.legend.breakpoint') }}
            </div>
          </div>
          <div class="graph-container">
            <WorkflowGraph
              v-if="nodes.length > 0"
              :nodes="graphNodes"
              :edges="edges"
              :current-node="session?.current_node"
              :executed-nodes="executedNodes"
              :breakpoints="breakpointNodes"
              @node-click="handleNodeClick"
            />
          </div>
        </div>

        <!-- State Panel -->
        <div class="debug-panel state-panel">
        <div class="state-tabs">
          <button :class="['tab', { active: activeTab === 'state' }]" @click="activeTab = 'state'">
              {{ $t('workflowDebug.state') }}
          </button>
            <button :class="['tab', { active: activeTab === 'result' }]" @click="activeTab = 'result'">
              {{ $t('workflowDebug.result') }}
            </button>
          </div>

          <div v-show="activeTab === 'state'" class="tab-content">
            <div v-if="!session" class="state-display">
              <div class="empty-hint">{{ $t('workflowDebug.createSessionFirst') }}</div>
            </div>
            <div v-else-if="isEditingState" class="state-display editable">
              <textarea v-model="editedState" class="state-textarea"></textarea>
            </div>
            <div v-else class="state-display">{{ formatStateTruncated(session.current_state) }}</div>
            <div v-if="session" class="state-actions">
              <button class="btn-text" @click="toggleStateEdit">
                {{ isEditingState ? $t('common.cancel') : $t('common.edit') }}
              </button>
              <button class="btn-text" @click="copyState">{{ $t('common.copy') }}</button>
              <button class="btn-success" @click="startWithState" :disabled="loading" style="margin-left: auto;">
                {{ $t('workflowDebug.useCurrentState') }}
              </button>
            </div>
          </div>

          <div v-show="activeTab === 'result'" class="tab-content">
            <div class="state-display">{{ formatStateTruncated(workflowOutput) }}</div>
            <div class="state-actions">
              <button class="btn-text" @click="copyResult">{{ $t('common.copy') }}</button>
            </div>
          </div>
        </div>
      </div>

      <!-- Right: Real-time Output -->
      <div class="output-panel">
        <div class="output-header">
          <h3>📺 {{ $t('workflowDebug.liveOutput') }}</h3>
          <div class="output-status">
            <span :class="['dot', { streaming: isRunning }]"></span>
            <span>{{ isRunning ? $t('workflowDebug.outputRunning') : $t('workflowDebug.outputWaiting') }}</span>
          </div>
        </div>
        <div class="output-content" ref="outputContent">
          <template v-for="(line, index) in outputLines" :key="index">
            <span :class="line.type" v-html="formatOutputText(line.text)"></span>
          </template>
          <span v-if="isRunning" class="cursor"></span>
        </div>
        <div class="output-actions">
          <button class="btn-text" @click="clearOutput">{{ $t('common.reset') }}</button>
          <button class="btn-text" @click="copyOutput">{{ $t('common.copy') }}</button>
          <label style="font-size: 11px; color: #666; margin-left: auto; display: flex; align-items: center; gap: 4px;">
            <input type="checkbox" v-model="autoScroll" /> {{ $t('workflowDebug.autoScroll') }}
          </label>
        </div>
      </div>
    </div>

    <!-- Human Input Modal -->
    <div v-if="showHumanInput" class="modal-overlay" @click="showHumanInput = false">
      <div class="modal-content human-input-modal" @click.stop>
        <h3>👤 {{ $t('workflowDebug.humanInputTitle') }}</h3>
        <div class="human-input-info">
          <p><strong>{{ $t('workflowDebug.node') }}:</strong> {{ session?.current_node }}</p>
          <p class="info-hint">{{ $t('workflowDebug.humanInputHint') }}</p>
        </div>
        
        <!-- Human 节点输入提示 -->
        <div class="input-hint-box">
          <div class="hint-title">📋 {{ $t('workflowDebug.inputHintTitle') }}</div>
          <div class="hint-content">
            <div v-if="humanNodeFeedbackField">
              <div class="hint-label">{{ $t('workflowDebug.requiredFields') }}:</div>
              <div class="hint-field">
                <span class="field-name">{{ humanNodeFeedbackField }}</span>
                <span class="field-desc">- {{ $t('workflowDebug.userInputContent') }}</span>
              </div>
            </div>
            <div v-else>
              <div class="hint-label">{{ $t('workflowDebug.commonInputFields') }}:</div>
              <div class="hint-field">
                <span class="field-name">user_input</span>
                <span class="field-desc">- {{ $t('workflowDebug.userInputText') }}</span>
              </div>
            </div>
          </div>
        </div>
        
        <div class="form-group">
          <label>{{ $t('workflowDebug.humanInputJsonLabel') }}:</label>
          <textarea v-model="humanInputData" rows="10" :placeholder="humanInputPlaceholder"></textarea>
        </div>
        <div class="modal-actions">
          <button class="btn-success" @click="submitHumanInput">✓ {{ $t('workflowDebug.submitAndContinue') }}</button>
          <button class="btn-secondary" @click="showHumanInput = false">{{ $t('common.cancel') }}</button>
        </div>
      </div>
    </div>

    <!-- Start Debug Input Modal -->
    <div v-if="showStartInput" class="modal-overlay" @click="showStartInput = false">
      <div class="modal-content start-input-modal" @click.stop>
        <h3>▶ {{ $t('workflowDebug.startDebug') }}: {{ workflowName }}</h3>
        
        <!-- 输入提示 -->
        <div class="input-hint-box">
          <div class="hint-title">📋 {{ $t('workflowDebug.inputRequirementTitle') }}</div>
          <div class="hint-content">
            <div v-if="firstNodeInputFields.length > 0">
              <div class="hint-label">{{ $t('workflowDebug.firstNodeFields', { name: firstNodeName }) }}:</div>
              <div v-for="field in firstNodeInputFields" :key="field" class="hint-field">
                <span class="field-name">{{ field }}</span>
              </div>
            </div>
            <div v-else>
              <div class="hint-label">{{ $t('workflowDebug.commonInputFields') }}:</div>
              <div class="hint-field"><span class="field-name">user_input</span> - {{ $t('workflowDebug.userInputText') }}</div>
            </div>
          </div>
        </div>
        
        <div class="form-group">
          <label>{{ $t('workflowDebug.startInputJsonLabel') }}:</label>
          <textarea v-model="startInputData" rows="10" :placeholder="startInputPlaceholder"></textarea>
        </div>
        <div class="form-group">
          <label>{{ $t('workflowDebug.threadIdOptional') }}:</label>
          <input v-model="threadId" type="text" :placeholder="$t('workflowDebug.threadIdPlaceholder')" />
        </div>
        <div class="modal-actions">
          <button class="btn-primary" @click="executeDebug">{{ $t('workflowDebug.execute') }}</button>
          <button class="btn-secondary" @click="showStartInput = false">{{ $t('common.cancel') }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { debugApi, workflowsApi } from '../api'
import WorkflowGraph from '../components/WorkflowGraph.vue'

export default {
  name: 'WorkflowDebug',
  components: { WorkflowGraph },
  data() {
    return {
      workflowId: '',
      workflowName: '',
      nodes: [],
      edges: [],
      session: null,
      breakpoints: [],
      loading: false,
      activeTab: 'state',
      isEditingState: false,
      editedState: '',
      showHumanInput: false,
      humanInputData: '',
      showStartInput: false,
      startInputData: `{"user_input": "${this.$t('workflowDebug.sampleUserInput')}"}`,
      threadId: '',
      pollInterval: null,
      history: [],
      startTime: null,
      selectedNode: null,
      // 实时输出相关
      outputLines: [],
      autoScroll: true,
      // SSE 连接
      eventSource: null,
      streamAbortController: null,
      notice: null,
    }
  },
  computed: {
    statusClass() {
      const status = this.session?.status
      if (status === 'running') return 'status-running'
      if (status === 'paused') return 'status-paused'
      if (status === 'interrupted') return 'status-interrupted'
      if (status === 'stopped') return 'status-stopped'
      if (status === 'completed') return 'status-completed'
      return ''
    },
    statusText() {
      const map = {
        running: this.$t('workflowDebug.statusMap.running'),
        paused: this.$t('workflowDebug.statusMap.paused'),
        interrupted: this.$t('workflowDebug.statusMap.interrupted'),
        stopped: this.$t('workflowDebug.statusMap.stopped'),
        completed: this.$t('workflowDebug.statusMap.completed'),
      }
      return map[this.session?.status] || this.$t('workflowDebug.statusMap.notCreated')
    },
    isRunning() { return this.session?.status === 'running' },
    isPaused() { return this.session?.status === 'paused' || this.session?.status === 'interrupted' },
    isStopped() { return this.session?.status === 'stopped' || this.session?.status === 'completed' || this.session?.status === 'interrupted' },
    isHumanNode() {
      if (!this.isPaused || !this.session?.current_node) return false
      const node = this.nodes.find(n => n.name === this.session.current_node)
      const nodeType = node?.type?.toLowerCase() || ''
      return nodeType.includes('human') || nodeType === 'humannode'
    },
    currentNodeType() {
      if (!this.session?.current_node) return null
      const node = this.nodes.find(n => n.name === this.session.current_node)
      return node?.type?.toLowerCase() || null
    },
    executedNodes() {
      if (!this.session?.history) return []
      return [...new Set(this.session.history.filter(h => h.node).map(h => h.node))]
    },
    executedCount() { return this.executedNodes.length },
    totalTime() {
      if (!this.startTime) return '0s'
      return `${((Date.now() - this.startTime) / 1000).toFixed(1)}s`
    },
    breakpointNodes() { return this.breakpoints.map(bp => bp.node_id) },
    graphNodes() {
      return this.nodes.map(node => ({ id: node.id, name: node.id, type: node.type }))
    },
    displayNodes() {
      const result = []
      this.nodes.forEach(node => {
        result.push({ ...node, id: node.id })
        if (node.type === 'parallel' && node.children) {
          node.children.forEach(child => {
            result.push({ ...child, id: child.name, indent: true, disabled: true })
          })
        }
      })
      return result
    },
    workflowOutput() {
      if (!this.session) return null
      return {
        status: this.session.status,
        current_node: this.session.current_node,
        executed_nodes: this.executedNodes,
        partial_result: this.session.current_state,
      }
    },
    startInputPlaceholder() { return `{"user_input": "${this.$t('workflowDebug.sampleUserInput')}"}` },
    humanInputPlaceholder() {
      const field = this.humanNodeFeedbackField || 'user_input'
      return `{\n  "${field}": "${this.$t('workflowDebug.userInputContent')}"\n}`
    },
    humanNodeFeedbackField() {
      if (!this.session?.current_node) return null
      const node = this.nodes.find(n => n.name === this.session.current_node)
      return node?.feedback_field || node?.config?.feedback_field || null
    },
    firstNodeName() {
      return this.nodes.length > 0 ? this.nodes[0].name : ''
    },
    firstNodeInputFields() {
      if (this.nodes.length === 0) return []
      const firstNode = this.nodes[0]
      return firstNode.input_schema?.fields || []
    },
  },
  async mounted() {
    this.workflowId = this.$route.params.id
    await this.loadWorkflow()
  },
  beforeUnmount() {
    this.stopPolling()
    this.closeEventSource()
  },
  methods: {
    showNotice(message, type = 'error') {
      this.notice = { message, type }
      setTimeout(() => {
        if (this.notice?.message === message) this.notice = null
      }, 5000)
    },
    async loadWorkflow() {
      try {
        const data = await workflowsApi.get(this.workflowId)
        this.workflowName = data.workflow.name
        this.nodes = data.workflow.nodes || []
        this.edges = data.workflow.edges || []
      } catch (error) {
        console.error('加载工作流失败:', error)
        this.showNotice(this.$t('workflowDebug.messages.loadWorkflowFailed'))
      }
    },
    async loadSession() {
      if (!this.session) return
      try {
        const data = await debugApi.getSession(this.session.session_id)
        
        if (data.history && data.history.length > 0) {
          this.syncBackendHistory(data.history)
        }
        this.session = data
        this.breakpoints = data.breakpoints || []
      } catch (error) {
        console.error('加载会话失败:', error)
        this.showNotice(this.$t('workflowDebug.messages.loadSessionFailed'))
      }
    },
    syncBackendHistory(backendHistory) {
      for (const item of backendHistory) {
        if (item.action === 'node_output') {
          const exists = this.history.some(h => h.backendId === `output_${item.node}_${item.timestamp}`)
          if (!exists) {
            this.history.unshift({
              action: `📤 ${item.node}`,
              detail: this.$t('workflowDebug.messages.nodeOutput'),
              type: 'output',
              timestamp: new Date(item.timestamp).getTime(),
              backendId: `output_${item.node}_${item.timestamp}`,
            })
          }
        } else if (item.action === 'node_executed') {
          const exists = this.history.some(h => h.backendId === `${item.node}_${item.timestamp}`)
          if (!exists) {
            const nodeType = item.type || 'unknown'
            const icon = nodeType === 'human' ? '👤' : nodeType.toLowerCase().includes('llm') ? '🤖' : '⚙️'
            this.history.unshift({
              action: `${icon} ${item.node}`,
              detail: this.$t('workflowDebug.messages.nodeCompleted', { type: nodeType }),
              type: 'node',
              timestamp: new Date(item.timestamp).getTime(),
              backendId: `${item.node}_${item.timestamp}`,
            })
          }
        } else if (item.action === 'pause') {
          const exists = this.history.some(h => h.backendId === `pause_${item.node}_${item.timestamp}`)
          if (!exists) {
            this.history.unshift({
              action: `⏸ ${this.$t('workflowDebug.messages.pauseAction')}`,
              detail: this.$t('workflowDebug.messages.nodeLabel', { node: item.node }),
              type: 'pause',
              timestamp: new Date(item.timestamp).getTime(),
              backendId: `pause_${item.node}_${item.timestamp}`,
            })
          }
        }
      }
      this.history.sort((a, b) => b.timestamp - a.timestamp)
      if (this.history.length > 50) this.history = this.history.slice(0, 50)
    },
    async toggleBreakpoint(nodeName) {
      const bpId = `${nodeName}:before`
      const exists = this.breakpoints.find(bp => bp.id === bpId)
      if (exists) {
        this.breakpoints = this.breakpoints.filter(bp => bp.id !== bpId)
        if (this.session) {
          try { await debugApi.removeBreakpoint(this.session.session_id, bpId) } catch (e) { console.error(e) }
        }
      } else {
        this.breakpoints.push({ id: bpId, node_id: nodeName, type: 'before', enabled: true })
        if (this.session) {
          try { await debugApi.addBreakpoint(this.session.session_id, nodeName, 'before') } catch (e) { console.error(e) }
        }
      }
    },
    async clearAllBreakpoints() {
      if (this.breakpoints.length === 0) return
      if (this.session) {
        for (const bp of this.breakpoints) {
          try { await debugApi.removeBreakpoint(this.session.session_id, bp.id) } catch (e) { console.error(e) }
        }
      }
      this.breakpoints = []
    },
    startDebug() {
      this.history = []
      this.outputLines = []
      this.session = null
      this.startTime = null
      this.showStartInput = true
    },
    async executeDebug() {
      this.loading = true
      this.showStartInput = false
      try {
        const inputData = JSON.parse(this.startInputData)
        this.startTime = Date.now()
        const breakpoints = this.breakpoints.map(bp => ({
          node_id: bp.node_id, type: bp.type || 'before', condition: bp.condition || null
        }))
        const result = await debugApi.debugRun(this.workflowId, inputData, this.threadId || null, breakpoints)
        this.session = {
          session_id: result.session_id,
          workflow_id: result.workflow_id,
          thread_id: result.thread_id,
          status: result.status,
          current_node: null,
          current_state: {},
          breakpoints: result.breakpoints || [],
          history: [],
        }
        this.addHistory(`▶ ${this.$t('workflowDebug.start')}`, this.$t('workflowDebug.messages.debugStarted'))
        this.outputLines = []
        this.startEventSource(result.session_id)
        this.startPolling()
      } catch (error) {
        console.error('执行失败:', error)
        this.showNotice(this.$t('workflowDebug.messages.executeFailed', { message: error.response?.data?.detail || error.message }))
      } finally {
        this.loading = false
      }
    },
    async resume() {
      this.loading = true
      try {
        await debugApi.resume(this.session.session_id)
        this.addHistory(`▶ ${this.$t('workflowDebug.resume')}`, this.$t('workflowDebug.messages.resumeStarted'))
        await new Promise(r => setTimeout(r, 100))
        await this.loadSession()
      } catch (error) {
        console.error('继续执行失败:', error)
        this.showNotice(this.$t('workflowDebug.messages.resumeFailed'))
      } finally {
        this.loading = false
      }
    },
    async step() {
      this.loading = true
      try {
        await debugApi.step(this.session.session_id)
        this.addHistory(`⏭ ${this.$t('workflowDebug.step')}`, this.$t('workflowDebug.messages.stepStarted'))
        await new Promise(r => setTimeout(r, 100))
        await this.loadSession()
      } catch (error) {
        console.error('单步执行失败:', error)
        this.showNotice(this.$t('workflowDebug.messages.stepFailed'))
      } finally {
        this.loading = false
      }
    },
    async stop() {
      this.loading = true
      try {
        await debugApi.stop(this.session.session_id)
        this.addHistory(`⏹ ${this.$t('workflowDebug.stop')}`, this.$t('workflowDebug.messages.stopStarted'))
        await this.loadSession()
      } catch (error) {
        console.error('停止执行失败:', error)
        this.showNotice(this.$t('workflowDebug.messages.stopFailed'))
      } finally {
        this.loading = false
      }
    },
    selectNode(node) { this.selectedNode = node },
    toggleStateEdit() {
      this.isEditingState = !this.isEditingState
      if (this.isEditingState) {
        this.editedState = this.formatState(this.session.current_state)
      }
    },
    startWithState() { this.startDebug() },
    async saveAndResume() {
      try {
        const newState = JSON.parse(this.editedState)
        await debugApi.updateState(this.session.session_id, newState)
        this.isEditingState = false
        await this.resume()
      } catch (error) {
        console.error('保存状态失败:', error)
        this.showNotice(this.$t('workflowDebug.messages.saveStateFailed'))
      }
    },
    showHumanInputModal() {
      const field = this.humanNodeFeedbackField || 'user_input'
      this.humanInputData = JSON.stringify({ [field]: '' }, null, 2)
      this.showHumanInput = true
    },
    async submitHumanInput() {
      try {
        let data
        try { data = JSON.parse(this.humanInputData) } catch { data = this.humanInputData }
        const currentState = { ...(this.session.current_state || {}) }
        const nodeName = this.session.current_node
        if (typeof data === 'object' && data !== null && !Array.isArray(data)) {
          Object.assign(currentState, data)
        } else {
          currentState[nodeName] = data
        }
        await debugApi.updateState(this.session.session_id, currentState)
        this.showHumanInput = false
        this.addHistory(`👤 ${this.$t('workflowDebug.humanInputTitle')}`, this.$t('workflowDebug.messages.nodeLabel', { node: nodeName }))
        await this.resume()
      } catch (error) {
        console.error('提交失败:', error)
        this.showNotice(this.$t('workflowDebug.messages.submitFailed'))
      }
    },
    hasBreakpoint(nodeName) { return this.breakpoints.some(bp => bp.node_id === nodeName) },
    isNodeExecuted(nodeName) { return this.executedNodes.includes(nodeName) },
    getNodeTypeLabel(type) {
      const t = type?.toLowerCase() || ''
      if (t.includes('llm')) return 'LLM'
      if (t.includes('human')) return this.$t('workflowDebug.nodeTypes.human')
      if (t.includes('parallel')) return this.$t('workflowDebug.nodeTypes.parallel')
      if (t.includes('function')) return this.$t('workflowDebug.nodeTypes.function')
      return type
    },
    truncateJsonValues(obj, maxLen = 20000) {
      if (obj === null || obj === undefined) return obj
      if (typeof obj === 'string') {
        return obj.length > maxLen ? obj.substring(0, maxLen) + this.$t('workflowDebug.messages.outputTruncated') : obj
      }
      if (Array.isArray(obj)) {
        return obj.map(item => this.truncateJsonValues(item, maxLen))
      }
      if (typeof obj === 'object') {
        const result = {}
        for (const key in obj) {
          result[key] = this.truncateJsonValues(obj[key], maxLen)
        }
        return result
      }
      return obj
    },
    formatState(state) {
      if (!state) return this.$t('workflowDebug.messages.noData')
      return JSON.stringify(state, null, 2)
    },
    formatStateTruncated(state) {
      if (!state) return this.$t('workflowDebug.messages.noData')
      const truncated = this.truncateJsonValues(state, 20000)
      return JSON.stringify(truncated, null, 2)
    },
    formatTime(timestamp) {
      if (!timestamp) return new Date().toLocaleTimeString()
      return new Date(timestamp).toLocaleTimeString()
    },
    addHistory(action, detail, type = 'normal') {
      this.history.unshift({ action, detail, type, timestamp: Date.now() })
      if (this.history.length > 50) this.history = this.history.slice(0, 50)
    },
    handleNodeClick(node) { console.log('Node clicked:', node) },
    startPolling() {
      this.stopPolling()
      this.pollInterval = setInterval(() => {
        if (this.session && !['stopped', 'completed', 'error', 'interrupted'].includes(this.session.status)) {
          this.loadSession()
        }
      }, 1000)
    },
    stopPolling() {
      if (this.pollInterval) { clearInterval(this.pollInterval); this.pollInterval = null }
    },
    goBack() { this.$router.push(`/workflows/${this.workflowId}`) },
    async startEventSource(sessionId) {
      this.closeEventSource()
      const baseUrl = import.meta.env.VITE_API_BASE_URL || ''
      const token = localStorage.getItem('admin_token') || ''
      const url = `${baseUrl}/admin/debug/sessions/${sessionId}/stream`
      const controller = new AbortController()
      this.streamAbortController = controller

      try {
        const response = await fetch(url, {
          headers: { Authorization: `Bearer ${token}` },
          signal: controller.signal,
        })
        if (response.status === 401) {
          localStorage.removeItem('admin_token')
          window.dispatchEvent(new CustomEvent('admin-auth-required'))
        }
        if (!response.ok || !response.body) {
          throw new Error(`SSE stream failed: ${response.status}`)
        }

        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''

        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          const events = buffer.split(/\r?\n\r?\n/)
          buffer = events.pop() || ''
          for (const rawEvent of events) {
            this.handleStreamEvent(rawEvent)
          }
        }

        buffer += decoder.decode()
        if (buffer.trim()) {
          this.handleStreamEvent(buffer)
        }
      } catch (error) {
        if (controller.signal.aborted) return
        console.error('SSE 连接错误:', error)
        const message = error?.message || 'SSE stream failed'
        this.addHistory(`! ${this.$t('workflowDebug.liveOutput')}`, message, 'error')
        this.outputLines.push({ text: `\n[stream error] ${message}\n`, type: 'error' })
        if (this.session && ['stopped', 'completed', 'error', 'interrupted'].includes(this.session.status)) {
          this.closeEventSource()
        }
      } finally {
        if (this.streamAbortController === controller) {
          this.streamAbortController = null
        }
      }
    },
    handleStreamEvent(rawEvent) {
      let eventType = 'message'
      const dataLines = []
      for (const line of rawEvent.split(/\r?\n/)) {
        if (!line || line.startsWith(':')) continue
        if (line.startsWith('event:')) {
          eventType = line.slice(6).trim() || 'message'
        } else if (line.startsWith('data:')) {
          dataLines.push(line.slice(5).replace(/^ /, ''))
        }
      }
      if (dataLines.length === 0 || eventType === 'ping') return
      this.handleStreamPayload(eventType, dataLines.join('\n'))
    },
    handleStreamPayload(eventType, dataText) {
      try {
        const data = JSON.parse(dataText)
        if (eventType === 'message') {
          if (data.content) this.appendOutput(data.content)
        } else if (eventType === 'node_started') {
          this.addHistory(`⚙️ ${data.node}`, this.$t('workflowDebug.messages.nodeStarted', { type: data.type || 'unknown' }), 'node')
        } else if (eventType === 'node_finished') {
          const elapsed = data.elapsed_time ? `${data.elapsed_time.toFixed(2)}s` : ''
          this.addHistory(`✓ ${data.node}`, this.$t('workflowDebug.messages.nodeFinished', { elapsed }), 'node')

          if (this.outputLines.length > 0) {
            const lastLine = this.outputLines[this.outputLines.length - 1]
            if (lastLine.type === 'chunk' && lastLine.text.trim()) {
              this.outputLines.push({ text: '\n', type: 'chunk' })
            }
          }
        } else if (eventType === 'tool') {
          this.addHistory(`🔧 ${data.tool_name}`, this.$t('workflowDebug.messages.toolCalled'), 'tool')
        } else if (eventType === 'status') {
          if (data.status === 'completed') {
            this.addHistory(`✅ ${this.$t('workflowDebug.statusMap.completed')}`, this.$t('workflowDebug.messages.workflowCompleted'), 'success')
            this.closeEventSource()
          } else if (data.status === 'interrupted') {
            const node = data.current_node || data.interrupt_node || this.$t('workflowDebug.messages.unknownNode')
            this.addHistory(`⏸ ${this.$t('workflowDebug.statusMap.interrupted')}`, this.$t('workflowDebug.messages.waitingAtNode', { node }), 'pause')
            this.closeEventSource()
          } else if (data.status === 'stopped' || data.status === 'error') {
            this.addHistory(`❌ ${this.$t('workflowDebug.stop')}`, this.$t('workflowDebug.messages.workflowStopped'), 'error')
            this.closeEventSource()
          }
        } else if (eventType === 'error') {
          this.addHistory(`❌ ${this.$t('workflowDebug.messages.error')}`, data.message, 'error')
        }
      } catch (e) {
        console.error(`解析 ${eventType} 事件失败:`, e)
      }
    },
    closeEventSource() {
      if (this.streamAbortController) {
        this.streamAbortController.abort()
        this.streamAbortController = null
      }
      if (this.eventSource) {
        this.eventSource.close()
        this.eventSource = null
      }
    },
    appendOutput(text) {
      if (this.outputLines.length === 0) {
        this.outputLines.push({ text: '', type: 'chunk' })
      }
      const lastLine = this.outputLines[this.outputLines.length - 1]
      if (lastLine.type === 'chunk') {
        lastLine.text += text
      } else {
        this.outputLines.push({ text, type: 'chunk' })
      }
      if (this.autoScroll) {
        this.$nextTick(() => {
          const el = this.$refs.outputContent
          if (el) el.scrollTop = el.scrollHeight
        })
      }
    },
    addOutputLine(text, type = 'chunk') {
      this.outputLines.push({ text, type })
      if (this.autoScroll) {
        this.$nextTick(() => {
          const el = this.$refs.outputContent
          if (el) el.scrollTop = el.scrollHeight
        })
      }
    },
    formatOutputText(text) {
      if (!text) return ''
      const escaped = text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
      return escaped.replace(/\n/g, '<br>')
    },
    clearOutput() {
      this.outputLines = []
    },
    async copyOutput() {
      const text = this.outputLines.map(l => l.text).join('\n')
      await this.copyText(text, this.$t('workflowDebug.messages.copiedToClipboard'))
    },
    async copyState() {
      const text = this.formatState(this.session?.current_state)
      await this.copyText(text, this.$t('workflowDebug.messages.stateCopied'))
    },
    async copyResult() {
      const text = this.formatState(this.workflowOutput)
      await this.copyText(text, this.$t('workflowDebug.messages.resultCopied'))
    },
    async copyText(text, successMessage) {
      try {
        await navigator.clipboard.writeText(text)
        this.showNotice(successMessage, 'success')
      } catch {
        this.showNotice(text || successMessage, 'info')
      }
    },
  },
}
</script>


<style scoped>
.workflow-debug {
  padding: 12px;
  height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* Header */
.debug-header {
  background: white;
  padding: 12px 20px;
  border-radius: 8px;
  margin-bottom: 12px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.1);
  flex-shrink: 0;
}

.header-top {
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: center;
  gap: 20px;
  margin-bottom: 10px;
  padding-bottom: 10px;
  border-bottom: 2px solid #e0e0e0;
}

.header-left { display: flex; align-items: center; }
.header-center { text-align: center; }
.header-center h1 { font-size: 18px; margin: 0 0 2px 0; }
.workflow-id { color: #666; font-size: 13px; }
.header-info { display: flex; gap: 12px; }
.info-row { display: flex; align-items: center; gap: 4px; font-size: 13px; }
.info-label { color: #666; }
.info-value { font-family: monospace; background: #f5f5f5; padding: 2px 5px; border-radius: 3px; font-weight: 600; font-size: 13px; }

/* Control Panel */
.control-panel {
  display: flex;
  gap: 15px;
  align-items: center;
  flex-wrap: wrap;
  padding: 10px 12px;
  background: #f9f9f9;
  border-radius: 6px;
}

.control-item { display: flex; align-items: center; gap: 6px; font-size: 14px; }

.debug-notice {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin: 0 0 12px;
  padding: 10px 12px;
  border-radius: 6px;
  border: 1px solid #fecaca;
  background: #fef2f2;
  color: #991b1b;
  font-size: 13px;
  flex-shrink: 0;
}
.debug-notice.success {
  border-color: #bbf7d0;
  background: #f0fdf4;
  color: #166534;
}
.debug-notice.info {
  border-color: #bfdbfe;
  background: #eff6ff;
  color: #1e40af;
}
.debug-notice button {
  border: 0;
  background: transparent;
  color: inherit;
  cursor: pointer;
  font-size: 16px;
  line-height: 1;
}
.control-item label { font-weight: 600; color: #555; }
.status-badge { padding: 3px 10px; border-radius: 10px; font-size: 12px; font-weight: 600; }
.status-running { background: #e3f2fd; color: #1976d2; }
.status-paused { background: #fff3e0; color: #f57c00; }
.status-interrupted { background: #e1bee7; color: #7b1fa2; }
.status-stopped { background: #ffebee; color: #c62828; }
.status-completed { background: #e8f5e9; color: #388e3c; }
.current-node { font-family: monospace; font-weight: 600; color: #1976d2; }
.node-type-badge { font-size: 11px; padding: 2px 6px; border-radius: 3px; margin-left: 5px; }
.node-type-badge.llm { background: #e3f2fd; color: #1976d2; }
.node-type-badge.function { background: #f3e5f5; color: #7b1fa2; }
.node-type-badge.human { background: #e0f7fa; color: #00838f; }
.control-actions { margin-left: auto; display: flex; gap: 8px; }

/* Human Alert */
.human-alert {
  background: #f3e5f5;
  border: 2px solid #9c27b0;
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}
.human-alert-icon { font-size: 28px; }
.human-alert-content { flex: 1; }
.human-alert-title { font-weight: 600; font-size: 14px; color: #6a1b9a; margin-bottom: 4px; }
.human-alert-message { font-size: 12px; color: #666; }
.human-hint { font-size: 11px; color: #9c27b0; font-style: italic; }
.human-alert-actions { display: flex; gap: 8px; }

/* Main Content - 3 columns */
.debug-content {
  display: grid;
  grid-template-columns: 280px 1fr 660px;
  gap: 12px;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.debug-panel {
  background: white;
  border-radius: 8px;
  padding: 12px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.1);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
  padding-bottom: 8px;
  border-bottom: 2px solid #f0f0f0;
  flex-shrink: 0;
}
.panel-header h3 { font-size: 14px; color: #333; margin: 0; }

/* Left Panels */
.left-panels { display: flex; flex-direction: column; gap: 12px; overflow: hidden; }
.nodes-panel { flex: 1; }
.history-panel { flex: 1; }

/* Nodes List */
.nodes-list { display: flex; flex-direction: column; gap: 6px; overflow-y: auto; flex: 1; }
.node-card {
  border: 2px solid #e0e0e0;
  border-radius: 5px;
  padding: 8px 10px;
  background: #fafafa;
  cursor: pointer;
  transition: all 0.2s;
}
.node-card:hover { border-color: #bbb; }
.node-card.current { border-color: #1976d2; border-left: 4px solid #1976d2; background: #e3f2fd; }
.node-card.executed { opacity: 0.5; }
.node-card.has-breakpoint { border-left: 4px solid #f57c00; background: #fff8e1; }
.node-header { display: flex; justify-content: space-between; align-items: center; }
.node-left { display: flex; align-items: center; gap: 6px; }
.breakpoint-checkbox { width: 14px; height: 14px; accent-color: #f57c00; }
.node-name { font-weight: 600; font-size: 13px; }
.node-type { font-size: 11px; color: #666; background: #e0e0e0; padding: 2px 5px; border-radius: 3px; }
.node-type.llm { background: #e3f2fd; color: #1976d2; }
.node-type.human { background: #e0f7fa; color: #00838f; }

/* History */
.history-list { display: flex; flex-direction: column; gap: 5px; overflow-y: auto; flex: 1; }
.history-item { padding: 6px 8px; background: #f5f5f5; border-radius: 4px; font-size: 12px; border-left: 3px solid #ddd; }
.history-item.pause { border-left-color: #f57c00; }
.history-item.node { border-left-color: #9c27b0; }
.history-header { display: flex; justify-content: space-between; }
.history-action { font-weight: 600; }
.history-time { color: #999; font-size: 11px; }
.history-detail { color: #666; font-size: 11px; margin-top: 2px; }
.empty-state { text-align: center; color: #999; padding: 20px; font-size: 13px; }

/* Center Panels */
.center-panels { display: flex; flex-direction: column; gap: 12px; overflow: hidden; }
.graph-panel { flex: 0 0 auto; }
.graph-container {
  background: #fafafa;
  border-radius: 6px;
  padding: 15px;
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 200px;
  overflow: auto;
}
.legend-inline { font-size: 11px; color: #666; }

/* State Panel */
.state-panel { flex: 1; min-height: 0; }
.state-tabs { display: flex; gap: 4px; margin-bottom: 10px; border-bottom: 2px solid #f0f0f0; flex-shrink: 0; }
.tab {
  padding: 6px 12px;
  cursor: pointer;
  border: none;
  background: transparent;
  color: #666;
  font-weight: 500;
  font-size: 12px;
  border-bottom: 2px solid transparent;
  margin-bottom: -2px;
}
.tab.active { color: #1976d2; border-bottom-color: #1976d2; }
.tab-content { display: flex; flex-direction: column; flex: 1; overflow: hidden; }
.state-display {
  background: #f5f5f5;
  padding: 10px;
  border-radius: 5px;
  font-family: monospace;
  font-size: 13px;
  line-height: 1.5;
  overflow: auto;
  flex: 1;
  white-space: pre;
}
.state-display.editable { background: white; border: 1px solid #ddd; padding: 0; }
.state-textarea { width: 100%; height: 100%; padding: 10px; border: none; font-family: monospace; font-size: 13px; line-height: 1.5; resize: none; }
.state-actions { display: flex; gap: 8px; margin-top: 8px; flex-shrink: 0; }
.empty-hint { text-align: center; color: #999; padding: 20px; }

/* Output Panel */
.output-panel {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: white;
  border-radius: 8px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}
.output-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 12px;
  border-bottom: 2px solid #f0f0f0;
  flex-shrink: 0;
}
.output-header h3 { font-size: 15px; margin: 0; }
.output-status { display: flex; align-items: center; gap: 6px; font-size: 13px; color: #666; }
.output-status .dot { width: 8px; height: 8px; border-radius: 50%; background: #ccc; }
.output-status .dot.streaming { background: #4caf50; animation: pulse 1s infinite; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
.output-content {
  flex: 1;
  overflow: auto;
  padding: 12px;
  font-family: monospace;
  font-size: 14px;
  line-height: 1.6;
  background: #1e1e1e;
  color: #d4d4d4;
  white-space: pre-wrap;
  word-break: break-word;
}
.output-content .chunk { color: #9cdcfe; }
.output-content .user { color: #ce9178; }
.output-content .system { color: #6a9955; }
.output-content .error { color: #f48771; }
.output-content .cursor { display: inline-block; width: 8px; height: 14px; background: #d4d4d4; animation: blink 1s infinite; }
@keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }
.output-actions { display: flex; gap: 8px; padding: 8px 12px; border-top: 1px solid #f0f0f0; flex-shrink: 0; }

/* Buttons */
button {
  padding: 6px 14px;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  transition: all 0.2s;
}
button:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 2px 4px rgba(0,0,0,0.2); }
button:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-primary { background: #1976d2; color: white; }
.btn-success { background: #388e3c; color: white; }
.btn-danger { background: #d32f2f; color: white; }
.btn-secondary { background: #616161; color: white; }
.btn-back { background: #f5f5f5; color: #555; border: 1px solid #ddd; }
.btn-text { background: transparent; color: #1976d2; padding: 3px 6px; }

/* Modal */
.modal-overlay {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}
.modal-content {
  background: white;
  padding: 25px;
  border-radius: 8px;
  max-width: 600px;
  width: 90%;
  box-shadow: 0 4px 20px rgba(0,0,0,0.3);
}
.modal-content h3 { margin: 0 0 15px 0; font-size: 18px; }
.human-input-info {
  background: #f3e5f5;
  padding: 10px 12px;
  border-radius: 6px;
  margin-bottom: 15px;
  border-left: 4px solid #9c27b0;
}
.human-input-info p { margin: 0 0 4px 0; font-size: 13px; }
.human-input-info .info-hint { font-size: 11px; color: #666; margin: 0; }

/* Input Hint Box */
.input-hint-box {
  background: #e8f5e9;
  border: 1px solid #c8e6c9;
  border-radius: 6px;
  padding: 12px 15px;
  margin-bottom: 15px;
}
.hint-title {
  font-weight: 600;
  color: #2e7d32;
  margin-bottom: 8px;
  font-size: 13px;
}
.hint-content { font-size: 12px; }
.hint-label { color: #666; margin-bottom: 5px; }
.hint-field {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
}
.hint-field .field-name {
  font-family: monospace;
  background: #fff;
  padding: 2px 6px;
  border-radius: 3px;
  color: #1976d2;
  font-weight: 500;
}
.hint-field .field-desc {
  color: #666;
  font-size: 11px;
}

.form-group { margin-bottom: 15px; }
.form-group label { display: block; margin-bottom: 6px; font-weight: 600; color: #555; font-size: 13px; }
.form-group textarea, .form-group input {
  width: 100%;
  padding: 10px;
  border: 1px solid #ddd;
  border-radius: 4px;
  font-family: monospace;
  font-size: 12px;
}
.form-group textarea { resize: vertical; }
.modal-actions { display: flex; gap: 10px; justify-content: flex-end; }

/* Scrollbar */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: #f1f1f1; border-radius: 3px; }
::-webkit-scrollbar-thumb { background: #bbb; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #888; }
</style>
