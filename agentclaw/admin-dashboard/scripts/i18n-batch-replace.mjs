import fs from 'fs'
import path from 'path'

const args = process.argv.slice(2)
const write = args.includes('--write')
const rootArg = args.find(arg => arg.startsWith('--root='))
const root = path.resolve(rootArg ? rootArg.slice('--root='.length) : 'agentclaw/admin-dashboard/src')
const skipDirs = new Set(['locales', '__tests__'])
const filePattern = /\.(vue|js)$/

const globalReplacements = [
  ['>保存<', '>{{ $t(\'common.save\') }}<'],
  ['>取消<', '>{{ $t(\'common.cancel\') }}<'],
  ['>详情<', '>{{ $t(\'common.detail\') }}<'],
  ['>复制<', '>{{ $t(\'common.copy\') }}<'],
  ['>删除<', '>{{ $t(\'common.delete\') }}<'],
  ['>编辑<', '>{{ $t(\'common.edit\') }}<'],
  ['>创建<', '>{{ $t(\'common.create\') }}<'],
  ['>关闭<', '>{{ $t(\'common.close\') }}<'],
  ['>重置<', '>{{ $t(\'common.reset\') }}<'],
  ['title="复制"', ':title="$t(\'common.copy\')"'],
  ['title="删除"', ':title="$t(\'common.delete\')"'],
  ['title="编辑"', ':title="$t(\'common.edit\')"'],
]

