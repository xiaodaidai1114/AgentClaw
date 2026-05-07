<template>
  <div class="config-page">
    <PageHeader :breadcrumbs="breadcrumbs" :show-refresh="false">
      <template #actions>
        <n-button size="small" quaternary @click="router.push(`/workflows/${workflowId}`)">{{ $t('common.detail') }}</n-button>
        <n-button size="small" type="primary" secondary @click="router.push(`/workflows/${workflowId}/chat`)">{{ $t('common.experience') }}</n-button>
      </template>
    </PageHeader>

    <!-- Workflow identity strip -->
    <div class="identity-strip">
      <div class="identity-left">
        <span class="identity-name">{{ workflow?.name || workflowId }}</span>
        <n-tag size="small" round :bordered="false" type="info">v{{ workflow?.version || '-' }}</n-tag>
      </div>
      <n-text depth="3" style="font-size: 12px; font-family: monospace;">{{ workflow?.id || workflowId }}</n-text>
    </div>

    <!-- Tab navigation -->
    <div class="config-tabs">
      <button :class="['tab-btn', { active: activeTab === 'workflow' }]" @click="activeTab = 'workflow'">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
        {{ t('workflowConfig.tabs.workflow') }}
      </button>
      <button :class="['tab-btn', { active: activeTab === 'nodes' }]" @click="activeTab = 'nodes'">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>
        {{ t('workflowConfig.tabs.nodes') }}
      </button>
      <button :class="['tab-btn', { active: activeTab === 'prompts' }]" @click="activeTab = 'prompts'">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
        {{ t('workflowConfig.tabs.prompts') }}
      </button>
    </div>

    <!-- ═══ Tab: Workflow Config ═══ -->
    <div v-show="activeTab === 'workflow'" class="tab-body">
      <div class="section-header">
        <div>
          <h3 class="section-title">{{ $t('workflowConfig.workflow.title') }}</h3>
          <p class="section-desc">{{ $t('workflowConfig.workflow.description') }}</p>
        </div>
        <n-button type="primary" size="small" :disabled="!workflowChanged" @click="saveWorkflowConfig">{{ t('workflowConfig.actions.saveChanges') }}</n-button>
      </div>
      <div class="form-panel">
        <div class="form-row">
          <div class="form-field">
            <label class="field-label">{{ t('workflowConfig.workflow.publicShare') }}</label>
            <n-switch v-model:value="workflowForm.public_share_enabled" :disabled="isBuiltinWorkflow" @update:value="workflowChanged = true" />
            <span class="field-hint">{{ isBuiltinWorkflow ? t('workflowConfig.workflow.builtinPublicShareDisabled') : t('workflowConfig.workflow.publicShareHint') }}</span>
          </div>
          <div class="form-field">
            <label class="field-label">{{ t('workflowConfig.workflow.injectAsAgenticCapability') }}</label>
            <n-switch v-model:value="workflowForm.inject_as_agentic_capability" @update:value="workflowChanged = true" />
            <span class="field-hint">{{ t('workflowConfig.workflow.injectAsAgenticCapabilityHint') }}</span>
          </div>
          <div class="form-field">
            <label class="field-label">{{ t('workflowConfig.workflow.publicRateLimit') }}</label>
            <n-input v-model:value="workflowForm.rate_limit" :placeholder="t('workflowConfig.workflow.publicRateLimitPlaceholder')" @input="workflowChanged = true" />
            <span class="field-hint">{{ t('workflowConfig.workflow.publicRateLimitHint') }}</span>
          </div>
        </div>
        <div class="form-row">
          <div class="form-field">
            <label class="field-label">{{ t('workflowConfig.workflow.workflowApiKey') }}</label>
            <n-input v-model:value="workflowForm.workflow_api_key" type="password" show-password-on="click" :placeholder="workflowForm.workflow_api_key_set ? t('settings.secretUnchanged') : ''" @input="workflowChanged = true" />
            <span class="field-hint">{{ t('workflowConfig.workflow.workflowApiKeyHint') }}</span>
          </div>
          <div class="form-field">
            <label class="field-label">{{ t('common.timeout') }}<n-tooltip v-if="tips['超时 (秒)']"><template #trigger><span class="tip-icon">?</span></template>{{ tips['超时 (秒)'] }}</n-tooltip></label>
            <n-input-number v-model:value="workflowForm.timeout" :min="0" :max="3600" :placeholder="t('common.noLimit')" @update:value="workflowChanged = true" />
            <span class="field-hint">{{ t('workflowConfig.workflow.timeoutHint') }}</span>
          </div>
          <div class="form-field">
            <label class="field-label">{{ t('workflowConfig.workflow.recursionLimit') }}<n-tooltip v-if="tips['递归限制']"><template #trigger><span class="tip-icon">?</span></template>{{ tips['递归限制'] }}</n-tooltip></label>
            <n-input-number v-model:value="workflowForm.recursion_limit" :min="1" :max="500" @update:value="workflowChanged = true" />
          </div>
          <div class="form-field">
            <label class="field-label">{{ t('workflowConfig.workflow.publicConversationLimit') }}</label>
            <n-input-number v-model:value="workflowForm.public_conversation_limit" :min="1" :max="1000" @update:value="workflowChanged = true" />
            <span class="field-hint">{{ t('workflowConfig.workflow.publicConversationLimitHint') }}</span>
          </div>
          <div class="form-field">
            <label class="field-label">{{ t('workflowConfig.workflow.publicMessageLimit') }}</label>
            <n-input-number v-model:value="workflowForm.public_message_limit" :min="1" :max="5000" @update:value="workflowChanged = true" />
            <span class="field-hint">{{ t('workflowConfig.workflow.publicMessageLimitHint') }}</span>
          </div>
        </div>
        <div class="form-row">
          <div class="form-field full">
            <label class="field-label">{{ t('common.description') }}<n-tooltip v-if="tips['描述']"><template #trigger><span class="tip-icon">?</span></template>{{ tips['描述'] }}</n-tooltip></label>
            <n-input v-model:value="workflowForm.description" type="textarea" :rows="2" :placeholder="t('workflowConfig.workflow.descriptionPlaceholder')" @input="workflowChanged = true" />
          </div>
        </div>
        <div class="form-row">
          <div class="form-field full">
            <label class="field-label">{{ t('workflowConfig.workflow.welcome') }}<n-tooltip v-if="tips['开场白']"><template #trigger><span class="tip-icon">?</span></template>{{ tips['开场白'] }}</n-tooltip></label>
            <n-input v-model:value="workflowForm.welcome" type="textarea" :rows="3" :placeholder="t('workflowConfig.workflow.welcomePlaceholder')" @input="workflowChanged = true" />
          </div>
        </div>
        <div class="form-row">
          <div class="form-field full">
            <label class="field-label">{{ t('workflowConfig.workflow.memory') }}<n-tooltip v-if="tips['全局记忆']"><template #trigger><span class="tip-icon">?</span></template>{{ tips['全局记忆'] }}</n-tooltip></label>
            <n-input v-model:value="workflowForm.memory_content" type="textarea" :rows="10" :placeholder="t('workflowConfig.workflow.memoryPlaceholder')" @input="workflowChanged = true" />
            <span class="field-hint">{{ t('workflowConfig.workflow.memoryCounter', { count: (workflowForm.memory_content || '').length, max: 40000 }) }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- ═══ Tab: Node Config ═══ -->
    <div v-show="activeTab === 'nodes'" class="tab-body">
      <div class="node-layout">
        <!-- Node sidebar -->
        <aside class="node-sidebar">
          <div class="sidebar-title">{{ $t('workflowConfig.node.list') }}</div>
          <div
            v-for="node in nodeList" :key="node.id"
            :class="['node-item', { active: selectedNodeId === node.id }]"
            @click="onNodeSelect(node)"
          >
            <span :class="['node-dot', node.type.toLowerCase()]"></span>
            <span class="node-name">{{ node.id }}</span>
            <span class="node-type-badge">{{ node.type_label }}</span>
          </div>
          <div v-if="!nodeList.length" class="sidebar-empty">{{ t('workflowConfig.node.noNodes') }}</div>
        </aside>

        <!-- Node editor -->
        <div class="node-editor">
          <template v-if="nodeForm">
            <div class="node-editor-header">
              <div>
                <h3 class="section-title" style="margin-bottom: 2px;">{{ selectedNodeId }}</h3>
                <n-tag size="tiny" :bordered="false" :type="selectedNodeType === 'LLMNode' ? 'success' : selectedNodeType === 'HumanNode' ? 'warning' : 'info'">{{ selectedNodeType }}</n-tag>
              </div>
              <n-button type="primary" size="small" :disabled="!nodeChanged" @click="saveNodeConfig">{{ t('workflowConfig.actions.saveChanges') }}</n-button>
            </div>
            <p class="section-desc" style="margin-bottom: 20px;">{{ t('workflowConfig.node.overrideHint') }}</p>
            <!-- Base config -->
            <div class="config-block">
              <div class="block-title">{{ t('workflowConfig.blocks.base') }}</div>
              <div class="field-grid">
                <div class="form-field"><label class="field-label">{{ t('common.description') }}<n-tooltip v-if="tips['描述']"><template #trigger><span class="tip-icon">?</span></template>{{ tips['描述'] }}</n-tooltip></label><n-input v-model:value="nodeForm.description" @input="nodeChanged = true" /></div>
                <div class="form-field"><label class="field-label">{{ t('workflowConfig.fields.outputToUser') }}<n-tooltip v-if="tips['输出给用户']"><template #trigger><span class="tip-icon">?</span></template>{{ tips['输出给用户'] }}</n-tooltip></label><n-switch v-model:value="nodeForm.output_to_user" @update:value="nodeChanged = true" /></div>
                <div class="form-field"><label class="field-label">{{ t('workflowConfig.fields.outputKey') }}<n-tooltip v-if="tips['输出 Key']"><template #trigger><span class="tip-icon">?</span></template>{{ tips['输出 Key'] }}</n-tooltip></label><n-input v-model:value="nodeForm.output_key" @input="nodeChanged = true" /></div>
              </div>
            </div>

            <!-- LLM Engine -->
            <div v-if="selectedNodeType === 'LLMNode'" class="config-block highlight">
              <div class="block-title">{{ t('workflowConfig.blocks.llmEngine') }}</div>
              <div class="field-grid cols-3">
                <div class="form-field"><label class="field-label">{{ t('workflowConfig.fields.model') }}<n-tooltip v-if="tips['模型']"><template #trigger><span class="tip-icon">?</span></template>{{ tips['模型'] }}</n-tooltip></label><n-select v-model:value="nodeForm.model_id" :options="modelOptions" clearable @update:value="nodeChanged = true" /></div>
                <div class="form-field"><label class="field-label">{{ t('workflowConfig.fields.fastModel') }}<n-tooltip v-if="tips['快速模型']"><template #trigger><span class="tip-icon">?</span></template>{{ tips['快速模型'] }}</n-tooltip></label><n-switch v-model:value="nodeForm.use_fast_model" @update:value="nodeChanged = true" /></div>
                <div class="form-field"><label class="field-label">{{ t('workflowConfig.fields.stream') }}<n-tooltip v-if="tips['流式输出']"><template #trigger><span class="tip-icon">?</span></template>{{ tips['流式输出'] }}</n-tooltip></label><n-switch v-model:value="nodeForm.stream" @update:value="nodeChanged = true" /></div>
                <div class="form-field"><label class="field-label">{{ t('workflowConfig.fields.temperature') }}<n-tooltip v-if="tips['Temperature']"><template #trigger><span class="tip-icon">?</span></template>{{ tips['Temperature'] }}</n-tooltip></label><div class="slider-row"><n-slider v-model:value="nodeForm.temperature" :min="0" :max="2" :step="0.1" @update:value="nodeChanged = true" /><span class="slider-val">{{ nodeForm.temperature }}</span></div></div>
                <div class="form-field"><label class="field-label">{{ t('workflowConfig.fields.maxTokens') }}<n-tooltip v-if="tips['Max Tokens']"><template #trigger><span class="tip-icon">?</span></template>{{ tips['Max Tokens'] }}</n-tooltip></label><n-input-number v-model:value="nodeForm.max_tokens" :min="0" :max="200000" :step="256" @update:value="nodeChanged = true" /></div>
                <div class="form-field"><label class="field-label">{{ t('workflowConfig.fields.topP') }}<n-tooltip v-if="tips['Top P']"><template #trigger><span class="tip-icon">?</span></template>{{ tips['Top P'] }}</n-tooltip></label><div class="slider-row"><n-slider v-model:value="nodeForm.top_p" :min="0" :max="1" :step="0.05" @update:value="nodeChanged = true" /><span class="slider-val">{{ nodeForm.top_p }}</span></div></div>
                <div class="form-field"><label class="field-label">{{ t('workflowConfig.fields.outputFormat') }}<n-tooltip v-if="tips['输出格式']"><template #trigger><span class="tip-icon">?</span></template>{{ tips['输出格式'] }}</n-tooltip></label><n-select v-model:value="nodeForm.output_format" :options="outputFormatOptions" @update:value="nodeChanged = true" /></div>
              </div>
            </div>

            <!-- Tools & Memory -->
            <div v-if="selectedNodeType === 'LLMNode'" class="config-block">
              <div class="block-title">{{ t('workflowConfig.blocks.toolsMemory') }}</div>
              <div class="field-grid cols-3">
                <div class="form-field"><label class="field-label">{{ t('workflowConfig.fields.toolChoice') }}<n-tooltip v-if="tips['工具选择']"><template #trigger><span class="tip-icon">?</span></template>{{ tips['工具选择'] }}</n-tooltip></label><n-select v-model:value="nodeForm.tool_choice" :options="toolChoiceOptions" @update:value="nodeChanged = true" /></div>
                <div class="form-field"><label class="field-label">{{ t('workflowConfig.fields.maxToolRounds') }}<n-tooltip v-if="tips['最大工具轮数']"><template #trigger><span class="tip-icon">?</span></template>{{ tips['最大工具轮数'] }}</n-tooltip></label><n-input-number v-model:value="nodeForm.max_tool_rounds" :min="0" :max="200" @update:value="nodeChanged = true" /></div>
                <div class="form-field"><label class="field-label">{{ t('workflowConfig.fields.agentStyle') }}<n-tooltip v-if="tips['Agent 风格']"><template #trigger><span class="tip-icon">?</span></template>{{ tips['Agent 风格'] }}</n-tooltip></label><n-select v-model:value="nodeForm.agent_style" :options="agentStyleOptions" @update:value="nodeChanged = true" /></div>
                <div class="form-field"><label class="field-label">{{ t('workflowConfig.fields.enableMemory') }}<n-tooltip v-if="tips['启用全局记忆']"><template #trigger><span class="tip-icon">?</span></template>{{ tips['启用全局记忆'] }}</n-tooltip></label><n-switch v-model:value="nodeForm.enable_memory" @update:value="nodeChanged = true" /></div>
                <div class="form-field"><label class="field-label">{{ t('workflowConfig.fields.enableBuiltinSkills') }}<n-tooltip v-if="tips['启用内置技能']"><template #trigger><span class="tip-icon">?</span></template>{{ tips['启用内置技能'] }}</n-tooltip></label><n-switch v-model:value="nodeForm.enable_builtin_skills" @update:value="nodeChanged = true" /></div>
                <div class="form-field"><label class="field-label">{{ t('workflowConfig.fields.enableBuiltinTools') }}<n-tooltip v-if="tips['启用内置工具']"><template #trigger><span class="tip-icon">?</span></template>{{ tips['启用内置工具'] }}</n-tooltip></label><n-switch v-model:value="nodeForm.enable_builtin_tools" @update:value="nodeChanged = true" /></div>
                <div class="form-field"><label class="field-label">{{ t('workflowConfig.fields.injectFiles') }}<n-tooltip v-if="tips['注入文件']"><template #trigger><span class="tip-icon">?</span></template>{{ tips['注入文件'] }}</n-tooltip></label><n-select v-model:value="nodeForm.inject_files" :options="injectFilesOptions" @update:value="nodeChanged = true" /></div>
                <div class="form-field"><label class="field-label">{{ t('workflowConfig.fields.useContext') }}<n-tooltip v-if="tips['使用上下文']"><template #trigger><span class="tip-icon">?</span></template>{{ tips['使用上下文'] }}</n-tooltip></label><n-switch v-model:value="nodeForm.use_context" @update:value="nodeChanged = true" /></div>
                <div class="form-field"><label class="field-label">{{ t('workflowConfig.fields.saveToContext') }}<n-tooltip v-if="tips['保存到上下文']"><template #trigger><span class="tip-icon">?</span></template>{{ tips['保存到上下文'] }}</n-tooltip></label><n-switch v-model:value="nodeForm.save_to_context" @update:value="nodeChanged = true" /></div>
                <div class="form-field"><label class="field-label">{{ t('workflowConfig.fields.maxContextMessages') }}<n-tooltip v-if="tips['最大上下文消息数']"><template #trigger><span class="tip-icon">?</span></template>{{ tips['最大上下文消息数'] }}</n-tooltip></label><n-input-number v-model:value="nodeForm.max_context_messages" :min="0" :max="200" @update:value="nodeChanged = true" /></div>
              </div>
            </div>
            <!-- Advanced / Fallback -->
            <details v-if="selectedNodeType === 'LLMNode'" class="config-block collapsible">
              <summary class="block-title clickable">{{ t('workflowConfig.blocks.advancedFallback') }}</summary>
              <div class="field-grid cols-3" style="margin-top: 16px;">
                <div class="form-field"><label class="field-label">{{ t('workflowConfig.fields.errorStrategy') }}<n-tooltip v-if="tips['错误策略']"><template #trigger><span class="tip-icon">?</span></template>{{ tips['错误策略'] }}</n-tooltip></label><n-select v-model:value="nodeForm.on_error" :options="errorStrategyOptions" @update:value="nodeChanged = true" /></div>
                <div class="form-field"><label class="field-label">{{ t('workflowConfig.fields.fallbackValue') }}<n-tooltip v-if="tips['Fallback 值']"><template #trigger><span class="tip-icon">?</span></template>{{ tips['Fallback 值'] }}</n-tooltip></label><n-input v-model:value="nodeForm.fallback_value" @input="nodeChanged = true" /></div>
                <div class="form-field"><label class="field-label">{{ t('workflowConfig.fields.maxRetries') }}<n-tooltip v-if="tips['最大重试']"><template #trigger><span class="tip-icon">?</span></template>{{ tips['最大重试'] }}</n-tooltip></label><n-input-number v-model:value="nodeForm.max_retries" :min="0" :max="10" @update:value="nodeChanged = true" /></div>
                <div class="form-field"><label class="field-label">{{ t('workflowConfig.fields.retryDelay') }}<n-tooltip v-if="tips['重试延迟']"><template #trigger><span class="tip-icon">?</span></template>{{ tips['重试延迟'] }}</n-tooltip></label><n-input-number v-model:value="nodeForm.retry_delay" :min="0" :max="60" :step="0.5" @update:value="nodeChanged = true" /></div>
                <div class="form-field"><label class="field-label">{{ t('workflowConfig.fields.fallbackModel') }}<n-tooltip v-if="tips['备选模型']"><template #trigger><span class="tip-icon">?</span></template>{{ tips['备选模型'] }}</n-tooltip></label><n-select v-model:value="nodeForm.fallback_model_id" :options="modelOptions" clearable @update:value="nodeChanged = true" /></div>
                <div class="form-field"><label class="field-label">{{ t('workflowConfig.fields.autoFallback') }}<n-tooltip v-if="tips['自动降级']"><template #trigger><span class="tip-icon">?</span></template>{{ tips['自动降级'] }}</n-tooltip></label><n-switch v-model:value="nodeForm.auto_fallback" @update:value="nodeChanged = true" /></div>
                <div class="form-field"><label class="field-label">{{ t('workflowConfig.fields.fallbackThreshold') }}<n-tooltip v-if="tips['降级阈值']"><template #trigger><span class="tip-icon">?</span></template>{{ tips['降级阈值'] }}</n-tooltip></label><n-input-number v-model:value="nodeForm.fallback_threshold" :min="0" :max="10" @update:value="nodeChanged = true" /></div>
                <div class="form-field"><label class="field-label">{{ t('workflowConfig.fields.compression') }}<n-tooltip v-if="tips['上下文压缩']"><template #trigger><span class="tip-icon">?</span></template>{{ tips['上下文压缩'] }}</n-tooltip></label><n-switch v-model:value="nodeForm.enable_compression" @update:value="nodeChanged = true" /></div>
                <div class="form-field"><label class="field-label">{{ t('workflowConfig.fields.compressionThreshold') }}<n-tooltip v-if="tips['压缩阈值']"><template #trigger><span class="tip-icon">?</span></template>{{ tips['压缩阈值'] }}</n-tooltip></label><n-input-number v-model:value="nodeForm.compression_threshold" :min="0" :max="500000" :step="10000" @update:value="nodeChanged = true" /></div>
                <div class="form-field"><label class="field-label">{{ t('workflowConfig.fields.compressionModel') }}<n-tooltip v-if="tips['压缩模型']"><template #trigger><span class="tip-icon">?</span></template>{{ tips['压缩模型'] }}</n-tooltip></label><n-select v-model:value="nodeForm.compression_model" :options="modelOptions" clearable @update:value="nodeChanged = true" /></div>
              </div>
            </details>

            <!-- Non-LLM error handling -->
            <details v-if="selectedNodeType !== 'LLMNode'" class="config-block collapsible">
              <summary class="block-title clickable">{{ t('workflowConfig.blocks.errorHandling') }}</summary>
              <div class="field-grid" style="margin-top: 16px;">
                <div class="form-field"><label class="field-label">{{ t('workflowConfig.fields.errorStrategy') }}<n-tooltip v-if="tips['错误策略']"><template #trigger><span class="tip-icon">?</span></template>{{ tips['错误策略'] }}</n-tooltip></label><n-select v-model:value="nodeForm.on_error" :options="errorStrategyOptions" @update:value="nodeChanged = true" /></div>
                <div class="form-field"><label class="field-label">{{ t('workflowConfig.fields.fallbackValue') }}<n-tooltip v-if="tips['Fallback 值']"><template #trigger><span class="tip-icon">?</span></template>{{ tips['Fallback 值'] }}</n-tooltip></label><n-input v-model:value="nodeForm.fallback_value" @input="nodeChanged = true" /></div>
                <div class="form-field"><label class="field-label">{{ t('workflowConfig.fields.maxRetries') }}<n-tooltip v-if="tips['最大重试']"><template #trigger><span class="tip-icon">?</span></template>{{ tips['最大重试'] }}</n-tooltip></label><n-input-number v-model:value="nodeForm.max_retries" :min="0" :max="10" @update:value="nodeChanged = true" /></div>
                <div class="form-field"><label class="field-label">{{ t('workflowConfig.fields.retryDelay') }}<n-tooltip v-if="tips['重试延迟']"><template #trigger><span class="tip-icon">?</span></template>{{ tips['重试延迟'] }}</n-tooltip></label><n-input-number v-model:value="nodeForm.retry_delay" :min="0" :max="60" :step="0.5" @update:value="nodeChanged = true" /></div>
              </div>
            </details>

            <!-- HumanNode specific -->
            <div v-if="selectedNodeType === 'HumanNode'" class="config-block highlight">
              <div class="block-title">{{ t('workflowConfig.blocks.humanBehavior') }}</div>
              <div class="field-grid cols-3">
                <div class="form-field"><label class="field-label">{{ t('workflowConfig.fields.feedbackField') }}<n-tooltip v-if="tips['反馈字段']"><template #trigger><span class="tip-icon">?</span></template>{{ tips['反馈字段'] }}</n-tooltip></label><n-input v-model:value="nodeForm.feedback_field" @input="nodeChanged = true" /></div>
                <div class="form-field"><label class="field-label">{{ t('workflowConfig.fields.pendingStatus') }}<n-tooltip v-if="tips['待处理状态']"><template #trigger><span class="tip-icon">?</span></template>{{ tips['待处理状态'] }}</n-tooltip></label><n-input v-model:value="nodeForm.pending_status" @input="nodeChanged = true" /></div>
                <div class="form-field"><label class="field-label">{{ t('workflowConfig.fields.approvalMode') }}<n-tooltip v-if="tips['审批模式']"><template #trigger><span class="tip-icon">?</span></template>{{ tips['审批模式'] }}</n-tooltip></label><n-switch v-model:value="nodeForm.approval_mode" @update:value="nodeChanged = true" /></div>
                <div class="form-field"><label class="field-label">{{ t('common.timeout') }}<n-tooltip v-if="tips['超时 (秒)']"><template #trigger><span class="tip-icon">?</span></template>{{ tips['超时 (秒)'] }}</n-tooltip></label><n-input-number v-model:value="nodeForm.timeout_seconds" :min="0" :max="86400" @update:value="nodeChanged = true" /></div>
                <div class="form-field"><label class="field-label">{{ t('workflowConfig.fields.timeoutAction') }}<n-tooltip v-if="tips['超时策略']"><template #trigger><span class="tip-icon">?</span></template>{{ tips['超时策略'] }}</n-tooltip></label><n-select v-model:value="nodeForm.on_timeout" :options="timeoutActionOptions" @update:value="nodeChanged = true" /></div>
                <div class="form-field"><label class="field-label">{{ t('workflowConfig.fields.saveToContext') }}<n-tooltip v-if="tips['保存到上下文']"><template #trigger><span class="tip-icon">?</span></template>{{ tips['保存到上下文'] }}</n-tooltip></label><n-switch v-model:value="nodeForm.save_to_context" @update:value="nodeChanged = true" /></div>
              </div>
            </div>

          </template>
          <div v-else class="editor-empty">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#d0d5dd" stroke-width="1.5"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>
            <p>{{ t('workflowConfig.node.selectNode') }}</p>
          </div>
        </div>
      </div>
    </div>

    <!-- ═══ Tab: Prompts ═══ -->
    <div v-show="activeTab === 'prompts'" class="tab-body">
      <PromptConfigPanel :workflow-id="workflowId" />
    </div>
  </div>
</template>
<script setup>
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { NButton, NInput, NInputNumber, NSelect, NSlider, NSwitch, NTag, NText, NTooltip, useMessage } from 'naive-ui'
import PageHeader from '../components/PageHeader.vue'
import PromptConfigPanel from '../components/PromptConfigPanel.vue'
import { modelsApi, settingsApi, workflowsApi } from '../api'
import {
  localizeBuiltinNodeConfig,
  localizeBuiltinWorkflow,
  localizeBuiltinWorkflowConfig,
} from '../utils/builtinWorkflowI18n'
import { toConversationModelOptions } from '../utils/models'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const { t } = useI18n()
const workflowId = computed(() => String(route.params.id || ''))
const breadcrumbs = computed(() => [{ text: t('workflows.title'), to: '/workflows' }, { text: workflowId.value, to: `/workflows/${workflowId.value}` }, { text: t('common.configure') }])
const activeTab = ref('nodes')
const workflow = ref(null)
const workflowForm = ref({})
const workflowChanged = ref(false)
const nodeList = ref([])
const selectedNodeId = ref('')
const selectedNodeType = ref('')
const nodeForm = ref(null)
const nodeChanged = ref(false)
const availableModels = ref([])
const modelOptions = computed(() => toConversationModelOptions(availableModels.value))
const isBuiltinWorkflow = computed(() => workflowId.value === '__builtin__' || !!workflow.value?.is_builtin)
const errorStrategyOptions = ['ABORT', 'RETRY', 'SKIP', 'FALLBACK'].map((value) => ({ label: value, value }))
const toolChoiceOptions = ['auto', 'required', 'none'].map((value) => ({ label: value, value }))
const timeoutActionOptions = ['approve', 'reject', 'error'].map((value) => ({ label: value, value }))
const outputFormatOptions = ['text', 'json'].map((value) => ({ label: value, value }))
const agentStyleOptions = ['default', 'agentic'].map((value) => ({ label: value, value }))
const injectFilesOptions = [
  { label: t('workflowConfig.injectFiles.inheritDefault'), value: null },
  { label: t('workflowConfig.injectFiles.forceOn'), value: true },
  { label: t('workflowConfig.injectFiles.forceOff'), value: false },
]

const tips = {
  '超时 (秒)': t('workflowConfig.tips.timeout'),
  '递归限制': t('workflowConfig.tips.recursionLimit'),
  '描述': t('workflowConfig.tips.description'),
  '开场白': t('workflowConfig.tips.welcome'),
  '全局记忆': t('workflowConfig.tips.memory'),
  '输出给用户': t('workflowConfig.tips.outputToUser'),
  '输出 Key': t('workflowConfig.tips.outputKey'),
  '模型': t('workflowConfig.tips.model'),
  '快速模型': t('workflowConfig.tips.fastModel'),
  '流式输出': t('workflowConfig.tips.stream'),
  'Temperature': t('workflowConfig.tips.temperature'),
  'Max Tokens': t('workflowConfig.tips.maxTokens'),
  'Top P': t('workflowConfig.tips.topP'),
  '输出格式': t('workflowConfig.tips.outputFormat'),
  '工具选择': t('workflowConfig.tips.toolChoice'),
  '最大工具轮数': t('workflowConfig.tips.maxToolRounds'),
  'Agent 风格': t('workflowConfig.tips.agentStyle'),
  '启用全局记忆': t('workflowConfig.tips.enableMemory'),
  '启用内置技能': t('workflowConfig.tips.enableBuiltinSkills'),
  '启用内置工具': t('workflowConfig.tips.enableBuiltinTools'),
  '注入文件': t('workflowConfig.tips.injectFiles'),
  '使用上下文': t('workflowConfig.tips.useContext'),
  '保存到上下文': t('workflowConfig.tips.saveToContext'),
  '最大上下文消息数': t('workflowConfig.tips.maxContextMessages'),
  '错误策略': t('workflowConfig.tips.errorStrategy'),
  'Fallback 值': t('workflowConfig.tips.fallbackValue'),
  '最大重试': t('workflowConfig.tips.maxRetries'),
  '重试延迟': t('workflowConfig.tips.retryDelay'),
  '备选模型': t('workflowConfig.tips.fallbackModel'),
  '自动降级': t('workflowConfig.tips.autoFallback'),
  '降级阈值': t('workflowConfig.tips.fallbackThreshold'),
  '上下文压缩': t('workflowConfig.tips.compression'),
  '压缩阈值': t('workflowConfig.tips.compressionThreshold'),
  '压缩模型': t('workflowConfig.tips.compressionModel'),
  '反馈字段': t('workflowConfig.tips.feedbackField'),
  '待处理状态': t('workflowConfig.tips.pendingStatus'),
  '审批模式': t('workflowConfig.tips.approvalMode'),
  '超时策略': t('workflowConfig.tips.timeoutAction'),
}

function normalizeNodeType(type) {
  const value = String(type || '').toLowerCase()
  if (value.includes('llm')) return 'LLMNode'
  if (value.includes('human')) return 'HumanNode'
  if (value.includes('function')) return 'FunctionNode'
  return type || 'BaseNode'
}

function getNodeTypeLabel(type) {
  return {
    LLMNode: t('workflowConfig.nodeTypes.llm'),
    HumanNode: t('workflowConfig.nodeTypes.human'),
    FunctionNode: t('workflowConfig.nodeTypes.function'),
  }[type] || type
}
async function fetchWorkflow() {
  const res = await workflowsApi.get(workflowId.value)
  const localizedWorkflow = localizeBuiltinWorkflow(res.workflow, t)
  workflow.value = localizedWorkflow
  nodeList.value = (localizedWorkflow?.nodes || []).map((node) => ({ id: node.id || node.name, type: normalizeNodeType(node.type), type_label: getNodeTypeLabel(normalizeNodeType(node.type)), config: node }))
}

async function fetchWorkflowConfig() {
  const cfg = localizeBuiltinWorkflowConfig(await settingsApi.getWorkflow(workflowId.value), workflowId.value, t)
  workflowForm.value = {
    timeout: cfg.timeout,
    recursion_limit: cfg.recursion_limit,
    rate_limit: cfg.rate_limit || '',
    public_share_enabled: isBuiltinWorkflow.value ? false : !!cfg.public_share_enabled,
    public_share_token: isBuiltinWorkflow.value ? '' : (cfg.public_share_token || ''),
    workflow_api_key: cfg.workflow_api_key || '',
    workflow_api_key_set: !!cfg.workflow_api_key_set,
    inject_as_agentic_capability: cfg.inject_as_agentic_capability !== false,
    public_conversation_limit: cfg.public_conversation_limit || 20,
    public_message_limit: cfg.public_message_limit || 200,
    description: cfg.description || '',
    welcome: cfg.welcome || '',
    memory_content: cfg.memory_content || '',
  }
  workflowChanged.value = false
}

async function fetchModels() {
  const res = await modelsApi.getAvailable()
  availableModels.value = res.models || []
}

async function onNodeSelect(node) {
  selectedNodeId.value = node.id
  selectedNodeType.value = node.type
  nodeForm.value = {
    ...localizeBuiltinNodeConfig(await settingsApi.getNode(workflowId.value, node.id), workflowId.value, node.id, t),
  }
  nodeChanged.value = false
}

async function saveWorkflowConfig() {
  if (isBuiltinWorkflow.value) {
    workflowForm.value.public_share_enabled = false
    workflowForm.value.public_share_token = ''
  }
  const res = localizeBuiltinWorkflowConfig(await settingsApi.updateWorkflow(workflowId.value, workflowForm.value), workflowId.value, t)
  workflowForm.value = {
    timeout: res.timeout,
    recursion_limit: res.recursion_limit,
    rate_limit: res.rate_limit || '',
    public_share_enabled: isBuiltinWorkflow.value ? false : !!res.public_share_enabled,
    public_share_token: isBuiltinWorkflow.value ? '' : (res.public_share_token || ''),
    workflow_api_key: res.workflow_api_key || '',
    workflow_api_key_set: !!res.workflow_api_key_set,
    inject_as_agentic_capability: res.inject_as_agentic_capability !== false,
    public_conversation_limit: res.public_conversation_limit || 20,
    public_message_limit: res.public_message_limit || 200,
    description: res.description || '',
    welcome: res.welcome || '',
    memory_content: res.memory_content || '',
  }
  workflowChanged.value = false
  message.success(t('workflowConfig.messages.workflowSaved'))
}

async function saveNodeConfig() {
  nodeForm.value = {
    ...localizeBuiltinNodeConfig(await settingsApi.updateNode(workflowId.value, selectedNodeId.value, nodeForm.value), workflowId.value, selectedNodeId.value, t),
  }
  nodeChanged.value = false
  message.success(t('workflowConfig.messages.nodeSaved'))
}

onMounted(async () => {
  try {
    await Promise.all([fetchWorkflow(), fetchWorkflowConfig(), fetchModels()])
    if (nodeList.value.length) await onNodeSelect(nodeList.value[0])
  } catch (e) {
    message.error(t('workflowConfig.messages.loadFailed'))
  }
})
</script>
<style scoped>
.config-page { width: 100%; }

/* Identity strip */
.identity-strip {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 16px; margin-bottom: 20px;
  background: #fff; border: 1px solid #eaecf0; border-radius: 10px;
}
.identity-left { display: flex; align-items: center; gap: 10px; }
.identity-name { font-size: 15px; font-weight: 600; color: var(--text-primary); }

/* Tab bar */
.config-tabs {
  display: flex; gap: 4px; padding: 4px;
  background: #f4f5f7; border-radius: 10px; margin-bottom: 20px;
}
.tab-btn {
  flex: 1; display: flex; align-items: center; justify-content: center; gap: 6px;
  padding: 9px 16px; border: none; border-radius: 8px;
  background: transparent; color: #667085; font-size: 13px; font-weight: 500;
  cursor: pointer; transition: all 0.15s;
}
.tab-btn:hover { color: var(--text-primary); background: rgba(255,255,255,0.6); }
.tab-btn.active {
  background: #fff; color: var(--text-primary); font-weight: 600;
  box-shadow: 0 1px 3px rgba(0,0,0,0.08);
}
.tab-btn svg { opacity: 0.6; }
.tab-btn.active svg { opacity: 1; }

/* Tab body */
.tab-body { animation: fadeIn 0.15s ease; }
@keyframes fadeIn { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }

/* Section header */
.section-header {
  display: flex; align-items: flex-start; justify-content: space-between;
  margin-bottom: 20px;
}
.section-title { font-size: 16px; font-weight: 600; color: var(--text-primary); margin: 0; }
.section-desc { font-size: 13px; color: #667085; margin: 4px 0 0; }
/* Form panel */
.form-panel {
  background: #fff; border: 1px solid #eaecf0; border-radius: 12px; padding: 24px;
}
.form-row { display: flex; gap: 20px; margin-bottom: 16px; }
.form-row:last-child { margin-bottom: 0; }
.form-field { flex: 1; min-width: 0; }
.form-field.full { flex: 1 1 100%; }
.field-label {
  display: block; font-size: 13px; font-weight: 500; color: #344054;
  margin-bottom: 6px;
}
.field-hint { font-size: 12px; color: #98a2b3; margin-top: 4px; display: block; }

/* Tip icon */
.tip-icon {
  display: inline-flex; align-items: center; justify-content: center;
  width: 14px; height: 14px; border-radius: 50%;
  background: #eaecf0; color: #667085;
  font-size: 10px; font-weight: 600; line-height: 1;
  margin-left: 4px; cursor: help; vertical-align: middle;
  transition: background 0.15s, color 0.15s;
}
.tip-icon:hover { background: var(--primary); color: #fff; }

/* Node layout */
.node-layout { display: flex; gap: 20px; min-height: 560px; }

/* Node sidebar */
.node-sidebar {
  width: 220px; flex-shrink: 0;
  background: #fff; border: 1px solid #eaecf0; border-radius: 12px;
  padding: 12px; overflow-y: auto;
}
.sidebar-title {
  font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;
  color: #98a2b3; padding: 4px 8px 10px; border-bottom: 1px solid #f2f4f7; margin-bottom: 8px;
}
.node-item {
  display: flex; align-items: center; gap: 8px;
  padding: 9px 10px; border-radius: 8px; cursor: pointer;
  transition: all 0.12s; font-size: 13px; color: #344054;
}
.node-item:hover { background: #f9fafb; }
.node-item.active { background: var(--primary-light); color: var(--primary); font-weight: 500; }
.node-dot {
  width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0;
}
.node-dot.llmnode { background: #12b76a; }
.node-dot.humannode { background: #f79009; }
.node-dot.functionnode { background: #2e90fa; }
.node-dot.basenode { background: #98a2b3; }
.node-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.node-type-badge {
  font-size: 10px; padding: 1px 6px; border-radius: 4px;
  background: #f2f4f7; color: #667085; flex-shrink: 0;
}
.sidebar-empty { padding: 32px 0; text-align: center; color: #98a2b3; font-size: 13px; }

/* Node editor */
.node-editor { flex: 1; min-width: 0; }
.node-editor-header {
  display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px;
}
.editor-empty {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  height: 400px; color: #98a2b3; gap: 12px; font-size: 14px;
}
/* Config blocks */
.config-block {
  background: #fff; border: 1px solid #eaecf0; border-radius: 12px;
  padding: 20px; margin-bottom: 16px;
}
.config-block.highlight {
  border-color: #d0d5dd; background: linear-gradient(135deg, #fff 0%, #f9fafb 100%);
}
.config-block.collapsible { padding: 0; }
.config-block.collapsible > .field-grid { padding: 0 20px 20px; }
.block-title {
  font-size: 13px; font-weight: 600; color: #344054;
  margin-bottom: 16px; padding-bottom: 10px; border-bottom: 1px solid #f2f4f7;
}
.block-title.clickable {
  cursor: pointer; padding: 16px 20px; margin-bottom: 0;
  border-bottom: none; list-style: none; user-select: none;
}
.block-title.clickable::before { content: ''; }
details[open] > .block-title.clickable { border-bottom: 1px solid #f2f4f7; margin-bottom: 0; }

/* Field grid */
.field-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; }
.field-grid.cols-3 { grid-template-columns: repeat(3, 1fr); }

/* Slider row */
.slider-row { display: flex; align-items: center; gap: 12px; }
.slider-val {
  font-size: 12px; font-weight: 500; color: #667085;
  min-width: 32px; text-align: right; font-variant-numeric: tabular-nums;
}

/* Responsive */
@media (max-width: 900px) {
  .node-layout { flex-direction: column; min-height: auto; }
  .node-sidebar { width: 100%; }
  .form-row { flex-direction: column; gap: 12px; }
  .field-grid, .field-grid.cols-3 { grid-template-columns: 1fr; }
  .config-tabs { flex-wrap: wrap; }
  .identity-strip { flex-direction: column; align-items: flex-start; gap: 8px; }
  .section-header { flex-direction: column; gap: 12px; }
}
@media (min-width: 901px) and (max-width: 1100px) {
  .field-grid.cols-3 { grid-template-columns: repeat(2, 1fr); }
  .node-sidebar { width: 180px; }
}
@media (min-width: 1101px) and (max-width: 1400px) {
  .node-sidebar { width: 200px; }
}
</style>
