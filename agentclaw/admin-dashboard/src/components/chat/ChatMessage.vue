<template>
  <div class="message-wrapper">
    <!-- 用户消息 -->
    <div v-if="msg.role === 'user'" class="message user">
      <div class="user-avatar-stack">
        <div class="message-avatar">U</div>
        <span class="user-timestamp mono-font">{{ formatTime(msg.timestamp) }}</span>
      </div>
      <div class="message-content">
        <div class="user-bubble-row">
          <div class="user-bubble-stack">
            <!-- 编辑模式 -->
            <div v-if="isEditing" class="edit-area">
              <textarea ref="editInput" v-model="editText" class="edit-textarea" @input="autoResizeTextarea" @keydown.ctrl.enter="confirmEdit" @keydown.esc="cancelEdit"></textarea>
              <div class="edit-actions">
                <button class="edit-btn cancel" @click="cancelEdit">{{ $t('common.cancel') }}</button>
                <button class="edit-btn confirm" @click="confirmEdit">{{ $t('chatMessage.send') }}</button>
              </div>
            </div>
            <!-- 正常显示 -->
            <template v-else>
              <div class="message-bubble">{{ msg.content }}</div>
              <div class="user-actions-inline">
                <button v-if="!msg.isInterruptResponse" class="action-btn" :title="$t('chatMessage.editRetry')" @click="startEdit">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                </button>
                <button class="action-btn" :class="{ copied: msg.copied }" :title="$t('common.copy')" @click="$emit('copy')">
                  <svg v-if="!msg.copied" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>
                  <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6L9 17l-5-5"/></svg>
                </button>
              </div>
            </template>
          </div>
        </div>
      </div>
    </div>

    <!-- Welcome 消息 -->
    <div v-else-if="msg.role === 'welcome'" class="message welcome-msg">
      <div class="welcome-bubble">
        <span class="welcome-icon">✨</span>
        <span>{{ msg.content }}</span>
      </div>
    </div>

    <!-- 上下文摘要消息 -->
    <div v-else-if="msg.is_summary" class="message summary-msg">
      <div class="summary-bubble">
        <div class="summary-header" @click="summaryExpanded = !summaryExpanded">
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 21H5a2 2 0 01-2-2V5a2 2 0 012-2h11l5 5v11a2 2 0 01-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>
          <span>{{ $t('chatMessage.contextSummary') }}</span>
          <span class="summary-meta mono-font" v-if="msg.original_message_count">{{ $t('chatMessage.compressedMessages', { count: msg.original_message_count }) }}</span>
          <svg class="expand-chevron" :class="{ rotated: summaryExpanded }" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18l6-6-6-6"/></svg>
        </div>
        <div v-if="summaryExpanded" class="summary-body" v-html="formattedSummary"></div>
      </div>
    </div>

    <!-- 助手消息 -->
    <div v-else class="message">
      <div class="message-avatar">AC</div>
      <div class="message-content">
        <div class="message-header">
          <span class="agent-name">AgentClaw</span>
          <span class="mono-font">{{ formatTime(msg.timestamp) }}</span>
        </div>

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

        <!-- 执行步骤 (agent-step) -->
        <div v-if="hasSteps && !processCollapsed" class="agent-step">
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
                    <span>{{ $t('chatMessage.parallelBranches') }}</span>
                  </div>
                  <span>{{ $t('chatMessage.stepCount', { count: group.steps.length }) }}</span>
                </div>
                <div class="parallel-steps">
                  <div v-for="(step, si) in group.steps" :key="step.id || si" class="parallel-step">
                    <div class="mini-thinking timeline-node-card" :class="{ expanded: step.expanded, running: step.status === 'running', failed: step.error || step.status === 'failed' || step.status === 'error' }">
                    <div class="mini-thinking-header" @click="step.expanded = !step.expanded">
                      <svg v-if="isStepRunning(step)" class="icon-spin" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M12 2v4m0 12v4M4.93 4.93l2.83 2.83m8.48 8.48l2.83 2.83M2 12h4m12 0h4M4.93 19.07l2.83-2.83m8.48-8.48l2.83-2.83"/>
                      </svg>
                      <svg v-else-if="isStepFailed(step)" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M12 8v5" />
                        <path d="M12 16h.01" />
                        <circle cx="12" cy="12" r="9" />
                      </svg>
                      <svg v-else viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M20 6L9 17l-5-5" />
                      </svg>
                      <span>{{ step.name }}{{ step.elapsed ? ` (${step.elapsed})` : '' }}</span>
                      <svg class="expand-chevron" :class="{ rotated: step.expanded }" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18l6-6-6-6"/></svg>
                    </div>
                    <div v-if="step.expanded && (step.inputs || step.outputs || step.error)" class="node-io-panel mono-font">
                      <div v-if="step.inputs && Object.keys(step.inputs).length" class="io-section">
                        <JsonCodeBlock :label="$t('chatMessage.input')" :value="step.inputs" />
                      </div>
                      <div v-if="step.outputs && Object.keys(step.outputs).length" class="io-section">
                        <JsonCodeBlock :label="$t('chatMessage.output')" :value="step.outputs" />
                      </div>
                      <div v-if="step.error" class="io-section">
                        <JsonCodeBlock :label="$t('chatMessage.error')" :value="step.error" tone="error" />
                      </div>
                    </div>
                  </div>
                  <!-- 交叉显示 segments -->
                  <template v-for="(seg, si2) in getDisplaySegments(step)" :key="si2">
                    <div v-if="seg.type === 'reasoning'" class="mini-thinking" :class="{ expanded: seg.expanded }">
                      <div class="mini-thinking-header" @click="seg.expanded = !seg.expanded">
                        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1m-1.636 5.636l-.707-.707M12 21v-1m-5.636-1.636l.707-.707M3 12h1m1.636-5.636l.707.707M12 5a7 7 0 100 14 7 7 0 000-14z"/></svg>
                        <span>{{ $t('chatMessage.thinking') }}</span>
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
                          :class="{ selected: isToolSelected(item), running: item.running }"
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
                <div class="mini-thinking timeline-node-card" :class="{ expanded: step.expanded, running: step.status === 'running', failed: step.error || step.status === 'failed' || step.status === 'error' }">
                  <div class="mini-thinking-header" @click="step.expanded = !step.expanded">
                    <svg v-if="isStepRunning(step)" class="icon-spin" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M12 2v4m0 12v4M4.93 4.93l2.83 2.83m8.48 8.48l2.83 2.83M2 12h4m12 0h4M4.93 19.07l2.83-2.83m8.48-8.48l2.83-2.83"/>
                    </svg>
                    <svg v-else-if="isStepFailed(step)" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M12 8v5" />
                      <path d="M12 16h.01" />
                      <circle cx="12" cy="12" r="9" />
                    </svg>
                    <svg v-else viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M20 6L9 17l-5-5" />
                    </svg>
                    <span>{{ step.name }}{{ step.elapsed ? ` (${step.elapsed})` : '' }}</span>
                    <svg class="expand-chevron" :class="{ rotated: step.expanded }" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18l6-6-6-6"/></svg>
                  </div>
                  <div v-if="step.expanded && (step.inputs || step.outputs || step.error)" class="node-io-panel mono-font">
                    <div v-if="step.inputs && Object.keys(step.inputs).length" class="io-section">
                      <JsonCodeBlock :label="$t('chatMessage.input')" :value="step.inputs" />
                    </div>
                    <div v-if="step.outputs && Object.keys(step.outputs).length" class="io-section">
                      <JsonCodeBlock :label="$t('chatMessage.output')" :value="step.outputs" />
                    </div>
                    <div v-if="step.error" class="io-section">
                      <JsonCodeBlock :label="$t('chatMessage.error')" :value="step.error" tone="error" />
                    </div>
                  </div>
                </div>
                <!-- 交叉显示 segments -->
                <template v-for="(seg, si2) in getDisplaySegments(step)" :key="si2">
                  <div v-if="seg.type === 'reasoning'" class="mini-thinking" :class="{ expanded: seg.expanded }">
                    <div class="mini-thinking-header" @click="seg.expanded = !seg.expanded">
                      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1m-1.636 5.636l-.707-.707M12 21v-1m-5.636-1.636l.707-.707M3 12h1m1.636-5.636l.707.707M12 5a7 7 0 100 14 7 7 0 000-14z"/></svg>
                      <span>{{ $t('chatMessage.thinking') }}</span>
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
                        :class="{ selected: isToolSelected(item), running: item.running }"
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
            </template>
          </template>
        </div>

        <!-- 直接工具调用 (无 nodeSteps 时) -->
        <div v-else-if="hasToolCalls && !processCollapsed" class="agent-step">
          <div class="tool-group">
            <div
              v-for="(item, ti) in getToolGroupItems(msg.toolCalls)"
              :key="item.key || ti"
              class="mini-tool-capsule mono-font"
              :class="{ selected: isToolSelected(item) }"
              @click="onToolGroupClick(item)"
            >
              <span class="tool-status-dot" :class="item.failed ? 'dot-red' : 'dot-green'"></span>
              <span class="tool-name">{{ item.name }}</span>
              <span v-if="item.count > 1" class="tool-args-summary">×{{ item.count }}</span>
            </div>
          </div>
          <ToolDetailsPanel
            v-if="selectedTool"
            :tool="selectedTool"
            :visible="!!selectedTool"
            @close="selectedTool = null"
          />
        </div>

        <!-- 思考过程 (仅向后兼容：老消息没有 segments 时显示) -->
        <div v-if="msg.reasoning && !hasSegments && !processCollapsed" class="mini-thinking legacy-reasoning-card" :class="{ expanded: msg.reasoningExpanded }">
          <div class="mini-thinking-header" @click="$emit('toggle-reasoning')">
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1m-1.636 5.636l-.707-.707M12 21v-1m-5.636-1.636l.707-.707M3 12h1m1.636-5.636l.707.707M12 5a7 7 0 100 14 7 7 0 000-14z"/>
            </svg>
            <span>{{ $t('chatMessage.reasoningProcess') }}</span>
          </div>
          <div class="mini-thinking-body mono-font">{{ msg.reasoning }}</div>
        </div>

        <!-- 消息正文 -->
        <div v-if="msg.content" class="assistant-bubble">
          <div class="msg-text-block" v-html="formattedContent"></div>
        </div>

        <!-- 审批按钮（内嵌在消息中） -->
        <div v-if="msg.pendingApproval" class="approval-actions">
          <button class="approval-btn approve" @click="$emit('approve', 'approve')">
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6L9 17l-5-5"/></svg>
            {{ $t('chatMessage.approve') }}
          </button>
          <button class="approval-btn reject" @click="$emit('approve', 'reject')">
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
            {{ $t('chatMessage.rejectRevision') }}
          </button>
        </div>
        <div v-else-if="msg.approvalResult" class="approval-result" :class="msg.approvalResult">
          {{ msg.approvalResult === 'approve' ? $t('chatMessage.approved') : $t('chatMessage.rejected') }}
        </div>

        <!-- 底部操作栏 -->
        <div class="message-footer">
          <div class="message-meta">
            <template v-if="msg.prompt_tokens || msg.completion_tokens">
              <div class="token-stats mono-font">
                <div class="token-item" :title="$t('chatMessage.inputTokens')">
                  <svg class="token-icon" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 10 20 15 15 20"></polyline><path d="M4 4v7a4 4 0 0 0 4 4h12"></path></svg>
                  <span>{{ $t('chatMessage.inputTokensCount', { count: formatTokens(msg.prompt_tokens) }) }}</span>
                </div>
                <div class="token-item" :title="$t('chatMessage.outputTokens')">
                  <svg class="token-icon" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg>
                  <span>{{ $t('chatMessage.outputTokensCount', { count: formatTokens(msg.completion_tokens) }) }}</span>
                </div>
              </div>
            </template>
          </div>
          <div class="msg-actions">
            <button class="action-btn" :class="{ copied: msg.copied }" :title="$t('common.copy')" @click="$emit('copy')">
              <svg v-if="!msg.copied" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>
              <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6L9 17l-5-5"/></svg>
            </button>
            <button
              v-if="ttsAvailable && msg.content"
              class="action-btn"
              :class="{ active: ttsState === 'playing', loading: ttsState === 'generating' }"
              :disabled="ttsState === 'generating'"
              :title="ttsState === 'generating' ? $t('chatMessage.generatingSpeech') : ttsState === 'playing' ? $t('chatMessage.stopSpeech') : $t('chatMessage.speak')"
              @click="$emit('speak')"
            >
              <svg v-if="ttsState === 'generating'" class="icon-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v4m0 12v4M4.93 4.93l2.83 2.83m8.48 8.48l2.83 2.83M2 12h4m12 0h4M4.93 19.07l2.83-2.83m8.48-8.48l2.83-2.83"/></svg>
              <svg v-else-if="ttsState === 'playing'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/></svg>
              <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.54 8.46a5 5 0 010 7.07"/></svg>
            </button>
            <button class="action-btn" :class="{ active: msg.feedback === 'like' }" :title="$t('chatMessage.positiveFeedback')" @click="$emit('feedback', 'like')">
              <svg viewBox="0 0 24 24" :fill="msg.feedback === 'like' ? 'currentColor' : 'none'" stroke="currentColor" stroke-width="2"><path d="M14 9V5a3 3 0 00-3-3l-4 9v11h11.28a2 2 0 002-1.7l1.38-9a2 2 0 00-2-2.3zM7 22H4a2 2 0 01-2-2v-7a2 2 0 012-2h3"/></svg>
            </button>
            <button class="action-btn" :class="{ active: msg.feedback === 'dislike' }" :title="$t('chatMessage.negativeFeedback')" @click="$emit('feedback', 'dislike')">
              <svg viewBox="0 0 24 24" :fill="msg.feedback === 'dislike' ? 'currentColor' : 'none'" stroke="currentColor" stroke-width="2"><path d="M10 15v4a3 3 0 003 3l4-9V2H5.72a2 2 0 00-2 1.7l-1.38 9a2 2 0 002 2.3zm7-13h2.67A2.31 2.31 0 0122 4v7a2.31 2.31 0 01-2.33 2H17"/></svg>
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import ToolDetailsPanel from './ToolDetailsPanel.vue'
import JsonCodeBlock from './JsonCodeBlock.vue'
import { formatTime as formatLocalizedTime } from '../../composables/useFormatters'
import { renderMarkdownSafe } from '../../utils/sanitize'

