<template>
  <div class="message-wrapper">
    <div class="message">
      <div class="message-avatar">AC</div>
      <div class="message-content">
        <div class="message-header">
          <span class="agent-name">AgentClaw</span>
          <span class="mono-font">{{ currentTime }}</span>
        </div>

        <!-- Todo 卡片 -->
        <TodoCard v-if="todoItems.length" :items="todoItems" />

        <div v-if="hasProcessDetails && processCollapsed" class="process-summary-card" @click="$emit('toggle-process-view')">
          <div class="process-summary-marker">
            <span class="process-summary-dot" :class="processSummaryState">
              <svg v-if="processSummaryState === 'completed'" class="summary-state-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M20 6L9 17l-5-5" />
              </svg>
              <svg v-else-if="processSummaryState === 'failed'" class="summary-state-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M12 8v5" />
                <path d="M12 16h.01" />
              </svg>
            </span>
          </div>
          <div class="process-summary-body">
            <div class="process-summary-title">{{ processSummary.title }}</div>
            <div class="process-summary-meta mono-font">{{ processSummary.detail }}</div>
          </div>
          <svg class="expand-chevron rotated" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18l6-6-6-6"/></svg>
        </div>

        <!-- 执行步骤 -->
        <div v-if="nodeSteps.length && !processCollapsed" class="agent-step active">
          <template v-for="(group, gi) in groupedSteps" :key="gi">
            <!-- 并行组 -->
            <div v-if="group.isParallel" class="timeline-entry parallel-entry">
              <div class="timeline-marker">
                <span class="timeline-dot parallel-dot"></span>
              </div>
              <div class="timeline-card parallel-card">
              <div class="parallel-label mono-font">
                  <div class="parallel-label-main">
                    <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 3h5v5M4 20L21 3M21 16v5h-5M15 15l6 6M4 4l5 5"/></svg>
                    <span>{{ $t('streamingMessage.parallelBranches') }}</span>
                  </div>
                  <span>{{ $t('streamingMessage.stepCount', { count: group.steps.length }) }}</span>
                </div>
                <div class="parallel-steps">
                  <div v-for="(step, si) in group.steps" :key="step.id || si" class="parallel-step">
                    <div class="step-card" :class="{ running: step.status === 'running', failed: step.error || step.status === 'failed' || step.status === 'error' }">
                      <div class="step-header" @click="step.expanded = !step.expanded">
                        <svg v-if="isStepRunning(step)" class="icon-spin" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v4m0 12v4M4.93 4.93l2.83 2.83m8.48 8.48l2.83 2.83M2 12h4m12 0h4M4.93 19.07l2.83-2.83m8.48-8.48l2.83-2.83"/></svg>
                        <svg v-else-if="isStepFailed(step)" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 8v5" /><path d="M12 16h.01" /><circle cx="12" cy="12" r="9" /></svg>
                        <svg v-else viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6L9 17l-5-5" /></svg>
                        <span>{{ step.name }}{{ step.elapsed ? ` (${step.elapsed})` : step.status === 'running' ? '...' : '' }}</span>
                        <svg class="expand-chevron" :class="{ rotated: step.expanded }" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18l6-6-6-6"/></svg>
                      </div>
                  <!-- 节点 IO 面板 -->
                  <div v-if="step.expanded && (step.inputs || step.outputs || step.error)" class="node-io-panel mono-font">
                    <div v-if="step.inputs && Object.keys(step.inputs).length" class="io-section">
                      <JsonCodeBlock :label="$t('streamingMessage.input')" :value="step.inputs" />
                    </div>
                    <div v-if="step.outputs && Object.keys(step.outputs).length" class="io-section">
                      <JsonCodeBlock :label="$t('streamingMessage.output')" :value="step.outputs" />
                    </div>
                    <div v-if="step.error" class="io-section">
                      <JsonCodeBlock :label="$t('streamingMessage.error')" :value="step.error" tone="error" />
                    </div>
                  </div>
                  <!-- 交叉显示 segments -->
                  <template v-for="(seg, si2) in getDisplaySegments(step)" :key="si2">
                    <div v-if="seg.type === 'reasoning'" class="mini-thinking" :class="{ expanded: seg.expanded }">
                      <div class="mini-thinking-header" @click="seg.expanded = !seg.expanded">
                        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1m-1.636 5.636l-.707-.707M12 21v-1m-5.636-1.636l.707-.707M3 12h1m1.636-5.636l.707.707M12 5a7 7 0 100 14 7 7 0 000-14z"/></svg>
                        <span>{{ $t('streamingMessage.thinking') }}</span>
                        <svg class="expand-chevron" :class="{ rotated: seg.expanded }" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18l6-6-6-6"/></svg>
                      </div>
                      <div v-show="seg.expanded" class="mini-thinking-body mono-font">{{ seg.content }}</div>
                    </div>
                    <div v-else-if="seg.type === 'tool-group'" class="tool-group-block">
                      <div class="tool-group">
                        <div
                          v-for="(item, ti) in getToolGroupItems(seg.tools)"
                          :key="item.key || ti"
                          class="mini-tool-capsule mono-font"
                          :class="{ running: item.running, selected: isToolSelected(item) }"
                          @click="onToolGroupClick(item)"
                        >
                          <svg v-if="item.running" class="icon-spin" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v4m0 12v4M4.93 4.93l2.83 2.83m8.48 8.48l2.83 2.83M2 12h4m12 0h4M4.93 19.07l2.83-2.83m8.48-8.48l2.83-2.83"/></svg>
                          <span v-else class="tool-status-dot" :class="item.failed ? 'dot-red' : 'dot-green'"></span>
                          <span class="tool-name">{{ item.name }}</span>
                          <span v-if="item.count > 1" class="tool-args-summary">×{{ item.count }}</span><span v-else-if="getToolArgsSummary(item.tool.arguments)" class="tool-args-summary">{{ getToolArgsSummary(item.tool.arguments) }}</span>
                          <span v-if="item.count === 1 && item.tool.elapsed" class="tool-elapsed">{{ item.tool.elapsed }}</span>
                        </div>
                      </div>
                      <ToolDetailsPanel
                        v-if="selectedTool && selectedToolBelongsToSegment(seg.tools)"
                        :tool="selectedTool"
                        :visible="true"
                        @close="selectedTool = null"
                      />
                    </div>
                    <div v-else-if="seg.type === 'assistant-note'" class="assistant-note-block">
                    <span class="assistant-note-label">{{ $t('streamingMessage.executionNote') }}</span>
                    <span class="assistant-note-text">{{ seg.content }}</span>
                  </div>
                  <div v-else-if="seg.type === 'harness-feedback'" class="harness-feedback-note">
                      <span class="harness-feedback-label">{{ $t('streamingMessage.harnessFeedback') }}</span>
                      <span class="harness-feedback-text">{{ seg.content }}</span>
                    </div>
	                </template>
	                    </div>
	                </div>
	              </div>
	            </div>
            </div>
	            <!-- 顺序节点 -->
            <template v-else>
              <div
                v-for="(step, si) in group.steps"
                :key="step.id || si"
                class="timeline-entry"
                :class="{ running: isStepRunning(step), failed: isStepFailed(step), completed: isStepCompleted(step) }"
              >
                <div class="timeline-marker">
                  <span class="timeline-dot" :class="stepTimelineClass(step)">
                    <svg v-if="isStepCompleted(step)" class="timeline-state-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M20 6L9 17l-5-5" />
                    </svg>
                    <svg v-else-if="isStepFailed(step)" class="timeline-state-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M12 8v5" />
                      <path d="M12 16h.01" />
                    </svg>
                  </span>
                </div>
                <div class="timeline-card">
                <div class="step-card" :class="{ running: step.status === 'running', failed: step.error || step.status === 'failed' || step.status === 'error' }">
                  <div class="step-header" @click="step.expanded = !step.expanded">
                    <svg v-if="isStepRunning(step)" class="icon-spin" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v4m0 12v4M4.93 4.93l2.83 2.83m8.48 8.48l2.83 2.83M2 12h4m12 0h4M4.93 19.07l2.83-2.83m8.48-8.48l2.83-2.83"/></svg>
                    <svg v-else-if="isStepFailed(step)" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 8v5" /><path d="M12 16h.01" /><circle cx="12" cy="12" r="9" /></svg>
                    <svg v-else viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6L9 17l-5-5" /></svg>
                    <span>{{ step.name }}{{ step.elapsed ? ` (${step.elapsed})` : step.status === 'running' ? '...' : '' }}</span>
                    <svg class="expand-chevron" :class="{ rotated: step.expanded }" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18l6-6-6-6"/></svg>
                  </div>
                <!-- 节点 IO 面板 -->
                <div v-if="step.expanded && (step.inputs || step.outputs || step.error)" class="node-io-panel mono-font">
                  <div v-if="step.inputs && Object.keys(step.inputs).length" class="io-section">
                    <JsonCodeBlock :label="$t('streamingMessage.input')" :value="step.inputs" />
                  </div>
                  <div v-if="step.outputs && Object.keys(step.outputs).length" class="io-section">
                    <JsonCodeBlock :label="$t('streamingMessage.output')" :value="step.outputs" />
                  </div>
                  <div v-if="step.error" class="io-section">
                    <JsonCodeBlock :label="$t('streamingMessage.error')" :value="step.error" tone="error" />
                  </div>
                </div>
                <!-- 交叉显示 segments -->
                <template v-for="(seg, si2) in getDisplaySegments(step)" :key="si2">
                  <div v-if="seg.type === 'reasoning'" class="mini-thinking" :class="{ expanded: seg.expanded }">
                    <div class="mini-thinking-header" @click="seg.expanded = !seg.expanded">
                      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1m-1.636 5.636l-.707-.707M12 21v-1m-5.636-1.636l.707-.707M3 12h1m1.636-5.636l.707.707M12 5a7 7 0 100 14 7 7 0 000-14z"/></svg>
                      <span>{{ $t('streamingMessage.thinking') }}</span>
                      <svg class="expand-chevron" :class="{ rotated: seg.expanded }" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18l6-6-6-6"/></svg>
                    </div>
                    <div v-show="seg.expanded" class="mini-thinking-body mono-font">{{ seg.content }}</div>
                  </div>
                  <div v-else-if="seg.type === 'tool-group'" class="tool-group-block">
                    <div class="tool-group">
                      <div
                        v-for="(item, ti) in getToolGroupItems(seg.tools)"
                        :key="item.key || ti"
                        class="mini-tool-capsule mono-font"
                        :class="{ running: item.running, selected: isToolSelected(item) }"
                        @click="onToolGroupClick(item)"
                      >
                        <svg v-if="item.running" class="icon-spin" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v4m0 12v4M4.93 4.93l2.83 2.83m8.48 8.48l2.83 2.83M2 12h4m12 0h4M4.93 19.07l2.83-2.83m8.48-8.48l2.83-2.83"/></svg>
                        <svg v-else viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 11l3 3L22 4M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11"/></svg>
                        <span class="tool-name">{{ item.name }}</span>
                        <span v-if="item.count > 1" class="tool-args-summary">×{{ item.count }}</span><span v-else-if="getToolArgsSummary(item.tool.arguments)" class="tool-args-summary">{{ getToolArgsSummary(item.tool.arguments) }}</span>
                        <span v-if="item.count === 1 && item.tool.elapsed" class="tool-elapsed">{{ item.tool.elapsed }}</span>
                      </div>
                    </div>
                    <ToolDetailsPanel
                      v-if="selectedTool && selectedToolBelongsToSegment(seg.tools)"
                      :tool="selectedTool"
                      :visible="true"
                      @close="selectedTool = null"
                    />
                  </div>
                  <div v-else-if="seg.type === 'assistant-note'" class="assistant-note-block">
                    <span class="assistant-note-label">{{ $t('streamingMessage.executionNote') }}</span>
                    <span class="assistant-note-text">{{ seg.content }}</span>
                  </div>
                  <div v-else-if="seg.type === 'harness-feedback'" class="harness-feedback-note">
                    <span class="harness-feedback-label">{{ $t('streamingMessage.harnessFeedback') }}</span>
                    <span class="harness-feedback-text">{{ seg.content }}</span>
                  </div>
                </template>
                </div>
                </div>
              </div>
            </template>
          </template>
        </div>

        <!-- 思考指示器 -->
        <div v-if="thinkingStatus && !streamingContent" class="thinking-hint mono-font">
          <span>{{ thinkingStatus.icon }}</span> {{ thinkingStatus.text }}
        </div>

        <!-- 流式文本 -->
        <div v-if="streamingContent" class="assistant-bubble">
          <div class="msg-text-block" v-html="formattedContent"></div>
          <span class="cursor-blink"></span>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import ToolDetailsPanel from './ToolDetailsPanel.vue'