const fileReplacements = {
  'views/WorkflowDebug.vue': [
    ['<label>状态:</label>', '<label>{{ $t(\'workflowDebug.status\') }}:</label>'],
    ['<label>当前:</label>', '<label>{{ $t(\'workflowDebug.current\') }}:</label>'],
    ["{{ isEditingState ? '取消' : '编辑' }}", "{{ isEditingState ? $t('common.cancel') : $t('common.edit') }}"],
    ['📺 实时输出', '📺 {{ $t(\'workflowDebug.liveOutput\') }}'],
    ["{{ isRunning ? '流式输出中...' : '等待执行' }}", "{{ isRunning ? $t('workflowDebug.outputRunning') : $t('workflowDebug.outputWaiting') }}"],
    ['<button class="btn-back" @click="goBack">← 返回</button>', '<button class="btn-back" @click="goBack">← {{ $t(\'workflowDebug.back\') }}</button>'],
    ['<h1>🐛 调试工作流: {{ workflowName }}</h1>', '<h1>🐛 {{ $t(\'workflowDebug.title\') }}: {{ workflowName }}</h1>'],
    ['<span class="info-label">已执行:</span>', '<span class="info-label">{{ $t(\'workflowDebug.executed\') }}:</span>'],
    ['<span class="info-value">{{ executedCount }} / {{ nodes.length }} 节点</span>', '<span class="info-value">{{ $t(\'workflowDebug.executedNodes\', { executed: executedCount, total: nodes.length }) }}</span>'],
    ['<span class="info-label">总耗时:</span>', '<span class="info-label">{{ $t(\'workflowDebug.totalTime\') }}:</span>'],
    ['<button @click="startDebug" class="btn-success" :disabled="loading || isRunning">\n            ▶ 开始\n          </button>', '<button @click="startDebug" class="btn-success" :disabled="loading || isRunning">\n            ▶ {{ $t(\'workflowDebug.start\') }}\n          </button>'],
    ['<button @click="resume" class="btn-primary" :disabled="loading || !isPaused">\n              继续\n            </button>', '<button @click="resume" class="btn-primary" :disabled="loading || !isPaused">\n              {{ $t(\'workflowDebug.resume\') }}\n            </button>'],
    ['<button @click="step" class="btn-primary" :disabled="loading || !isPaused">\n              单步\n            </button>', '<button @click="step" class="btn-primary" :disabled="loading || !isPaused">\n              {{ $t(\'workflowDebug.step\') }}\n            </button>'],
    ['<button @click="stop" class="btn-danger" :disabled="loading || isStopped">\n              停止\n            </button>', '<button @click="stop" class="btn-danger" :disabled="loading || isStopped">\n              {{ $t(\'workflowDebug.stop\') }}\n            </button>'],
    ['<div class="human-alert-title">🔴 固定断点：等待人工输入</div>', '<div class="human-alert-title">🔴 {{ $t(\'workflowDebug.humanBreakpointTitle\') }}</div>'],
    ['<span class="human-hint">HumanNode 在调试模式下自动作为固定断点。请输入此节点的输出数据，数据将写入 State。</span>', '<span class="human-hint">{{ $t(\'workflowDebug.humanBreakpointHint\') }}</span>'],
    ['<button class="btn-success" @click="showHumanInputModal">📝 输入数据并继续</button>', '<button class="btn-success" @click="showHumanInputModal">📝 {{ $t(\'workflowDebug.submitAndContinue\') }}</button>'],
    ['<h3>📋 节点列表</h3>', '<h3>📋 {{ $t(\'workflowDebug.nodeList\') }}</h3>'],
    ['<button class="btn-text" @click="clearAllBreakpoints">清除断点</button>', '<button class="btn-text" @click="clearAllBreakpoints">{{ $t(\'workflowDebug.clearBreakpoints\') }}</button>'],
    ['<h3>📜 执行历史</h3>', '<h3>📜 {{ $t(\'workflowDebug.history\') }}</h3>'],
    ['<div v-if="!session || !history.length" class="empty-state">\n            暂无历史记录\n          </div>', '<div v-if="!session || !history.length" class="empty-state">\n            {{ $t(\'workflowDebug.noHistory\') }}\n          </div>'],
    ['<h3>🔄 工作流可视化</h3>', '<h3>🔄 {{ $t(\'workflowDebug.graph\') }}</h3>'],
    ['<button class="btn-text" @click="clearOutput">清空</button>', '<button class="btn-text" @click="clearOutput">{{ $t(\'common.reset\') }}</button>'],
    ['<input type="checkbox" v-model="autoScroll" /> 自动滚动', '<input type="checkbox" v-model="autoScroll" /> {{ $t(\'workflowDebug.autoScroll\') }}'],
    ['<h3>👤 Human 节点输入 - 固定断点</h3>', '<h3>👤 {{ $t(\'workflowDebug.humanInputTitle\') }}</h3>'],
    ['<p><strong>节点:</strong> {{ session?.current_node }}</p>', '<p><strong>{{ $t(\'workflowDebug.node\') }}:</strong> {{ session?.current_node }}</p>'],
    ['<div class="hint-title">📋 输入提示</div>', '<div class="hint-title">📋 {{ $t(\'workflowDebug.inputHintTitle\') }}</div>'],
    ['<label>请输入此节点的输出数据 (JSON 格式):</label>', '<label>{{ $t(\'workflowDebug.humanInputJsonLabel\') }}:</label>'],
    ['<button class="btn-success" @click="submitHumanInput">✓ 提交并继续执行</button>', '<button class="btn-success" @click="submitHumanInput">✓ {{ $t(\'workflowDebug.submitAndContinue\') }}</button>'],
    ['<h3>▶ 开始调试: {{ workflowName }}</h3>', '<h3>▶ {{ $t(\'workflowDebug.startDebug\') }}: {{ workflowName }}</h3>'],
    ['<div class="hint-title">📋 输入要求</div>', '<div class="hint-title">📋 {{ $t(\'workflowDebug.inputRequirementTitle\') }}</div>'],
    ['<label>输入数据 (JSON 格式):</label>', '<label>{{ $t(\'workflowDebug.startInputJsonLabel\') }}:</label>'],
    ['<label>Thread ID (可选):</label>', '<label>{{ $t(\'workflowDebug.threadIdOptional\') }}:</label>'],
    ['<button class="btn-primary" @click="executeDebug">开始执行</button>', '<button class="btn-primary" @click="executeDebug">{{ $t(\'workflowDebug.execute\') }}</button>'],
  ],
  'views/AgentChat.vue': [
    ['<span>参数配置</span>', '<span>{{ $t(\'agentChat.configTitle\') }}</span>'],
    ["{{ formDataFileNames[field.name] || '已上传' }}", "{{ formDataFileNames[field.name] || $t('agentChat.uploaded') }}"],
    ["{{ formFieldUploading[field.name] ? '上传中...' : field.type === 'image-upload' ? '选择图片' : field.type === 'audio-upload' ? '选择音频' : '选择文件' }}", "{{ formFieldUploading[field.name] ? $t('agentChat.uploading') : field.type === 'image-upload' ? $t('agentChat.selectImage') : field.type === 'audio-upload' ? $t('agentChat.selectAudio') : $t('agentChat.selectFile') }}"],
    ["{{ formFieldUploading[field.name] ? '上传中...' : '添加文件' }}", "{{ formFieldUploading[field.name] ? $t('agentChat.uploading') : $t('agentChat.addFiles') }}"],
    ['<button v-if="canStartWorkflow" class="btn-start" @click="startWorkflow">启动工作流</button>', '<button v-if="canStartWorkflow" class="btn-start" @click="startWorkflow">{{ $t(\'agentChat.startWorkflow\') }}</button>'],
    ["<p>{{ workflowDesc || '有什么可以帮你的？' }}</p>", "<p>{{ workflowDesc || $t('agentChat.welcomeFallback') }}</p>"],
    ['<span class="show-all-btn mono-font">{{ hiddenCount }} 条历史消息，点击显示全部</span>', '<span class="show-all-btn mono-font">{{ $t(\'agentChat.showAllHistory\', { count: hiddenCount }) }}</span>'],
    ["{{ processCollapsed ? '展开思考过程' : '收起思考过程' }}", "{{ processCollapsed ? $t('agentChat.expandProcess') : $t('agentChat.collapseProcess') }}"],
    [`<button class="info-panel-toggle" @click="infoPanelCollapsed = !infoPanelCollapsed" :title="infoPanelCollapsed ? '展开面板' : '收起面板'">`, `<button class="info-panel-toggle" @click="infoPanelCollapsed = !infoPanelCollapsed" :title="infoPanelCollapsed ? $t('agentChat.expandPanel') : $t('agentChat.collapsePanel')">`],
    ['<span>工作流信息</span>', '<span>{{ $t(\'agentChat.workflowInfo\') }}</span>'],
    ["<div class=\"section-content\">{{ workflowDesc || '暂无描述' }}</div>", "<div class=\"section-content\">{{ workflowDesc || $t('workflows.noDescription') }}</div>"],
    [`<label class="filter-toggle" :title="preFilterEnabled ? '关闭后所有技能和工具直接可用，响应更快但 token 消耗更高' : '开启后先用小模型筛选相关技能和工具，减少 token 消耗但增加少量延迟'">`, `<label class="filter-toggle" :title="preFilterEnabled ? $t('agentChat.prefilterDisabledHint') : $t('agentChat.prefilterEnabledHint')">`],
    ['<span>智能筛选</span>', '<span>{{ $t(\'agentChat.prefilter\') }}</span>'],
    ['<span>技能配置</span>', '<span>{{ $t(\'agentChat.skillsConfig\') }}</span>'],
    ['<div v-if="toolConfigLoading">加载中...</div>', '<div v-if="toolConfigLoading">{{ $t(\'common.loading\') }}</div>'],
    ['<span>已启用: {{ enabledSkillsCount }}/{{ availableSkills.length }}</span>', '<span>{{ $t(\'agentChat.enabledSkills\', { enabled: enabledSkillsCount, total: availableSkills.length }) }}</span>'],
    ['<div v-if="availableSkills.length === 0" class="tool-empty">暂无可用技能</div>', '<div v-if="availableSkills.length === 0" class="tool-empty">{{ $t(\'agentChat.noSkills\') }}</div>'],
    ['<span>工具配置</span>', '<span>{{ $t(\'agentChat.toolsConfig\') }}</span>'],
    [`{{ group.tools.every(t => !t.disabled) ? '全部禁用' : '全部启用' }}`, `{{ group.tools.every(t => !t.disabled) ? $t('agentChat.disableAll') : $t('agentChat.enableAll') }}`],
    ['<div v-if="toolGroups.length === 0" class="tool-empty">暂无可用工具</div>', '<div v-if="toolGroups.length === 0" class="tool-empty">{{ $t(\'agentChat.noTools\') }}</div>'],
    ['<span>使用量</span>', '<span>{{ $t(\'agentChat.usage\') }}</span>'],
    ['<span class="section-count">{{ messages.length }} 条</span>', '<span class="section-count">{{ $t(\'agentChat.messagesCount\', { count: messages.length }) }}</span>'],
    ['<div class="section-content">当前会话已记录 {{ messages.length }} 条消息</div>', '<div class="section-content">{{ $t(\'agentChat.sessionRecorded\', { count: messages.length }) }}</div>'],
    ['<div v-if="!infoPanelCollapsed" class="panel-actions"><button class="btn-back" @click="goBack">← 返回工作流</button></div>', '<div v-if="!infoPanelCollapsed" class="panel-actions"><button class="btn-back" @click="goBack">← {{ $t(\'agentChat.backToWorkflow\') }}</button></div>'],
  ],
  'views/Settings.vue': [
    ['label="默认超时 (秒)"', ':label="t(\'settingsForm.global.defaultTimeout\')"'],
    ['label="递归限制"', ':label="t(\'settingsForm.global.recursionLimit\')"'],
    ['label="最大工具调用轮数"', ':label="t(\'settingsForm.global.maxToolRounds\')"'],
    ['label="最大上下文消息数"', ':label="t(\'settingsForm.global.maxContextMessages\')"'],
    ['label="工具结果最大长度"', ':label="t(\'settingsForm.global.toolResultMaxLength\')"'],
    ['label="最大消息长度"', ':label="t(\'settingsForm.global.maxMessageLength\')"'],
    ['title="数据库"', ':title="t(\'settingsForm.infra.database\')"'],
    ['title="文件存储"', ':title="t(\'settingsForm.infra.fileStorage\')"'],
    ['title="认证"', ':title="t(\'settingsForm.infra.auth\')"'],
    ['title="定时任务"', ':title="t(\'settingsForm.infra.scheduler\')"'],
    ['label="存储目录"', ':label="t(\'settingsForm.infra.storageDir\')"'],
    ['label="最大文件 (MB)"', ':label="t(\'settingsForm.infra.maxFileMb\')"'],
    ["{{ infraConfig.upload.minio_secure ? '是' : '否' }}", "{{ infraConfig.upload.minio_secure ? t('common.yes') : t('common.no') }}"],
    ["{{ infraConfig.auth.admin_token || '未设置' }}", "{{ infraConfig.auth.admin_token || t('settingsForm.infra.unset') }}"],
    ["{{ infraConfig.auth.workflow_api_key || '未设置' }}", "{{ infraConfig.auth.workflow_api_key || t('settingsForm.infra.unset') }}"],
    ['认证凭据通过环境变量配置，不可在此修改', '{{ t(\'settingsForm.infra.authManagedByEnv\') }}'],
    ["{{ infraConfig.scheduler.enabled ? '是' : '否' }}", "{{ infraConfig.scheduler.enabled ? t('common.yes') : t('common.no') }}"],
    ['label="时区"', ':label="t(\'settingsForm.infra.timezone\')"'],
    ['label="最大并行数"', ':label="t(\'settingsForm.infra.maxWorkers\')"'],
    ["{{ infraConfig.scheduler.coalesce ? '是' : '否' }}", "{{ infraConfig.scheduler.coalesce ? t('common.yes') : t('common.no') }}"],
    ['label="最大实例数"', ':label="t(\'settingsForm.infra.maxInstances\')"'],
    ['label="名称"', ':label="t(\'settingsForm.workflow.name\')"'],
    ['label="版本"', ':label="t(\'settingsForm.workflow.version\')"'],
    ['label="描述"', ':label="t(\'common.description\')"'],
    ['label="超时 (秒)"', ':label="t(\'common.timeout\')"'],
    ['label="断连取消"', ':label="t(\'settingsForm.workflow.cancelOnDisconnect\')"'],
    ['label="启用追踪"', ':label="t(\'settingsForm.workflow.tracing\')"'],
    ['label="需要认证"', ':label="t(\'settingsForm.workflow.authRequired\')"'],
    ['label="允许角色"', ':label="t(\'settingsForm.workflow.allowedRoles\')"'],
    ['placeholder="逗号分隔，如 admin,user"', ':placeholder="t(\'settingsForm.workflow.allowedRolesPlaceholder\')"'],
    ['label="速率限制"', ':label="t(\'settingsForm.workflow.rateLimit\')"'],
    ['placeholder="如 10/min"', ':placeholder="t(\'settingsForm.workflow.rateLimitPlaceholder\')"'],
    ['label="开场白"', ':label="t(\'workflowConfig.workflow.welcome\')"'],
    ['placeholder="节点描述"', ':placeholder="t(\'settingsForm.node.descriptionPlaceholder\')"'],
    ['label="错误策略"', ':label="t(\'workflowConfig.fields.errorStrategy\')"'],
    ['label="最大重试次数"', ':label="t(\'settingsForm.node.maxRetries\')"'],
    ['label="重试延迟 (秒)"', ':label="t(\'settingsForm.node.retryDelay\')"'],
    ['label="输出给用户"', ':label="t(\'workflowConfig.fields.outputToUser\')"'],
    ['label="输出 Key"', ':label="t(\'workflowConfig.fields.outputKey\')"'],
    ['placeholder="状态中的输出键名"', ':placeholder="t(\'settingsForm.node.outputKeyPlaceholder\')"'],
    ['label="Fallback 值"', ':label="t(\'workflowConfig.fields.fallbackValue\')"'],
    ['placeholder="错误策略为 FALLBACK 时使用"', ':placeholder="t(\'settingsForm.node.fallbackValuePlaceholder\')"'],
    ['label="模型"', ':label="t(\'workflowConfig.fields.model\')"'],
    ['placeholder="使用默认模型"', ':placeholder="t(\'settingsForm.node.useDefaultModel\')"'],
    ['label="使用快速模型"', ':label="t(\'workflowConfig.fields.fastModel\')"'],
    ['label="流式输出"', ':label="t(\'workflowConfig.fields.stream\')"'],
    ['label="输出格式"', ':label="t(\'workflowConfig.fields.outputFormat\')"'],
    ['label="备选模型"', ':label="t(\'workflowConfig.fields.fallbackModel\')"'],
    ['placeholder="无"', ':placeholder="t(\'common.none\')"'],
    ['label="自动 Fallback"', ':label="t(\'workflowConfig.fields.autoFallback\')"'],
    ['label="Fallback 阈值"', ':label="t(\'workflowConfig.fields.fallbackThreshold\')"'],
    ['label="工具选择"', ':label="t(\'workflowConfig.fields.toolChoice\')"'],
    ['label="启用内置技能"', ':label="t(\'workflowConfig.fields.enableBuiltinSkills\')"'],
    ['label="启用内置工具"', ':label="t(\'workflowConfig.fields.enableBuiltinTools\')"'],
    ['label="Agent 风格"', ':label="t(\'workflowConfig.fields.agentStyle\')"'],
    ['label="使用上下文"', ':label="t(\'workflowConfig.fields.useContext\')"'],
    ['label="保存到上下文"', ':label="t(\'workflowConfig.fields.saveToContext\')"'],
    ['label="压缩阈值 (tokens)"', ':label="t(\'settingsForm.node.compressionThreshold\')"'],
    ['placeholder="使用默认"', ':placeholder="t(\'settingsForm.node.useDefault\')"'],
    ['label="注入文件"', ':label="t(\'workflowConfig.fields.injectFiles\')"'],
    ['label="反馈字段"', ':label="t(\'workflowConfig.fields.feedbackField\')"'],
    ['label="待处理状态"', ':label="t(\'workflowConfig.fields.pendingStatus\')"'],
    ['label="审批模式"', ':label="t(\'workflowConfig.fields.approvalMode\')"'],
    ['label="超时策略"', ':label="t(\'workflowConfig.fields.timeoutAction\')"'],
    ['label="写入上下文"', ':label="t(\'settingsForm.node.writeToContext\')"'],
    ['description="请从左侧选择一个节点"', ':description="t(\'settingsForm.node.selectNode\')"'],
    ['description="该工作流暂无节点"', ':description="t(\'settingsForm.node.noNodes\')"'],
    ['description="请选择一个工作流"', ':description="t(\'settings.selectWorkflowFirst\')"'],
    ['环境变量', '{{ t(\'settingsForm.infra.environmentVariable\') }}'],
    ['message.success(\'全局配置已保存\')', 'message.success(t(\'settingsForm.messages.globalSaved\'))'],
    ['message.warning(\'后端接口未实现，配置暂未持久化\')', 'message.warning(t(\'settingsForm.messages.backendNotPersisted\'))'],
    ['message.success(\'配置已保存\')', 'message.success(t(\'settingsForm.messages.configSaved\'))'],
    ['message.error(\'获取工作流详情失败\')', 'message.error(t(\'settingsForm.messages.fetchWorkflowFailed\'))'],
    ['message.success(\'工作流配置已保存\')', 'message.success(t(\'settingsForm.messages.workflowSaved\'))'],
    ['message.error(\'获取工作流节点失败\')', 'message.error(t(\'settingsForm.messages.fetchNodesFailed\'))'],
    ['message.success(\'节点配置已保存\')', 'message.success(t(\'settingsForm.messages.nodeSaved\'))'],
  ],
  'views/WorkflowConfig.vue': [
    ['import { computed, onMounted, ref } from \'vue\'', 'import { computed, onMounted, ref } from \'vue\'\nimport { useI18n } from \'vue-i18n\''],
    ['const message = useMessage()', 'const message = useMessage()\nconst { t } = useI18n()'],
    ['<h3 class="section-title">工作流配置</h3>', '<h3 class="section-title">{{ $t(\'workflowConfig.workflow.title\') }}</h3>'],
    ['<p class="section-desc">控制工作流的全局行为参数</p>', '<p class="section-desc">{{ $t(\'workflowConfig.workflow.description\') }}</p>'],
    ['<div class="sidebar-title">节点列表</div>', '<div class="sidebar-title">{{ $t(\'workflowConfig.node.list\') }}</div>'],
    ['const breadcrumbs = computed(() => [{ text: \'智能体\', to: \'/workflows\' }, { text: workflowId.value, to: `/workflows/${workflowId.value}` }, { text: \'配置\' }])', 'const breadcrumbs = computed(() => [{ text: t(\'workflows.title\'), to: \'/workflows\' }, { text: workflowId.value, to: `/workflows/${workflowId.value}` }, { text: t(\'common.configure\') }])'],
    ['message.success(\'工作流配置已保存\')', 'message.success(t(\'workflowConfig.messages.workflowSaved\'))'],
    ['message.success(\'节点配置已保存\')', 'message.success(t(\'workflowConfig.messages.nodeSaved\'))'],
    ['message.error(\'加载配置失败\')', 'message.error(t(\'workflowConfig.messages.loadFailed\'))'],
  ],
}

let changedFiles = 0
let changedSnippets = 0

function walk(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      if (skipDirs.has(entry.name)) continue
      walk(path.join(dir, entry.name))
      continue
    }
    const file = path.join(dir, entry.name)
    if (!filePattern.test(file)) continue
    const original = fs.readFileSync(file, 'utf8')
    let next = original
    const rel = path.relative(root, file).replace(/\\/g, '/')
    const scopedReplacements = fileReplacements[rel] || []
    let fileChanges = 0
    for (const [from, to] of [...globalReplacements, ...scopedReplacements]) {
      if (!next.includes(from)) continue
      fileChanges += next.split(from).length - 1
      next = next.split(from).join(to)
    }
    if (!fileChanges) continue
    changedFiles += 1
    changedSnippets += fileChanges
    console.log(`${write ? 'WRITE' : 'DRY'} ${path.relative(process.cwd(), file)}  replacements=${fileChanges}`)
    if (write) fs.writeFileSync(file, next)
  }
}

walk(root)
console.log(`done files=${changedFiles} replacements=${changedSnippets} mode=${write ? 'write' : 'dry-run'}`)