export default {
  name: 'ChatMessage',
  components: { ToolDetailsPanel, JsonCodeBlock },
  props: {
    msg: { type: Object, required: true },
    processCollapsed: { type: Boolean, default: false },
    ttsAvailable: { type: Boolean, default: false },
    ttsState: { type: String, default: '' },
  },
  emits: ['copy', 'edit', 'feedback', 'toggle-reasoning', 'approve', 'toggle-process-view', 'speak'],
  data() {
    return { selectedTool: null, summaryExpanded: !!this.msg.is_summary, isEditing: false, editText: '' }
  },
  computed: {
    hasSteps() {
      return this.msg.nodeSteps && this.msg.nodeSteps.length > 0
    },
    hasToolCalls() {
      return this.msg.toolCalls && this.msg.toolCalls.length > 0 && !this.hasSteps
    },
    hasSegments() {
      return this.msg.nodeSteps && this.msg.nodeSteps.some(s => s.segments && s.segments.length > 0)
    },
    hasProcessDetails() {
      return this.hasSteps || this.hasToolCalls || (!!this.msg.reasoning && !this.hasSegments)
    },
    processHasRunning() {
      return !!(this.msg.nodeSteps || []).some(step => step.status === 'running')
        || !!(this.msg.toolCalls || []).some(tool => tool.status === 'running')
    },
    processHasFailed() {
      return !!(this.msg.nodeSteps || []).some(step => this.isStepFailed(step))
        || !!(this.msg.toolCalls || []).some(tool => ['failed', 'error', 'cancelled'].includes(String(tool.status || '').toLowerCase()))
    },
    processSummaryState() {
      if (this.processHasFailed) return 'failed'
      if (this.processHasRunning) return 'running'
      return 'completed'
    },
    processSummary() {
      const stepCount = (this.msg.nodeSteps || []).length
      const toolCount = (this.msg.toolCalls || []).length
      const totalMs = (this.msg.nodeSteps || []).reduce((sum, step) => sum + this.parseDurationToMs(step), 0)
      const detail = []
      if (stepCount) detail.push(this.$t('chatMessage.processSteps', { count: stepCount }))
      else if (toolCount) detail.push(this.$t('chatMessage.processTools', { count: toolCount }))
      else detail.push(this.$t('chatMessage.singleThought'))
      if (totalMs > 0) detail.push(this.$t('chatMessage.processElapsed', { duration: this.formatElapsed(totalMs) }))
      return {
        title: this.processHasFailed
          ? this.$t('chatMessage.processFailed')
          : this.processHasRunning
            ? this.$t('chatMessage.processRunning')
            : this.$t('chatMessage.processCompleted'),
        detail: detail.join(' · '),
      }
    },
    formattedContent() {
      if (!this.msg.content || this.msg.role !== 'assistant') return ''
      return renderMarkdownSafe(this.msg.content)
    },
    formattedSummary() {
      if (!this.msg.content) return ''
      return renderMarkdownSafe(this.msg.content)
    },
    groupedSteps() {
      if (!this.msg.nodeSteps) return []
      const groups = []
      let currentGroup = null
      for (const step of this.msg.nodeSteps) {
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
    formatTime(ts) {
      if (!ts) return ''
      return formatLocalizedTime(ts, undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    },
    formatTokens(n) {
      if (!n) return '0'
      return n.toLocaleString()
    },
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
    autoResizeTextarea() {
      const ta = this.$refs.editInput
      if (!ta) return
      ta.style.height = 'auto'
      ta.style.height = ta.scrollHeight + 'px'
    },
    startEdit() {
      this.editText = this.msg.content || ''
      this.isEditing = true
      this.$nextTick(() => {
        const ta = this.$refs.editInput
        if (ta) { ta.focus(); this.autoResizeTextarea() }
      })
    },
    confirmEdit() {
      const text = this.editText.trim()
      if (!text) return
      this.isEditing = false
      this.$emit('edit', text)
    },
    cancelEdit() {
      this.isEditing = false
      this.editText = ''
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
        } else if (seg.type === 'assistant-note' || seg.type === 'harness-feedback' || seg.type === 'tool-separator') {
          currentToolGroup = null
          result.push(seg)
        }
      }
      return result
    },
    formatJson(obj) {
      if (!obj) return ''
      try { return JSON.stringify(obj, null, 2) } catch { return String(obj) }
    },
  },
}
</script>
<style scoped>
.mono-font { font-family: var(--font-mono, ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace); }
.message-wrapper { width: 100%; min-width: 0; display: flex; justify-content: center; padding: 0 24px; }
.message-wrapper:hover .msg-actions { opacity: 1; }
.message-wrapper:hover .token-stats { opacity: 1; }

.message { width: 100%; min-width: 0; max-width: 880px; display: flex; gap: 16px; margin-bottom: 36px; }
.message.user { flex-direction: row-reverse; }
.message.welcome-msg { justify-content: center; margin-bottom: 20px; }

.welcome-bubble { max-width: 100%; display: inline-flex; align-items: center; gap: 8px; padding: 10px 18px; background: var(--bg-hover, #f1f1f1); border-radius: 20px; font-size: 14px; color: var(--text-sec, #52525b); line-height: 1.5; overflow-wrap: anywhere; }

.message-avatar {
  width: 28px; height: 28px; border-radius: 8px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  font-weight: 600; font-size: 12px; margin-top: 2px;
}
.message.user .message-avatar { background: var(--text-main, #18181b); color: white; }
.message:not(.user) .message-avatar { background: var(--bg-app, #fff); color: var(--accent-main, #3b82f6); border: 1px solid var(--border-base, #e4e4e7); box-shadow: var(--shadow-sm); }

.user-avatar-stack {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  min-width: 32px;
}

.user-timestamp {
  font-size: 10px;
  line-height: 1;
  color: var(--text-muted, #a1a1aa);
}

.message-content { min-width: 0; display: flex; flex-direction: column; align-items: flex-start; max-width: calc(100% - 44px); width: 100%; gap: 8px; }
.message.user .message-content { align-items: flex-end; }

.message-header { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--text-muted, #a1a1aa); margin-bottom: -2px; line-height: 1.5; }
.message.user .message-header { flex-direction: row-reverse; }
.agent-name { font-weight: 500; color: var(--text-main, #18181b); }

.message-bubble { line-height: 1.6; color: var(--text-main, #18181b); font-size: 15px; display: inline-block; word-break: break-word; }
.message.user .message-bubble { background: var(--bg-user-msg, #f4f4f5); padding: 10px 16px; border-radius: 14px; border-top-right-radius: 4px; }

.user-bubble-row { max-width: 100%; min-width: 0; display: flex; align-items: flex-end; gap: 4px; flex-direction: row; }
.user-bubble-stack {
  max-width: 100%;
  min-width: 0;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 6px;
}

.user-actions-inline {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 2px 4px;
  opacity: 0;
  transform: translateY(-2px);
  transition: opacity 0.18s ease, transform 0.18s ease;
}

.message.user:hover .user-actions-inline {
  opacity: 1;
  transform: translateY(0);
}

.edit-area { width: min(100%, 880px); min-width: 0; display: flex; flex-direction: column; gap: 8px; }
.edit-textarea {
  width: 100%; min-height: 180px; max-height: 65vh; padding: 12px 16px; border: 1.5px solid var(--accent-main, #3b82f6);
  border-radius: 12px; font-size: 15px; line-height: 1.6; resize: vertical; outline: none; overflow-y: auto;
  font-family: inherit; color: var(--text-main, #18181b); background: var(--bg-app, #fff);
}
.edit-textarea:focus { box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.15); }
.edit-actions { display: flex; justify-content: flex-end; gap: 8px; flex-wrap: wrap; }
.edit-btn {
  padding: 5px 16px; border-radius: 8px; font-size: 13px; font-weight: 500;
  cursor: pointer; border: 1px solid transparent; transition: all 0.15s;
}
.edit-btn.cancel { background: var(--bg-hover, #f1f1f1); color: var(--text-sec, #52525b); border-color: var(--border-base, #e4e4e7); }
.edit-btn.cancel:hover { background: var(--border-base, #e4e4e7); }
.edit-btn.confirm { background: var(--accent-main, #3b82f6); color: white; }
.edit-btn.confirm:hover { background: #2563eb; }

.msg-text-block { line-height: 1.65; color: var(--text-main, #18181b); font-size: 15px; width: 100%; min-width: 0; word-break: break-word; overflow-wrap: anywhere; margin-top: 4px; }
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
.msg-text-block :deep(img), .summary-body :deep(img) {
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
.msg-text-block :deep(a:has(img)), .summary-body :deep(a:has(img)) {
  display: inline-block;
  max-width: 100%;
}

.message-footer { min-width: 0; display: flex; align-items: center; justify-content: space-between; width: 100%; min-height: 24px; margin-top: 2px; }
.message.user .message-footer { flex-direction: row-reverse; }
.msg-actions { display: flex; align-items: center; gap: 2px; opacity: 0; transition: opacity 0.2s; flex-shrink: 0; }
.action-btn {
  width: 28px; height: 28px; border: none; background: transparent; border-radius: 6px;
  cursor: pointer; display: flex; align-items: center; justify-content: center;
  color: var(--text-muted, #a1a1aa); transition: all 0.15s;
}
.action-btn:hover { background: var(--bg-hover, #f1f1f1); color: var(--text-sec, #52525b); }
.action-btn.active { color: var(--accent-main, #3b82f6); }
.action-btn.loading { color: var(--accent-main, #3b82f6); }
.action-btn:disabled { cursor: default; opacity: 0.85; }
.action-btn.copied { color: var(--success-color, #10b981); }
.action-btn svg { width: 14px; height: 14px; }
.footer-divider { width: 1px; height: 12px; background: var(--border-base, #e4e4e7); margin: 0 8px; }
.token-stats { min-width: 0; display: flex; align-items: center; gap: 8px; font-size: 11px; color: var(--text-muted, #a1a1aa); opacity: 0.6; transition: opacity 0.2s; }
.token-item { min-width: 0; display: flex; align-items: center; gap: 5px; }
.token-icon { color: var(--text-muted, #a1a1aa); }

/* Agent Step */
.agent-step { width: 100%; max-width: 640px; display: flex; flex-direction: column; gap: 6px; padding-left: 14px; border-left: 1.5px solid var(--border-base, #e4e4e7); margin: 4px 0 12px; }
.mini-thinking { font-size: 13px; color: var(--text-sec, #52525b); cursor: pointer; display: flex; flex-direction: column; gap: 4px; }
.mini-thinking-header { min-width: 0; display: flex; align-items: center; gap: 8px; font-weight: 500; transition: color 0.2s; }
.mini-thinking-header span { min-width: 0; overflow-wrap: anywhere; }
.mini-thinking-header:hover { color: var(--text-main, #18181b); }
.mini-thinking-body { display: none; padding: 2px 0 4px 14px; font-size: 13px; color: var(--text-muted, #a1a1aa); line-height: 1.5; border-left: 1px dashed var(--border-dark, #d4d4d8); margin-left: 6px; }
.mini-thinking.expanded .mini-thinking-body { display: block; }

/* 展开箭头 */
.expand-chevron { transition: transform 0.2s; color: var(--text-muted, #a1a1aa); flex-shrink: 0; margin-left: auto; }
.expand-chevron.rotated { transform: rotate(90deg); }

/* 并行组 */
.parallel-group { display: flex; flex-direction: column; gap: 4px; padding: 6px 8px; border: 1px dashed var(--border-dark, #d4d4d8); border-radius: 8px; margin: 2px 0; }
.parallel-label { min-width: 0; font-size: 11px; color: var(--text-muted, #a1a1aa); display: flex; align-items: center; gap: 4px; margin-bottom: 2px; }
.parallel-steps { display: flex; flex-wrap: wrap; gap: 8px; }
.parallel-step { flex: 1; min-width: min(180px, 100%); }

/* 节点 IO 面板 */
.node-io-panel { min-width: 0; background: var(--bg-terminal, #0f172a); border-radius: 8px; padding: 10px 12px; margin: 4px 0 6px 22px; font-size: 12px; line-height: 1.5; overflow: hidden; }
.io-section { margin-bottom: 8px; }
.io-section:last-child { margin-bottom: 0; }
.io-label { color: #60a5fa; font-weight: 600; font-size: 11px; }
.io-label.io-error { color: #f87171; }
.io-content { color: #e2e8f0; margin: 2px 0 0 0; padding: 0; white-space: pre-wrap; word-break: break-all; font-size: 12px; background: transparent; border: none; overflow-x: auto; max-height: 200px; overflow-y: auto; }
.io-content.io-error { color: #fca5a5; }

.tool-group { min-width: 0; display: flex; flex-wrap: wrap; gap: 6px; margin-top: 2px; }
.mini-tool-capsule {
  max-width: 100%;
  min-width: 0;
  display: flex; align-items: center; gap: 6px; padding: 4px 10px;
  background: var(--bg-app, #fff); border: 1px solid var(--border-base, #e4e4e7); border-radius: var(--radius-sm, 8px);
  font-size: 12px; color: var(--text-sec, #52525b); cursor: pointer; transition: all 0.2s; box-shadow: var(--shadow-sm);
}
.mini-tool-capsule:hover { border-color: var(--border-dark, #d4d4d8); box-shadow: var(--shadow-md); color: var(--text-main, #18181b); }
.mini-tool-capsule.running { border-color: var(--accent-bg, #dbeafe); background: var(--accent-bg, #dbeafe); color: var(--accent-main, #3b82f6); box-shadow: none; }
.mini-tool-capsule.selected { border-color: var(--accent-main, #3b82f6); box-shadow: 0 0 0 1px var(--accent-main, #3b82f6); color: var(--text-main, #18181b); }
.mini-tool-capsule.selected .tool-name { color: var(--text-main, #18181b); }
.tool-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 500; font-family: var(--font-mono, ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace); font-size: 11.5px; }

.tool-status-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.dot-green { background: #10b981; }
.dot-red { background: #ef4444; }

@keyframes spin { 100% { transform: rotate(360deg); } }
.icon-spin { animation: spin 1s linear infinite; }

/* 上下文摘要消息 */
.summary-msg { justify-content: center; margin-bottom: 20px; width: 100%; min-width: 0; max-width: 880px; }
.summary-bubble { width: 100%; min-width: 0; background: var(--accent-bg, #dbeafe); border: 1px solid var(--accent-main, #3b82f6); border-radius: var(--radius-md, 12px); overflow: hidden; }
.summary-header { min-width: 0; display: flex; align-items: center; gap: 8px; padding: 10px 16px; cursor: pointer; font-size: 13px; font-weight: 500; color: var(--accent-main, #3b82f6); transition: background 0.15s; }
.summary-header:hover { background: rgba(59, 130, 246, 0.08); }
.summary-meta { font-size: 11px; color: var(--text-muted, #a1a1aa); font-weight: 400; }
.summary-header .expand-chevron { margin-left: auto; color: var(--accent-main, #3b82f6); }
.summary-body { min-width: 0; padding: 0 16px 14px; font-size: 14px; line-height: 1.6; color: var(--text-main, #18181b); border-top: 1px solid rgba(59, 130, 246, 0.15); overflow-wrap: anywhere; }
.summary-body :deep(h3) { font-size: 14px; margin: 10px 0 6px; }
.summary-body :deep(p) { margin: 6px 0; }
.summary-body :deep(ul), .summary-body :deep(ol) { margin: 6px 0; padding-left: 20px; }
.summary-body :deep(code) { background: rgba(59, 130, 246, 0.08); padding: 1px 4px; border-radius: 3px; font-size: 12.5px; }
.summary-body :deep(pre) { background: var(--bg-terminal, #0f172a); color: #e2e8f0; padding: 10px 12px; border-radius: 8px; overflow-x: auto; margin: 8px 0; font-size: 12px; }
.summary-body :deep(pre code) { background: transparent; padding: 0; color: inherit; }

/* 审批按钮 */
.approval-actions { display: flex; flex-wrap: wrap; gap: 10px; margin: 12px 0 4px; }
.approval-btn {
  display: flex; align-items: center; gap: 6px;
  padding: 8px 20px; border-radius: 8px; font-size: 14px; font-weight: 500;
  cursor: pointer; border: 1px solid transparent; transition: all 0.2s;
  max-width: 100%;
}
.approval-btn.approve { background: #f0fdf4; color: #16a34a; border-color: #bbf7d0; }
.approval-btn.approve:hover { background: #dcfce7; border-color: #86efac; }
.approval-btn.reject { background: #fef2f2; color: #dc2626; border-color: #fecaca; }
.approval-btn.reject:hover { background: #fee2e2; border-color: #fca5a5; }
.approval-result { font-size: 13px; padding: 6px 14px; border-radius: 6px; margin: 8px 0 4px; display: inline-block; }
.approval-result.approve { background: #f0fdf4; color: #16a34a; }
.approval-result.reject { background: #fef2f2; color: #dc2626; }

.assistant-bubble {
  width: min(100%, 760px);
  min-width: 0;
  background: linear-gradient(180deg, rgba(239, 246, 255, 0.96), rgba(255, 255, 255, 0.98));
  border: 1px solid rgba(191, 219, 254, 0.95);
  border-radius: 20px 20px 20px 10px;
  padding: 16px 18px;
  box-shadow: 0 24px 46px -34px rgba(37, 99, 235, 0.28);
}

.assistant-bubble .msg-text-block { margin-top: 0; }

.msg-text-block :deep(pre) {
  max-height: 420px;
  overflow: auto;
}

.message-footer {
  width: min(100%, 760px);
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.message-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 0;
}

.msg-actions {
  opacity: 1;
  padding: 2px;
  background: rgba(255, 255, 255, 0.82);
  border: 1px solid rgba(228, 228, 231, 0.9);
  border-radius: 999px;
  box-shadow: var(--shadow-sm);
}

.token-stats {
  opacity: 1;
  flex-wrap: wrap;
  gap: 8px;
}

.token-item {
  gap: 6px;
  padding: 6px 10px;
  border-radius: 999px;
  border: 1px solid rgba(228, 228, 231, 0.95);
  background: rgba(255, 255, 255, 0.95);
  color: var(--text-sec, #52525b);
  box-shadow: 0 8px 16px -14px rgba(15, 23, 42, 0.28);
}

.token-icon { color: var(--accent-main, #3b82f6); }

.process-summary-card {
  width: min(100%, 760px);
  min-width: 0;
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
  overflow-wrap: anywhere;
}

.process-summary-meta {
  margin-top: 2px;
  font-size: 11px;
  color: var(--text-muted, #a1a1aa);
  overflow-wrap: anywhere;
}

.agent-step {
  width: min(100%, 760px);
  min-width: 0;
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
  min-width: 0;
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
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 6px;
}

.parallel-steps {
  gap: 12px;
}

.parallel-step {
  min-width: min(220px, 100%);
}

.timeline-node-card,
.step-card,
.legacy-reasoning-card {
  min-width: 0;
  border-radius: 16px;
  border: 1px solid rgba(228, 228, 231, 0.92);
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 18px 36px -32px rgba(15, 23, 42, 0.26);
}

.timeline-node-card,
.step-card {
  padding: 12px 14px;
}

.legacy-reasoning-card {
  width: min(100%, 760px);
  min-width: 0;
  padding: 12px 14px;
}

.timeline-node-card.running,
.step-card.running {
  border-color: rgba(59, 130, 246, 0.28);
  background: linear-gradient(180deg, rgba(239, 246, 255, 0.92), rgba(255, 255, 255, 0.98));
}

.timeline-node-card.failed,
.step-card.failed {
  border-color: rgba(239, 68, 68, 0.22);
  background: linear-gradient(180deg, rgba(254, 242, 242, 0.88), rgba(255, 255, 255, 0.98));
}

.mini-thinking,
.step-card {
  gap: 0;
}

.mini-thinking-header,
.step-header {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-main, #18181b);
}

.mini-thinking-body {
  min-width: 0;
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
  min-width: 0;
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
  min-width: 0;
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

.mini-thinking.timeline-node-card {
  margin-top: 0;
}

.mini-tool-capsule {
  max-width: 100%;
  min-width: 0;
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
  max-width: min(180px, 44vw);
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

@media (max-width: 1024px) {
  .message-wrapper { padding: 0 12px; }

  .message {
    gap: 10px;
    margin-bottom: 24px;
  }

  .message-avatar {
    width: 26px;
    height: 26px;
    border-radius: 7px;
  }

  .user-avatar-stack {
    min-width: 28px;
  }

  .assistant-bubble {
    padding: 13px 14px;
    border-radius: 14px 14px 14px 8px;
  }

  .assistant-bubble,
  .message-footer,
  .process-summary-card,
  .agent-step,
  .legacy-reasoning-card {
    width: 100%;
  }

  .process-summary-card {
    padding: 10px 12px;
    gap: 10px;
  }

  .timeline-entry {
    grid-template-columns: 20px minmax(0, 1fr);
    gap: 10px;
  }

  .parallel-step {
    min-width: 100%;
  }

  .parallel-card,
  .timeline-node-card,
  .step-card,
  .legacy-reasoning-card {
    border-radius: 12px;
  }

  .timeline-node-card,
  .step-card,
  .legacy-reasoning-card {
    padding: 10px 12px;
  }

  .mini-thinking-header,
  .step-header {
    gap: 8px;
    font-size: 12px;
  }

  .assistant-note-block,
  .harness-feedback-note {
    margin-left: 0;
    flex-direction: column;
    gap: 6px;
  }

  .message-footer {
    gap: 8px;
  }

  .token-stats {
    gap: 6px;
  }

  .token-item {
    padding: 5px 8px;
  }
}

@media (max-width: 420px) {
  .message-wrapper { padding: 0 8px; }

  .message {
    gap: 8px;
  }

  .message-avatar {
    width: 24px;
    height: 24px;
    font-size: 11px;
  }

  .message-content {
    max-width: calc(100% - 34px);
  }

  .user-avatar-stack {
    min-width: 26px;
  }

  .assistant-bubble,
  .process-summary-card,
  .timeline-node-card,
  .step-card,
  .legacy-reasoning-card {
    padding: 10px;
  }

  .approval-btn {
    flex: 1 1 120px;
    justify-content: center;
    padding: 8px 10px;
  }
}

</style>