import TodoCard from './TodoCard.vue'
import JsonCodeBlock from './JsonCodeBlock.vue'
import { renderMarkdownSafe } from '../../utils/sanitize'

export default {
  name: 'StreamingMessage',
  components: { ToolDetailsPanel, TodoCard, JsonCodeBlock },
  props: {
    streamingContent: { type: String, default: '' },
    reasoningContent: { type: String, default: '' },
    thinkingStatus: { type: Object, default: null },
    nodeSteps: { type: Array, default: () => [] },
    todoItems: { type: Array, default: () => [] },
    processCollapsed: { type: Boolean, default: false },
  },
  emits: ['toggle-process-view'],
  data() {
    return { selectedTool: null }
  },
  computed: {
    currentTime() {
      const d = new Date()
      return d.toLocaleTimeString(this.$i18n?.locale || undefined, {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false,
      })
    },
    formattedContent() {
      if (!this.streamingContent) return ''
      return renderMarkdownSafe(this.streamingContent)
    },
    hasProcessDetails() {
      return this.nodeSteps.length > 0 || !!this.reasoningContent
    },
    processHasRunning() {
      return this.nodeSteps.some(step => step.status === 'running')
    },
    processHasFailed() {
      return this.nodeSteps.some(step => this.isStepFailed(step))
    },
    processSummaryState() {
      if (this.processHasFailed) return 'failed'
      if (this.processHasRunning) return 'running'
      return 'completed'
    },
    processSummary() {
      const stepCount = this.nodeSteps.length
      const totalMs = this.nodeSteps.reduce((sum, step) => sum + this.parseDurationToMs(step), 0)
      const detail = []
      if (stepCount) detail.push(this.$t('streamingMessage.processSteps', { count: stepCount }))
      if (totalMs > 0) detail.push(this.$t('streamingMessage.processElapsed', { duration: this.formatElapsed(totalMs) }))
      return {
        title: this.processHasFailed
          ? this.$t('streamingMessage.processFailed')
          : this.processHasRunning
            ? this.$t('streamingMessage.processRunning')
            : this.$t('streamingMessage.processCompleted'),
        detail: detail.join(' · ') || this.$t('streamingMessage.waitingMoreSteps'),
      }
    },
    groupedSteps() {
      const groups = []
      let currentGroup = null
      for (const step of this.nodeSteps) {
        if (step.parallelGroupId) {
          if (currentGroup && currentGroup.groupId === step.parallelGroupId) {
            currentGroup.steps.push(step)
          } else {
            currentGroup = { groupId: step.parallelGroupId, isParallel: true, steps: [step] }
            groups.push(currentGroup)
          }
        } else {
          currentGroup = null
          groups.push({ groupId: null, isParallel: false, steps: [step] })
        }
      }
      return groups
    },
  },
  methods: {
    isStepRunning(step) {
      return String(step?.status || '').toLowerCase() === 'running'
    },
    isStepFailed(step) {
      const status = String(step?.status || '').toLowerCase()
      return !!step?.error || ['failed', 'error', 'cancelled', 'canceled', 'timeout'].includes(status)
    },
    isStepCompleted(step) {
      return !!step && !this.isStepRunning(step) && !this.isStepFailed(step)
    },
    stepTimelineClass(step) {
      return {
        running: this.isStepRunning(step),
        failed: this.isStepFailed(step),
        completed: this.isStepCompleted(step),
      }
    },
    onToolClick(tool) {
      this.selectedTool = this.selectedTool === tool ? null : tool
    },
    onToolGroupClick(item) {
      const target = item.count > 1
        ? { id: item.key, name: item.name, tools: item.tools, isGroup: true }
        : item.tool
      this.selectedTool = this.isSameSelectedTool(target) ? null : target
    },
    isSameSelectedTool(tool) {
      if (!this.selectedTool || !tool) return false
      if (this.selectedTool.isGroup || tool.isGroup) {
        return this.selectedTool.isGroup && tool.isGroup && this.selectedTool.id === tool.id
      }
      return this.selectedTool === tool
    },
    isToolSelected(item) {
      if (!this.selectedTool || !item) return false
      if (this.selectedTool.isGroup) return this.selectedTool.id === item.key
      return this.selectedTool === item.tool
    },
    selectedToolBelongsToSegment(tools) {
      if (!this.selectedTool) return false
      if (this.selectedTool.isGroup) {
        return this.getToolGroupItems(tools).some(item => item.key === this.selectedTool.id)
      }
      return (tools || []).some(t => t === this.selectedTool)
    },
    parseDurationToMs(step) {
      if (step?.elapsed) {
        const text = String(step.elapsed).trim()
        if (text.endsWith('ms')) {
          const value = Number.parseFloat(text.replace('ms', ''))
          return Number.isFinite(value) ? value : 0
        }
        if (text.endsWith('s')) {
          const value = Number.parseFloat(text.replace('s', ''))
          return Number.isFinite(value) ? value * 1000 : 0
        }
      }
      if (step?.startTime) {
        return Math.max(0, Date.now() - step.startTime)
      }
      return 0
    },
    formatElapsed(ms) {
      if (!ms) return ''
      if (ms < 1000) return `${Math.round(ms)}ms`
      if (ms < 60000) return `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)}s`
      const minutes = Math.floor(ms / 60000)
      const seconds = ((ms % 60000) / 1000).toFixed(1)
      return `${minutes}m ${seconds}s`
    },
    formatJson(obj) {
      if (!obj) return ''
      try { return JSON.stringify(obj, null, 2) } catch { return String(obj) }
    },
    getToolGroupItems(tools) {
      const groups = []
      const index = new Map()
      for (const tool of tools || []) {
        const name = tool?.name || 'tool'
        let item = index.get(name)
        if (!item) {
          item = { key: name, name, count: 0, tool, tools: [], running: false, failed: false }
          index.set(name, item)
          groups.push(item)
        }
        item.count += 1
        item.tools.push(tool)
        if (tool?.status === 'running') item.running = true
        if (tool?.status === 'failed') item.failed = true
      }
      groups.forEach(item => {
        const ids = item.tools.map((tool, index) => tool?.id || `${item.name}-${index}`).join('|')
        item.key = `${item.name}:${ids}`
      })
      return groups
    },
    getDisplaySegments(step) {
      if (!step.segments || !step.segments.length) {
        return step.toolCalls && step.toolCalls.length ? [{ type: 'tool-group', tools: step.toolCalls }] : []
      }
      const result = []
      let currentToolGroup = null
      for (const seg of step.segments) {
        if (seg.type === 'reasoning') {
          currentToolGroup = null
          result.push(seg)
        } else if (seg.type === 'tool') {
          if (!currentToolGroup) {
            currentToolGroup = { type: 'tool-group', tools: [] }
            result.push(currentToolGroup)
          }
          currentToolGroup.tools.push(seg)
        } else if (seg.type === 'assistant-note' || seg.type === 'harness-feedback') {
          currentToolGroup = null
          result.push(seg)
        }
      }
      return result
    },
    getToolArgsSummary(args) {
      if (!args) return ''
      try {
        const p = typeof args === 'string' ? JSON.parse(args) : args
        const k = Object.keys(p)
        if (!k.length) return ''
        const v = p[k[0]]
        if (typeof v === 'string' && v.length < 30) return `("${v}")`
        return `(${k.join(', ')})`
      } catch { return '' }
    },
  },
}
</script>

<style scoped>
.mono-font { font-family: var(--font-mono, ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace); }
.message-wrapper { width: 100%; display: flex; justify-content: center; padding: 0 24px; }
.message { width: 100%; max-width: 880px; display: flex; gap: 16px; margin-bottom: 36px; }
.message-avatar { width: 28px; height: 28px; border-radius: 8px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; font-weight: 600; font-size: 12px; margin-top: 2px; background: var(--bg-app, #fff); color: var(--accent-main, #3b82f6); border: 1px solid var(--border-base, #e4e4e7); box-shadow: var(--shadow-sm); }
.message-content { display: flex; flex-direction: column; align-items: flex-start; max-width: calc(100% - 44px); width: 100%; gap: 8px; }
.message-header { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--text-muted, #a1a1aa); margin-bottom: -2px; line-height: 1.5; }
.agent-name { font-weight: 500; color: var(--text-main, #18181b); }

.agent-step { width: 100%; max-width: 640px; display: flex; flex-direction: column; gap: 8px; padding-left: 14px; border-left: 1.5px solid var(--accent-main, #3b82f6); margin: 4px 0 12px; }
.agent-step.active { border-left-color: var(--accent-main, #3b82f6); }

/* 节点头 */
.step-header { display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 500; color: var(--accent-main, #3b82f6); cursor: pointer; user-select: none; }

/* 思考块 — 可折叠 */
.mini-thinking { font-size: 13px; color: var(--text-sec, #52525b); cursor: pointer; display: flex; flex-direction: column; gap: 4px; }
.mini-thinking-header { display: flex; align-items: center; gap: 8px; font-weight: 500; transition: color 0.2s; }
.mini-thinking-header:hover { color: var(--text-main, #18181b); }
.mini-thinking-body { display: none; padding: 2px 0 4px 14px; font-size: 13px; color: var(--text-muted, #a1a1aa); line-height: 1.5; border-left: 1px dashed var(--border-dark, #d4d4d8); margin-left: 6px; white-space: pre-wrap; word-break: break-word; max-height: 300px; overflow-y: auto; }
.mini-thinking.expanded .mini-thinking-body { display: block; }

/* 展开箭头 */
.expand-chevron { transition: transform 0.2s; color: var(--text-muted, #a1a1aa); flex-shrink: 0; margin-left: auto; }
.expand-chevron.rotated { transform: rotate(90deg); }

/* 并行组 */
.parallel-group { display: flex; flex-direction: column; gap: 4px; padding: 6px 8px; border: 1px dashed var(--border-dark, #d4d4d8); border-radius: 8px; margin: 2px 0; }
.parallel-label { font-size: 11px; color: var(--text-muted, #a1a1aa); display: flex; align-items: center; gap: 4px; margin-bottom: 2px; }
.parallel-steps { display: flex; flex-wrap: wrap; gap: 8px; }
.parallel-step { flex: 1; min-width: 180px; }

/* 节点 IO 面板 */
.node-io-panel { background: var(--bg-terminal, #0f172a); border-radius: 8px; padding: 10px 12px; margin: 4px 0 6px 22px; font-size: 12px; line-height: 1.5; overflow: hidden; }
.io-section { margin-bottom: 8px; }
.io-section:last-child { margin-bottom: 0; }
.io-label { color: #60a5fa; font-weight: 600; font-size: 11px; }
.io-label.io-error { color: #f87171; }
.io-content { color: #e2e8f0; margin: 2px 0 0 0; padding: 0; white-space: pre-wrap; word-break: break-all; font-size: 12px; background: transparent; border: none; overflow-x: auto; max-height: 200px; overflow-y: auto; }
.io-content.io-error { color: #fca5a5; }

/* 工具胶囊 */
.tool-group { display: flex; flex-wrap: wrap; gap: 6px; margin: 2px 0; }
.mini-tool-capsule { display: flex; align-items: center; gap: 6px; padding: 4px 10px; background: var(--bg-app, #fff); border: 1px solid var(--border-base, #e4e4e7); border-radius: var(--radius-sm, 8px); font-size: 12px; color: var(--text-sec, #52525b); cursor: pointer; transition: all 0.2s; box-shadow: var(--shadow-sm); }
.mini-tool-capsule:hover { border-color: var(--border-dark, #d4d4d8); box-shadow: var(--shadow-md); }
.mini-tool-capsule.running { border-color: var(--accent-bg, #dbeafe); background: var(--accent-bg, #dbeafe); color: var(--accent-main, #3b82f6); box-shadow: none; }
.mini-tool-capsule.selected { border-color: var(--accent-main, #3b82f6); box-shadow: 0 0 0 1px var(--accent-main, #3b82f6); color: var(--text-main, #18181b); }
.tool-name { font-weight: 500; font-family: var(--font-mono, ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace); font-size: 11.5px; }

.tool-status-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.dot-green { background: #10b981; }
.dot-red { background: #ef4444; }

.thinking-hint { font-size: 13px; color: var(--text-muted, #a1a1aa); display: flex; align-items: center; gap: 6px; }

.msg-text-block { line-height: 1.65; color: var(--text-main, #18181b); font-size: 15px; width: 100%; word-break: break-word; }
.msg-text-block :deep(code) { background: var(--border-light, #f1f1f1); padding: 2px 5px; border-radius: 4px; font-family: var(--font-mono, ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace); font-size: 13.5px; color: var(--accent-main, #3b82f6); }
.msg-text-block :deep(pre) { background: var(--bg-terminal, #0f172a); color: #e2e8f0; padding: 14px 16px; border-radius: var(--radius-md, 12px); overflow-x: auto; margin: 14px 0; border: 1px solid #1e293b; }
.msg-text-block :deep(pre code) { background: transparent; padding: 0; color: inherit; font-size: 13px; }
.msg-text-block :deep(p) { margin: 10px 0; }
.msg-text-block :deep(ul), .msg-text-block :deep(ol) { margin: 10px 0; padding-left: 24px; line-height: 1.8; }
.msg-text-block :deep(blockquote) { border-left: 3px solid var(--border-dark, #d4d4d8); padding-left: 14px; color: var(--text-sec, #52525b); margin: 10px 0; }
.msg-text-block :deep(table) { border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 14px; }
.msg-text-block :deep(table thead) { background: var(--bg-hover, #f1f1f1); }
.msg-text-block :deep(table th) { padding: 10px 12px; text-align: left; font-weight: 600; border: 1px solid var(--border-base, #e4e4e7); }
.msg-text-block :deep(table td) { padding: 10px 12px; border: 1px solid var(--border-base, #e4e4e7); }
.msg-text-block :deep(table tr:hover) { background: var(--bg-hover, #f1f1f1); }
.msg-text-block :deep(img) {
  display: block;
  max-width: min(100%, 720px);
  max-height: 520px;
  object-fit: contain;
  margin: 12px 0;
  border-radius: 14px;
  border: 1px solid var(--border-base, #e4e4e7);
  background: var(--bg-app, #fff);
  box-shadow: 0 18px 44px -34px rgba(15, 23, 42, 0.42);
}
.msg-text-block :deep(a:has(img)) {
  display: inline-block;
  max-width: 100%;
}

@keyframes spin { 100% { transform: rotate(360deg); } }
.icon-spin { animation: spin 1s linear infinite; }
@keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }
.cursor-blink { display: inline-block; width: 2px; height: 16px; background-color: var(--accent-main, #3b82f6); vertical-align: middle; margin-left: 2px; animation: blink 1s step-end infinite; }

.assistant-bubble {
  width: min(100%, 760px);
  background: linear-gradient(180deg, rgba(239, 246, 255, 0.96), rgba(255, 255, 255, 0.98));
  border: 1px solid rgba(191, 219, 254, 0.95);
  border-radius: 20px 20px 20px 10px;
  padding: 16px 18px;
  box-shadow: 0 24px 46px -34px rgba(37, 99, 235, 0.28);
}

.assistant-bubble .msg-text-block {
  margin-top: 0;
}

.assistant-bubble .cursor-blink {
  margin-left: 4px;
}

.process-summary-card {
  width: min(100%, 760px);
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border-radius: 16px;
  border: 1px solid rgba(59, 130, 246, 0.16);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(244, 248, 255, 0.98));
  cursor: pointer;
  box-shadow: 0 18px 36px -30px rgba(59, 130, 246, 0.3);
}

.process-summary-marker {
  width: 22px;
  display: flex;
  justify-content: center;
}

.process-summary-dot {
  width: 16px;
  height: 16px;
  border-radius: 999px;
  background: #94a3b8;
  box-shadow: 0 0 0 6px rgba(148, 163, 184, 0.12);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: white;
}

.process-summary-dot.running,
.timeline-dot.running {
  background: var(--accent-main, #3b82f6);
  box-shadow: 0 0 0 6px rgba(59, 130, 246, 0.14);
  animation: timelinePulse 1.8s ease-in-out infinite;
}

.process-summary-dot.completed,
.timeline-dot.completed {
  background: #22c55e;
  box-shadow: 0 0 0 6px rgba(34, 197, 94, 0.14);
}

.process-summary-dot.failed,
.timeline-dot.failed {
  background: #ef4444;
  box-shadow: 0 0 0 6px rgba(239, 68, 68, 0.14);
}

.summary-state-icon,
.timeline-state-icon {
  width: 10px;
  height: 10px;
}

.process-summary-body {
  flex: 1;
  min-width: 0;
}

.process-summary-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-main, #18181b);
}

.process-summary-meta {
  margin-top: 2px;
  font-size: 11px;
  color: var(--text-muted, #a1a1aa);
}

.agent-step {
  width: min(100%, 760px);
  max-width: none;
  position: relative;
  padding-left: 0;
  border-left: none;
  gap: 12px;
}

.agent-step::before {
  content: '';
  position: absolute;
  left: 11px;
  top: 12px;
  bottom: 12px;
  width: 1.5px;
  background: linear-gradient(180deg, rgba(148, 163, 184, 0.18), rgba(148, 163, 184, 0.68), rgba(148, 163, 184, 0.18));
}

.timeline-entry {
  position: relative;
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr);
  gap: 12px;
}

.timeline-marker {
  display: flex;
  justify-content: center;
  position: relative;
  z-index: 1;
}

.timeline-dot {
  margin-top: 10px;
  width: 12px;
  height: 12px;
  border-radius: 999px;
  background: #cbd5e1;
  border: 2px solid rgba(255, 255, 255, 0.96);
  box-shadow: 0 0 0 4px rgba(203, 213, 225, 0.22);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: white;
}

.parallel-dot {
  background: #f59e0b;
  box-shadow: 0 0 0 4px rgba(245, 158, 11, 0.16);
}

.timeline-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
}

.parallel-card {
  padding: 12px 14px 14px;
  border-radius: 16px;
  border: 1px solid rgba(245, 158, 11, 0.18);
  background: linear-gradient(180deg, rgba(255, 251, 235, 0.88), rgba(255, 255, 255, 0.96));
  box-shadow: 0 18px 34px -30px rgba(245, 158, 11, 0.28);
}

.parallel-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-size: 11px;
  color: #92400e;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.parallel-label-main {
  display: flex;
  align-items: center;
  gap: 6px;
}

.parallel-steps {
  gap: 12px;
}

.parallel-step {
  min-width: 220px;
}

.step-card {
  padding: 12px 14px;
  border-radius: 16px;
  border: 1px solid rgba(228, 228, 231, 0.92);
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 18px 36px -32px rgba(15, 23, 42, 0.26);
}

.step-card.running {
  border-color: rgba(59, 130, 246, 0.28);
  background: linear-gradient(180deg, rgba(239, 246, 255, 0.92), rgba(255, 255, 255, 0.98));
}

.step-card.failed {
  border-color: rgba(239, 68, 68, 0.22);
  background: linear-gradient(180deg, rgba(254, 242, 242, 0.88), rgba(255, 255, 255, 0.98));
}

.step-header,
.mini-thinking-header {
  gap: 10px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-main, #18181b);
}

.mini-thinking-body {
  margin-top: 10px;
  padding: 12px 14px;
  border-radius: 14px;
  border: 1px dashed rgba(148, 163, 184, 0.45);
  background: rgba(248, 250, 252, 0.96);
  color: var(--text-sec, #52525b);
  max-height: 260px;
  overflow: auto;
}

.node-io-panel {
  margin: 10px 0 0;
  padding: 0;
  background: transparent;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.io-section {
  margin: 0;
}

.tool-group-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 12px;
}

.tool-group {
  gap: 8px;
  margin: 0;
}

.mini-thinking {
  margin-top: 12px;
}

.mini-thinking:first-child,
.tool-group-block:first-child {
  margin-top: 0;
}
.assistant-note-block {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin: 7px 0 4px 22px;
  padding: 8px 10px;
  border-left: 2px solid rgba(148, 163, 184, 0.42);
  border-radius: 0 10px 10px 0;
  background: rgba(248, 250, 252, 0.9);
  color: var(--text-sec, #52525b);
  font-size: 12px;
  line-height: 1.5;
}
.assistant-note-label {
  flex: 0 0 auto;
  margin-top: 1px;
  padding: 1px 6px;
  border-radius: 999px;
  background: rgba(100, 116, 139, 0.1);
  color: #64748b;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.02em;
}
.assistant-note-text {
  min-width: 0;
  word-break: break-word;
}
.harness-feedback-note {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin: 7px 0 4px 22px;
  padding: 8px 10px;
  border-left: 2px solid rgba(59, 130, 246, 0.35);
  border-radius: 0 10px 10px 0;
  background: rgba(239, 246, 255, 0.72);
  color: var(--text-sec, #52525b);
  font-size: 12px;
  line-height: 1.5;
}
.harness-feedback-label {
  flex: 0 0 auto;
  margin-top: 1px;
  padding: 1px 6px;
  border-radius: 999px;
  background: rgba(59, 130, 246, 0.1);
  color: var(--accent-main, #3b82f6);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.02em;
}
.harness-feedback-text {
  min-width: 0;
  word-break: break-word;
}

.mini-tool-capsule {
  padding: 6px 12px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.96);
}

.mini-tool-capsule.running {
  background: rgba(219, 234, 254, 0.88);
}

.tool-args-summary {
  font-size: 11px;
  color: var(--text-muted, #a1a1aa);
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-elapsed {
  font-size: 10px;
  color: var(--text-muted, #a1a1aa);
  margin-left: auto;
  flex-shrink: 0;
}

@keyframes timelinePulse {
  0%, 100% {
    transform: scale(1);
    box-shadow: 0 0 0 6px rgba(59, 130, 246, 0.14);
  }
  50% {
    transform: scale(1.08);
    box-shadow: 0 0 0 9px rgba(59, 130, 246, 0.08);
  }
}

@media (max-width: 768px) {
  .assistant-bubble,
  .process-summary-card,
  .agent-step {
    width: 100%;
  }

  .timeline-entry {
    grid-template-columns: 20px minmax(0, 1fr);
    gap: 10px;
  }

  .parallel-step {
    min-width: 100%;
  }
}
</style>
