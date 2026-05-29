# Changelog

All notable changes to AgentClaw will be documented in this file.

## [1.1.0] - 2026-05-29

**Added**

- 公开工作流页面新增匿名 public user 会话：访问分享页会生成独立 cookie，并将 public conversation 绑定到匿名用户；最近会话列表现在只展示当前匿名用户自己的会话，支持未登录用户多会话。
- 新增公开工作流单页发布相关能力，Dashboard 可在 public-chat 模式下只开放公开聊天入口，公开运行、会话、音频接口统一携带 share token 与 same-origin public session 校验。
- 新增 Dashboard 聊天语音能力，支持工作流级 ASR/TTS 开关、浏览器录音转写、助手消息手动播放语音，以及 Admin/Public 两套音频 API。
- 新增音频服务与 provider registry，提供 OpenAI 兼容 ASR/TTS 适配，并让 `DocumentNode` 可对音频文件调用 ASR 后注入文本内容。
- Dashboard 模型配置支持维护 `speech2text` / `tts` 模型类型，并可配置默认 ASR 模型、默认 TTS 模型、TTS 声音、音频格式和 ASR 支持的音频后缀。
- 新增 ASR/TTS 云端适配设计文档和基础实施计划，覆盖音频 provider 抽象、模型配置格式、Workflow 聊天语音开关、Public Agent 音频安全边界和实施批次。

**Changed**

- 项目版本从 `1.0.9` 更新为 `1.1.0`，同步 `VERSION`、运行时 fallback 版本、Python 包元数据、`uv.lock`、Dashboard package 元数据和 README 徽章。
- 公开分享访问现在必须显式携带有效 `share_token`，public session 只证明页面来源，不再替代分享 token。
- 公开页面请求统一保留 `share_token`，避免分享页刷新、切换会话或发送消息时退化成 403。
- 公开会话 ID 默认长度从短随机串提升到 24 位后缀，降低可猜测性。
- 公开访问限流支持默认限流配置和 Redis 后端；无 Redis 时仍可回退到内存限流，除非显式要求 Redis。
- 公网发布相关安全配置支持通过环境变量收紧 Admin API、Dashboard、MCP routes、Scheduler API、Channel routes、API docs、CORS、Public Agent 请求体/消息长度和上传体积限制。
- Public Agent 工具策略新增 `allow`、`block_builtin` 和 `block_all` 模式，并支持在阻断内置工具时显式放行指定工具。
- 海龟汤主持人在选型、确认汤面、已结束等阶段收到无关内容时，会返回阶段相关引导，避免游戏开始前误判为提问结论。
- 模型配置弹窗按模型类型区分渠道：chat 模型保留 chat 渠道，ASR/TTS 模型使用独立音频渠道，`embedding` / `rerank` 模型不再显示或保存 `channel`。
- 会话模型选择器和模型服务将 ASR/TTS 与 embedding/rerank 一样视为非对话模型，避免被选为默认聊天、快速、降级或视觉模型。
- 重新构建 Dashboard `dist` 产物，使公开分享会话、聊天语音、模型配置和版本更新进入运行包。

**Fixed**

- 修复 public share token 中包含非 ASCII 字符时 `secrets.compare_digest()` 抛出 `TypeError` 并导致 500 的问题，现在会统一按 UTF-8 bytes 做常量时间比较。
- 修复公开分享页可通过 `/dashboard/agent/<任意 id>?conversation_id=...` 绕过分享 token 直接访问对应智能体的问题。
- 修复公开分享页删除会话失败、最近会话缺失，以及打开分享链接时短暂闪现 Dashboard 主页的问题。

**Tests**

- 新增/扩展公开访问、公开执行、公开会话、部署安全配置、Public Agent 工具策略、上传限制、会话服务、海龟汤模板、Admin/Public 音频 API、音频服务、DocumentNode ASR、工作流聊天语音、Settings 模型配置和 Dashboard 前端回归测试。

## [1.0.9] - 2026-05-22

**Added**

- 新增 Dashboard “模板库”页面，支持浏览 AgentClaw 随包发布的官方模板、按分类/关键词筛选、查看推荐输入，并一键导入到当前项目或导入后直接打开体验。
- 新增 `agentclaw.agent_square` 官方模板库包，将原 `agentclaw/examples` 示例迁移为可复制模板，并随包提供 `Hello World`、意图路由、工具调用、人工审核、并行分析、GIF Creator、MCP Agent、数据报告、周报、文档分析、知识库问答等模板。
- 新增两个游戏型模板：`海龟汤主持人` 和 `AI 狼人杀主持人`。狼人杀模板提供 12 人狼王守卫局的主状态机与角色子工作流，支持隐藏身份、私有视角、警长竞选、放逐、遗言、警徽移交、猎人/狼王开枪、白痴翻牌、自爆和模型复盘。
- 新增模板库后端 API：列出模板、查询导入状态、复制模板到项目 `agents/`、更新 `agents/__init__.py`、热注册导入后的工作流，并兼容旧的 Agent Square 列表接口。
- 新增 `WorkflowTemplate`，支持用变量参数化节点 ID、提示词、输出字段和边，实例化为普通 `Workflow`，便于复用结构化工作流定义。
- 新增 `StateExtractNode` 和 `graph.state_path` 工具，用于通过 LLM 从文本中抽取结构化状态，并支持点路径读写、append、shallow merge 和 deep merge。
- 新增 `HumanInput` 输入模式，`HumanNode` 现在可以显式声明文本框、按钮、确认按钮或基于 state 动态生成的输入控件。
- 新增 `SubWorkflowNode` 的嵌套状态映射能力，支持 `readonly_input_map`、`state_map`、嵌套 `output_map`、实例 ID、派生 thread_id、自定义 thread_id、合并策略，以及可选隐藏子工作流内部节点事件。
- 新增 SubWorkflowNode 对子工作流 HumanNode 中断的桥接能力，父工作流可以中断、恢复，并把用户输入继续传回子工作流。
- 新增中文最佳实践文档，补充声明式节点、显式业务 state、`StateExtractNode`、多轮 `HumanNode`、多角色 `SubWorkflowNode` 和 `WorkflowTemplate` 的选型建议与示例。
- 新增 Claw Apps / 模板库展示方案文档，梳理官方模板库的产品入口、导入语义、目录约定、打包边界和首批模板选择原则。

**Changed**

- 项目版本从 `1.0.8` 更新为 `1.0.9`，同步 `VERSION`、运行时 fallback 版本、Python 包元数据、`uv.lock`、Dashboard package 元数据和 README 徽章。
- Python 发布包现在包含 `agent_square/**/*`，官方模板库会随 `agentclaw-ai` 一起分发；旧 `agentclaw/examples` 标准项目示例已迁移为模板库应用。
- 模板导入后的工作流现在会作为项目 `agents.<app_id>` 包加载，并继承当前项目模型、MCP 与 skills 配置。
- Dashboard 智能体列表默认只展示用户工作流，内置模板改由“模板库”导入；打开工作流时会携带模板推荐输入作为一次性 `seed_input`。
- AgentChat 现在会根据 workflow schema 区分直接聊天输入和参数启动工作流；纯参数型工作流会在参数面板外显示启动提示与“开始运行”按钮，运行时自动创建会话，并说明不能直接输入的原因。
- AgentChat 参数启动入口的“开始运行”按钮增加深色 fallback 背景，避免主题变量未加载时入口不可见。
- AI 狼人杀模板收敛了流程与提示词边界：玩家操作通过结构化动作触发，AI 发言遵守夜间信息边界、验人时间线、警长票/放逐票语义，猎人和狼王开枪状态按死亡原因结算。
- AgentChat 支持 HumanNode 的按钮输入模式、结构化按钮值恢复、`next_input_info`、中断后输入控件恢复、运行中流式草稿本地持久化，以及空会话的 workflow welcome 展示。
- 工作流运行时默认 `recursion_limit` 改为 `0`，表示 AgentClaw 层不限制；传给 LangGraph 时映射为足够大的运行时上限，仍可显式设置正数限制。
- 工作流配置自动发现现在会把全局项目目录、`models.json`、`mcp.json` 和 skills 目录作为候选路径，支持从模板库导入到 `agents/<template>/...` 的嵌套工作流。
- 内置工作流结构输出新增 `agent_square_app_id` 和 `recommended_input`，工作流列表 API 同步暴露这些字段。
- Python 顶层导出新增 `WorkflowTemplate`、`HumanInput`、`SubWorkflowNode` 和 `StateExtractNode`，应用代码可直接从 `agentclaw` 导入这些新能力。
- 同步函数节点和同步 `CustomNode.process()` 改为在线程中执行，避免阻塞事件循环。
- MCP 默认工具超时从 300 秒收敛为 30 秒；`python`、`javascript`、`shell`、`execute_sudo_command` 等长任务工具默认保留 120 秒，并允许环境变量统一覆盖。
- MCP 配置支持 JSONC 注释、`type: "remote"` 兼容写法、URL server 自动传输检测结果回写；远程 HTTP MCP 工具调用不再被同 server 锁串行化，stdio server 仍保持串行。
- 重新构建 Dashboard `dist` 产物，使模板库、聊天输入模式、会话恢复和版本更新进入运行包。

**Fixed**

- 修复 Dashboard 新建、导入或热注册资源后立即打开详情页时，前端偶发读到旧状态或 404 的问题，关键读取路径加入短暂 readiness retry。
- 修复 AgentChat 在工作流中断、刷新或远端会话暂为空时丢失流式输出/等待输入状态的问题；现在会优先保留本地更完整的消息快照，并恢复按钮输入。
- 修复运行中流式草稿最终保存时重复追加 assistant 消息的问题，完成时会替换已有草稿。
- 修复 HumanNode 按钮值为 `False`、数字或结构化值时被字符串化或丢失的问题。
- 修复 Admin 通过文件热注册包含 `dataclass` 自定义节点的工作流时，模块未提前写入 `sys.modules` 可能导致加载失败的问题。
- 修复并行分支更新嵌套 dict 状态时互相覆盖的问题。
- 修复动态条件边返回节点列表时内置执行器未按并行分支执行的问题。
- 修复 MCP 工具超时后连接状态残留的问题，超时会断开并清理客户端状态。

**Tests**

- 新增模板库和 Agent Square 测试，覆盖模板 manifest、示例迁移、资源文件复制、项目导入、热注册、Dashboard 导入 API、海龟汤和狼人杀模板结构。
- 新增工作流运行时测试，覆盖 `WorkflowTemplate`、`StateExtractNode`、嵌套 state path、SubWorkflowNode 多实例隔离、子工作流中断恢复、并行分支合并、动态并行条件边和事件隐藏。
- 新增 HumanNode 输入模式测试，覆盖文本/按钮混合模式、审批默认按钮、动态按钮、结构化恢复值和 `False` 按钮值。
- 新增 Dashboard 前端测试，覆盖模板库页面、聊天按钮输入、seed input、welcome 消息、流式草稿持久化、中断态恢复、对话合并、参数启动型工作流入口和 eventual consistency retry。
- 新增 AgentChat 启动按钮样式回归测试，确保“开始运行”按钮拥有非透明 fallback 背景。
- 新增 Admin API 契约测试，覆盖模板库列表/导入接口、工作流列表的模板元数据，以及文件热注册 `dataclass` 节点工作流。
- 新增模板聊天入口结构测试，确保官方模板至少提供 `user_input` 直接输入或 `form_config` 参数启动路径，并覆盖 `08 数据报告生成器`、`09 周报生成器`、`10 Document Analyzer` 的预期输入结构。
- 新增 MCP 测试，覆盖 JSONC 配置、remote 类型兼容、自动传输回写、工具超时、超时断连，以及远程 HTTP 并发/stdio 串行调用差异。
- 新增事件循环安全、运行时配置、模板打包、Demo2 模型配置和 Workflow 设置 API 契约测试。

## [1.0.8] - 2026-05-08

**Added**

- 新增内置 `image-generation` skill，支持 OpenAI GPT Image、Nano Banana 和 Volcengine Ark Seedream 三个图片生成渠道，并提供对应 provider reference 与命令行 runner。
- 图片生成 runner 默认保存到 `generated_images`，JSON 结果包含 `output_dir` 与 `absolute_output_dir`，便于后续工具把本地生成文件转为浏览器可访问链接。
- 新增图片生成 skill 测试，覆盖 provider 资源加载、脚本输出目录、环境变量去重、`.env` 自动加载、模型别名、Seedream 密钥安全和内置 skill 读取。

**Changed**

- 项目运行时版本从 `1.0.7` 更新为 `1.0.8`，同步 `VERSION`、运行时 fallback 版本、管理后台 package 元数据和 README 徽章；Python pip 包元数据暂保持 `1.0.7`，本次不发布。
- 图片生成渠道环境变量收敛为每个 provider 一个 key：OpenAI 使用 `OPENAI_IMAGE_KEY`，Nano Banana 使用 `GOOGLE_IMAGE_KEY`，Seedream 使用 `ARK_API_KEY`；OpenAI 兼容渠道仅通过可选 `OPENAI_BASE_URL` 或 `--base-url` 覆盖 endpoint。
- 图片生成 runner 会自动读取项目 `.env` 并补入当前脚本进程环境，不再要求调用方先手动执行 `set -a; . ./.env; set +a`。
- Agentic 内置提示词明确要求 Markdown 图片只能使用浏览器可访问 URL，例如 `/api/download/...`、签名 `/api/files/...?token=...`、HTTP(S) 或 data URL。
- `image-generation` skill 文档明确本地 `output_paths`、`output_dir`、`absolute_output_dir` 不是浏览器 URL；若脚本只返回本地文件路径，最终展示前应先调用 `create_download_url`。

**Fixed**

- 修复内置智能体生成图片后可能把 `generated_images/...` 本地相对路径直接写入 Markdown，导致 Dashboard 将其解析为 `/dashboard/generated_images/...` 并无法展示图片的问题。
- 修复图片生成脚本直接运行时无法读取项目 `.env` 中 provider API Key，容易因环境变量未 export 而失败的问题。

**Tests**

- 新增 Agentic prompt 回归测试，确保提示词不再允许 `URL-or-path`，并明确要求本地图片文件先转换为浏览器可访问下载 URL。
- 扩展内置 skill 描述测试，覆盖 `image-generation` skill 的高层路由描述。

## [1.0.7] - 2026-05-07

**Changed**

- 项目版本从 `1.0.6` 更新为 `1.0.7`，同步 `VERSION`、Python 包元数据、`uv.lock`、管理后台 package 元数据和 README 徽章。
- README / README_CN 的 Agent Creator 演示从内嵌 MP4 改为直接展示 GIF，提升 GitHub / PyPI 等页面上的预览兼容性。
- Python 包元数据改用 SPDX `license = "Apache-2.0"`，并将构建后端要求提升到支持该格式的 setuptools 版本，避免构建时出现 license 元数据弃用告警。

**Fixed**

- 修复 1.0.6 真实 `uv pip install agentclaw-ai` 后，导入 AgentClaw 仍会打印 LangGraph/LangChain `allowed_objects` 的 `LangChainPendingDeprecationWarning`；过滤器现在按 LangChain 的实际 warning 类型精确匹配。

**Tests**

- 补充 warning 过滤测试，覆盖 LangChain pending deprecation warning 类本身，避免只匹配普通 `Warning` 而在真实安装环境中失效。

## [1.0.6] - 2026-05-07

**Changed**

- 项目版本从 `1.0.5` 更新为 `1.0.6`，同步 `VERSION`、Python 包元数据、`uv.lock`、管理后台 package 元数据和 README 徽章。
- `pip install agentclaw-ai` 现在默认安装完整运行依赖，包含 Redis、文档解析、知识库、调度器、浏览器工具、Windows 桌面工具、飞书/钉钉等渠道依赖，保持与 README 中的默认安装方式一致。
- Quick Start / Deployment 文档改为以 `pip install agentclaw-ai` 和 `uv pip install agentclaw-ai` 为主；浏览器自动化只在缺少本机 Chrome/Chromium/Edge 时提示额外执行 `playwright install chromium`。

**Fixed**

- 修复 PyPI 1.0.5 默认安装缺少 Redis、Playwright、APScheduler、MarkItDown、Milvus Lite、渠道 SDK 等依赖，导致浏览器操作、Redis、知识库、调度和渠道能力安装后不可用的问题。
- 修复启用企业微信 bot 渠道时，wheel 中没有 `node_modules/@wecom/aibot-node-sdk` 会导致 Node worker 直接 `ERR_MODULE_NOT_FOUND` 的问题；启动 worker 前会检查并通过 `npm install --omit=dev --no-audit --no-fund` 自动安装缺失的 npm 依赖。
- 修复企业微信 worker 启动失败时只显示泛化 “failed to start” 的问题，现在会保留并展示 worker 上报的具体错误。
- 修复部分 LangGraph/LangChain 版本启动时打印 `allowed_objects` 默认值即将变化的 `LangChainPendingDeprecationWarning`；AgentClaw 现在显式创建 checkpoint serializer，并仅过滤这条第三方启动噪声。

**Tests**

- 新增 PyPI distribution 元数据测试，覆盖默认依赖必须包含完整运行能力。
- 新增企业微信 worker 依赖自修复测试，覆盖 npm 依赖缺失时安装、已存在时跳过安装。
- 新增启动 warning 过滤测试，确保只过滤 LangGraph `allowed_objects` 这条噪声，不隐藏其他 warning。

## [1.0.5] - 2026-05-06

**Added**

- Dashboard 系统配置新增“内置智能体”配置页，支持查看与修改内置智能体的 `Temperature`、`Top P`、备选模型、自动降级、降级阈值和全局记忆；每个配置项提供图标式还原按钮，还原为本地待保存状态，保存后才正式生效。
- Settings Admin API 新增工作流字段和节点字段的单项 reset 端点，用于后续统一配置页复用默认值还原能力。
- Settings Admin API 新增 `models.json` 读写端点，保存模型配置时会保留已脱敏密钥并热更新运行中工作流的 LLMManager。
- AgentChat 前端新增 `agentRunManager`，按 public/admin、workflow、conversation 管理正在运行的前端请求快照、订阅和取消入口，为离开页面后继续运行与回来恢复状态提供运行态基础。
- Dashboard 总览时间范围接入 `24h` / `7d` / `30d`，统计卡片、工作流列表和最近 Trace 请求都会使用同一个选中时间窗口。
- Dashboard 系统配置新增“模型配置”页，可通过简洁列表、添加/编辑弹窗和默认模型下拉框维护 `models.json`，并在保存后热更新模型信息；`vision` 调整为 chat 模型的“支持视觉”选项。
- 知识库文档列表新增删除操作、处理中状态轮询、解析失败原因内联展示，以及对应中英文文案。
- 新增全局记忆、Dashboard 时间范围、内置智能体配置、AgentChat 后台运行、知识库文档状态/删除、Settings API 和 Windows PowerShell Unicode 执行测试覆盖。

**Changed**

- 项目版本从 `1.0.4` 更新为 `1.0.5`，同步 `VERSION`、Python 包元数据、`uv.lock`、管理后台 package 元数据和 README 徽章。
- PyPI 发布包名改为 `agentclaw-ai`，以避开已占用的 `agentclaw` distribution；Python import 包名和 CLI 命令仍保持 `agentclaw`。
- README 快速开始改为以 `pip install agentclaw-ai` / `uv pip install agentclaw-ai` 和 `agentclaw up` 交互式启动为主，并说明模型可在 Dashboard 系统配置中维护，或手动编辑 `models.json` 后重启。
- MCP Token 自动生成后会写入项目 `.env` 并同步当前进程环境；若环境变量未加载但项目 `.env` 已存在真实 `MCP_TOKEN`，会优先复用该值。
- 全局记忆默认最大限制从 `20000` 字符提升到 `40000` 字符，后端超限判断、内置智能体系统配置页和工作流配置页的计数显示保持一致。
- `skill-tools` 的 `read_file` MCP 描述调整为本地文件读取的首选工具，并新增 `paths` 参数支持一次读取多个文件，减少模型为了读取文件而转用 Python / shell 的倾向。
- 模型配置页不再以内联堆叠表单展示所有模型；模型列表只展示摘要和操作入口且不展示 API Key，具体字段通过弹窗维护，默认/降级/快速模型只能选择 chat 模型，视觉模型只能选择开启“支持视觉”的 chat 模型。
- 知识库上传接口改为先创建 `processing` 文档记录并在后台执行解析、切分和索引，避免上传框阻塞等待 MarkItDown / 向量入库完成；服务层提供可选择的 `index_now=False` 延迟索引路径。
- 工作流列表统计接口支持 `time_range` 参数，`WorkflowService` 统一计算 `24h`、`7d`、`30d` 时间窗口后复用原统计聚合。
- 内置智能体节点模型参数默认保持未设置：`temperature` 与 `top_p` 只有显式保存后才写入 `model_params`，`max_tokens=0` 也不会被传给模型；`False` 和 `0` 等有效显式配置仍会被保留。
- Windows 下内置 shell 工具对显式 `powershell` / `pwsh -Command` 调用改用 UTF-16LE `-EncodedCommand`，并注入 UTF-8 输出编码，降低中文查询和 JSON body 经过 `cmd.exe` 代码页时被破坏的概率。
- 重新构建 Dashboard `dist` 产物，使前端运行包同步上述页面、状态管理、知识库和版本更新。

**Fixed**

- 修复 AgentChat 在智能体运行中切换页面、新建会话或切换会话会中断当前运行的问题；聊天路由现在按 `fullPath` 重新挂载视图，旧会话实例可继续接收流式事件，重新进入对应会话时可挂回运行中快照。
- 修复多个后台运行会话写入 localStorage 时互相覆盖的问题；保存本地会话时按当前会话增量合并，删除会话时使用替换写入，避免已删除会话被旧缓存合并回来。
- 修复内置智能体聊天页仍显示“返回工作流”按钮并可跳转到 `__builtin__` 工作流配置页的问题。
- 修复 Dashboard 时间范围切换后总览卡片、工作流列表和最近 Trace 仍固定显示近 24 小时数据的问题。
- 修复知识库上传失败后前端仍显示就绪、无法看到解析失败原因，以及文档缺少删除入口的问题。
- 修复知识库重新入库、替换和后台入库时失败状态写入逻辑分散且容易漏写可读错误的问题，统一通过 `_index_document_with_failure_status()` / `_mark_document_failed()` 标记 failed。
- 修复 Windows PowerShell 命令中包含中文时，shell 工具通过 `cmd.exe /c` 执行导致请求 body 或输出被 GBK/系统代码页乱码的问题。
- 修复 `MCP_TOKEN` 缺失时只生成临时进程 token，重启后 token 变化且日志只能看到脱敏值的问题。
- 修复通过 `0.0.0.0:端口` 访问 Dashboard 时会话删除后刷新又出现的问题：前端会自动规范到 `127.0.0.1`，同时删除会话只有在后端确认删除成功后才更新本地缓存。
- `agentclaw up` 启动 Server 前会提示模型配置入口：优先在 Dashboard 系统配置中填写模型，也可手动修改 `models.json` 后重启。
- 修复模型配置热更新时覆盖 `LLMManager(default/fallback/fast=...)` 显式构造参数的问题，避免已有工作流的节点/管理器级模型选择被全局默认值改写。
- 修复模型配置页把脱敏后的 API Key `***` 放进密码输入框，导致点击显示时只能看到掩码且容易误保存的问题；编辑弹窗现在留空表示保留已有密钥，填写新值才替换。
- 兼容旧版 `type: "vision"` 模型配置，读取时会按 `type: "chat"` 且 `supports_vision: true` 处理，避免视觉模型语义与 chat 模型分裂。
- 修复 `read_file` MCP 工具参数 schema 使用顶层 `anyOf`，导致部分 OpenAI 兼容模型接口拒绝工具定义的问题；`path` / `paths` 仍由工具实现层校验。
- 修复模型同时传入 `path` 和空 `paths: []` 时，`read_file` 误报 `paths` 必须非空而没有读取单文件路径的问题。
- 修复模型配置保存 payload 省略 `api_key` 时会覆盖删除同 ID 既有模型密钥的问题；后端现在默认保留旧密钥，只有填写新密钥才替换。

**Tests**

- 新增全局记忆边界测试，覆盖 `40000` 字符刚好不超限、`40001` 字符触发超限，以及 Dashboard 相关计数器默认值同步。
- 新增 AgentChat 运行态测试，覆盖页面卸载不取消请求、运行中新建/切换会话只导航不重置、会话缓存合并/删除、重新挂载恢复运行态以及恢复后取消原始请求。
- 新增 Dashboard 时间范围测试，验证 `7d` 等选择会同步传给 summary、workflow list 和 trace list 请求。
- 新增知识库测试，覆盖延迟索引上传返回 processing、文档删除入口、解析失败 inline 展示和后台轮询状态。
- 新增 MCP Token 管理测试，覆盖自动生成写入项目 `.env` 以及环境变量未加载时复用项目 `.env` 中的真实 token。
- 新增会话删除与 Dashboard 访问地址规范化测试，覆盖数据库 `DELETE 0`、前端删除失败不改本地缓存，以及 `0.0.0.0` 自动跳转到 `127.0.0.1`。
- 新增 `read_file` MCP 测试，覆盖工具描述引导和 `paths` 批量读取多个文件。
- 新增 Settings 模型配置测试，覆盖 `models.json` 密钥脱敏、掩码密钥保留、热更新触发、Admin API 契约、Dashboard 弹窗式模型配置入口，以及 LLMManager 热更新保留显式模型覆盖。
- 新增 Settings 服务测试，覆盖内置智能体默认未设置模型参数、显式保存 `False`/`0`、单字段 reset 恢复默认值，以及全局记忆清空。
- 新增 Windows shell 工具编码测试，验证 PowerShell Unicode 脚本会被转为 `-EncodedCommand` 且保留中文内容。

## [1.0.4] - 2026-04-30

**Added**

- Dashboard 与 Public Agent 安全发布体系：工作流公开访问需要显式发布开关和 share token，内置智能体禁止公开分享，匿名 public execution / conversation 接入工作流级限流与预留配额字段。
- 工作流配置新增独立 API Key、公开发布控制、限流配额预留、角色/租户等后续多用户扩展字段，以及 `inject_as_agentic_capability` 开关，用于控制是否把工作流能力注入内置 Agent 提示词。
- Agentic 系统提示词现在注入已注册工作流的名称、描述和输入参数摘要，帮助内置 Agent 直接复用平台能力；`agentclaw_api` 内置 skill 文档同步说明走本机 internal relay。
- 新增 Dashboard 安全/公共访问/知识库模型选择测试，以及 Agentic 能力注入、工作流设置安全、内置 skill API 文档和真实 API 场景测试覆盖。
- `agentclaw init` 与 `agentclaw up` 自动初始化项目时会在项目根目录生成 `docker-compose.yml`，方便用户直接查看、调整或独立运行 Docker 基础设施配置。
- `computer-tools` 新增 Windows 专用 `get_windows_elements` 工具，基于 `pywinauto` 枚举当前桌面窗口和控件树，便于 OS 级鼠标/键盘操作前定位稳定 UI 元素。

**Changed**

- 项目版本从 `1.0.3` 更新为 `1.0.4`，同步 `VERSION`、Python 包元数据、`uv.lock`、管理后台 package 元数据和 README 徽章。
- Dashboard 前端登录态、public route、Workflow Debug SSE、Markdown/文件渲染、知识库模型配置、重排显示和渠道日志体验进一步收敛，避免公网部署与匿名页面出现空白、401 静默失败或误导性分数。
- 内置 skill 描述改为正向高维使用场景描述，减少路由歧义；`agentclaw_api` reference 统一使用 internal relay 路径，避免内部 Agent 为调用平台能力而读取代码或传递密钥。
- 文档同步 Dashboard 公网部署、公开智能体、API Key、内部 relay、签名文件链接、上传限制、工作流能力注入和测试运行说明。
- Docker 本地基础设施端口改为统一通过环境变量配置：`PG_PORT`、`REDIS_PORT`、`MINIO_API_PORT`、`MINIO_CONSOLE_PORT`、`MILVUS_PORT`、`MILVUS_HTTP_PORT`、`ADMINER_PORT`；`agentclaw up -p` / `PORT` 继续只控制 AgentClaw API + Dashboard 服务端口。
- Agentic Harness 工具 schema 新增仅运行时使用的风险判断字段，并明确低/中/高风险标准；运行时按 `max(工具固有风险, 模型判断风险)` 计算最终风险，`shell` / `python` / `javascript` 固有风险至少为 `medium`。
- Python 包新增 `agentclaw[windows]` 可选依赖组，Windows 桌面元素枚举能力通过 `pywinauto` 按平台安装。

**Fixed**

- 修复 Workflow API Key 被当作 Admin Token 使用导致调度器、渠道、文件列表等管理能力越权访问的问题，并拆分 Admin、Workflow、public 与 internal 调用边界。
- 修复 Public Agent 匿名页面与后端认证模型不一致导致新浏览器打开不可用的问题；公开会话强制绑定 share token/source，内置智能体公开状态在 API 与 UI 中统一归零。
- 修复 Bearer 保护后的 `/api/files/{file_id}` 无法作为 Markdown 图片/下载链接直接渲染的问题，改用短期签名文件 URL，并补充旧路径 allowed-root containment 与删除校验。
- 修复启动日志打印完整 Admin Token、LLM 失败完整 dump 默认开启、CSP 阻断 Dashboard 运行、webhook 可创建无 secret、上传先整包读内存、飞书日志单独落文件和重排序模型选择/显示异常等问题。
- 修复 Docker 启动脚本混合 CRLF/LF 行尾导致 Bash 语法检查失败的问题，并让脚本输出实际映射端口。
- 修复知识库上传损坏或伪装 `.docx` / `.pptx` / `.xlsx` 文件时 MarkItDown 抛出 `BadZipFile` 底层异常的问题；上传、替换和重建索引现在会把文档标记为 failed 并保存可读失败原因，Dashboard 文件列表可直接查看错误详情。
- 修复 Windows/GBK 环境下内置 Python 工具打印知识库检索结果中的项目符号、中文或特殊 Unicode 字符时触发 `UnicodeEncodeError` 的问题；Python 子进程现在默认使用 UTF-8 输出编码。
- 修复 Harness 风险确认只依赖工具名/参数、无法叠加模型对具体调用风险判断的问题；模型传入的风险字段会在真实工具执行前剥离，避免污染 MCP/ToolKit 参数。
- 修复内置智能体调用 `screenshot` 截图分析时 `computer-tools` 未接收项目 `models.json`，导致已配置视觉模型仍提示“未配置视觉模型”的问题；截图工具现在也会兼容自动选择第一个 `type: vision` / `model_type: vision` 模型。
- 修复 Dashboard AgentChat 在本地 `conv_*` 会话未同步到服务端或远端会话 404 时可能丢失稳定 `conversation_id` 的问题；工作流执行前现在会从路由恢复或生成本地会话 ID，避免后端每轮生成新的 LangGraph `thread_id` 导致多轮上下文丢失。

## [1.0.3] - 2026-04-28

**Added**

- **`agentclaw up` 启动向导**:
  - 新增手动选择 Docker 本地基础设施或 Remote 远程环境的启动流程，支持新目录自动初始化项目
  - Docker 模式会复用已运行的 PostgreSQL / Redis，仅在基础设施未运行时执行 `docker compose up`
  - Remote 模式支持可选填写外部 PostgreSQL / Redis，全部留空时以内存模式启动
  - 新增可选统一数据目录配置，可将项目代码与日志、上传文件、知识库缓存以及 Docker 基础设施持久化数据分离

- **标准项目 Examples 与 MCP 示例**:
  - `agentclaw/examples` 新增 `mcps/` 示例目录，演示将 `ToolKit` 发布为服务内 MCP 端点并在 `mcp_agent` 中复用
  - `mcp_agent` 同时演示服务内发布 MCP 工具和 `mcp.json` 外部 `fetch` MCP server，节点可直接通过 `tools=[...]` 使用这些工具
  - 示例工作流按 01-11 从简单到复杂重新组织到 `agents/`，并保留可运行的标准项目 `server.py`

**Changed**

- **版本号更新**:
  - 项目版本从 `1.0.2` 更新为 `1.0.3`，同步 `VERSION`、Python 包元数据、管理后台 package 元数据和 README 徽章

- **pip 安装启动体验**:
  - Python wheel 现在明确携带 Admin Dashboard 构建产物和内置 Docker Compose 模板，`pip install agentclaw` 后可直接使用 `agentclaw up` 启动
  - Admin Dashboard 构建检查提前到 FastAPI app 创建前，避免首次生成 `dist` 后静态路由未挂载
  - Docker 模式固定使用 `agentclaw` Compose project name，容器名称不再随源码目录、site-packages 目录或 compose 文件所在目录变化

- **初始化配置边界**:
  - `agentclaw init` 默认生成新版 `models.json` list 格式，并将模型 `api_key` 放回模型配置文件
  - 新增 `agentclaw/env_config.py` 作为统一环境变量配置清单，集中登记用户可见、内部和兼容环境变量
  - `agentclaw init` / `agentclaw up` 生成的 `.env` 只展示建议用户直接配置的 Server、Auth、PG/Redis、Workflow、Upload、Knowledge Base、Scheduler、MCP、Browser 和内置工具配置
  - `MAX_TOOL_ROUNDS` 默认改为 `0`（不限制），并同步系统配置页默认值与 `.env` 说明
  - 管理后台系统配置页改为保存时联动项目 `.env`，页面不再常驻展示 `.env` 变量名，减少配置页噪音
  - 管理后台保存系统配置时同步更新项目 `.env` 与当前进程环境变量，使运行时参数修改立即生效并可持久化
  - 默认 `.env` 不再写入 `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` 等模型密钥占位，模型连接信息继续由 `models.json` 管理
  - CLI 收敛为 `agentclaw init`、`agentclaw up`、`agentclaw serve` 三个入口，移除旧的 `setup`、`run`、`down` 与 `skill` 命令
  - `agentclaw/examples` 重构为标准 AgentClaw 项目结构，示例工作流统一放入 `agents/` 并通过 `server.py` 导入注册
  - 统一对外回调地址配置为 `AGENTCLAW_URL`，兼容旧 `AgentClaw_SERVER_BASE_URL`，避免内置 skill-tools 使用旧默认端口
  - 启动时会自动兼容并迁移旧版 `models` dict 配置，减少旧项目启动警告
  - `AGENTCLAW_DATA_DIR` 可作为统一运行时数据根目录，启动时自动推导本地上传、知识库缓存和日志默认路径
  - 内置 Docker Compose 支持通过 `AGENTCLAW_DOCKER_STORAGE_TYPE=bind` 与派生目录把 PostgreSQL、Redis、etcd、MinIO、Milvus 数据挂载到指定路径；未配置时继续使用 named volumes
  - 知识库 Milvus 默认连接改为平台感知：Docker 模式写入宿主机 `MILVUS_URI`，空 `MILVUS_URI` 在 Linux/macOS 自动使用本地 Milvus Lite，Windows 则提示配置 Docker 或远程 Milvus

- **服务端口统一**:
  - 统一 server 监听配置解析优先级为 CLI 显式参数 > 项目 `.env` 中的 `HOST` / `PORT` > 默认 `0.0.0.0:8000`
  - `agentclaw serve`、`agentclaw up` 与直接运行项目 `server.py` 现在读取同一套监听配置
  - 新项目 `server.py` 模板改为 `AgentClawServer()`，避免模板硬编码 `port=8000` 与 `.env` 冲突

- **文档与启动提示**:
  - README、Quickstart、部署文档和最佳实践同步说明 `agentclaw up` 启动模式、Remote 模式和端口配置策略
  - 启动日志在 PostgreSQL 或 Redis 未配置时明确提示受影响的能力范围

**Fixed**

- **Dashboard 公网部署安全加固**:
  - 拆分 Admin Token 与 Workflow API Key 权限：Scheduler 管理/执行历史、Channel 列表/推送、上传文件列表、文件直链、会话管理、危险操作确认和会话截断现在仅允许 Admin Token；工作流执行、上下文压缩和必要上传接口仍允许 Workflow API Key
  - 将 `/_internal/...` 从公网服务端口移到独立本机 internal relay，公共端口直接拒绝同端口 internal 中转；内部工具通过 relay config 的 `internal_url` 调用，不需要在 shell 或模型上下文传递任何 key
  - internal relay 改为真实本机 HTTP 转发，不再跨线程/跨事件循环通过 `ASGITransport` 直接调用主应用；relay 配置改为项目目录内 `.agentclaw/relay.json`，避免多实例共享 `/tmp` 配置互相覆盖
  - `/api/files/{file_id}` 支持短期签名 URL，模型生成的 Markdown 图片、知识库来源下载和 download-tools 文件链接不再依赖浏览器携带 Bearer header
  - Dashboard `/agent/:id` 重新支持匿名 Public Agent，但必须在工作流配置中显式开启公开发布；公开链接携带工作流级 share token，内置智能体始终禁止分享
  - Public 匿名执行和 public conversation 接入工作流级 `rate_limit` 限流，并预留公开会话/消息配额字段；公开 conversation 强制校验 share token；公共限流默认不信任客户端传入的 `X-Forwarded-*`，需显式设置 `AGENTCLAW_TRUST_PROXY_HEADERS=1` 才会按可信反代头识别来源
  - 内置智能体的公开发布开关在 Settings API、工作流列表/详情和配置页统一归零/禁用，避免旧运行态配置把内置智能体误展示为可分享
  - 工作流配置新增工作流级 API Key，环境变量 `WORKFLOW_API_KEY` 仍作为默认 Key；工作流级 Key 仅允许执行对应工作流，不授予 Scheduler、Channel、文件列表等管理能力
  - LLM 失败请求完整 payload dump 默认关闭，仅在 `AGENTCLAW_DUMP_LLM_FAILURE_PAYLOAD=1` 时写入本地调试文件，并对 key/token/password 等敏感字段脱敏
  - 旧数据中的绝对文件路径增加 allowed-root containment 校验，仅允许上传目录、知识库 storage/cache 目录内路径；越界路径不会被读取或删除；允许目录内的旧文件/知识库文档路径会在访问或重建索引时迁移为相对 storage key
  - 本地与 MinIO 文件存储统一拒绝绝对 storage key 和 `..` 路径穿越，避免对象 key 或本地缓存路径越界
  - 增加全局安全头中间件，默认设置 CSP、`frame-ancestors 'none'`、`Referrer-Policy`、`X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY` 和基础 `Permissions-Policy`
  - Scheduler webhook 保持可对外调用，但启用 webhook 的任务必须配置并携带 `X-Webhook-Secret`，创建/更新和前端表单都会拒绝空 secret
  - Channel webhook 在没有平台签名配置时必须配置并携带 `X-Webhook-Secret`，避免飞书/钉钉/企微/QQ/自定义回调匿名触发工作流
  - 上传入口增加 ASGI 层大小限制，优先在 handler 前检查 `Content-Length`，并继续分块读取文件内容，超过大小限制时立即返回 413，避免有效凭据上传超大文件造成内存压力
  - Admin / Workflow / MCP 自动生成凭据和启动日志统一脱敏输出，避免完整长期凭据进入容器、平台或采集日志
  - Admin 与 MCP 鉴权默认不再接受 URL query token；Dashboard 调试流改用 `fetch` 携带 `Authorization` header 读取 SSE，MCP query token 仅可通过兼容环境变量显式启用
  - Public conversations 拆分为独立 public-only router，强制使用 `source=public` 并预留 `owner_id`、`user_id`、`tenant_id` 字段，避免公网请求读取或修改 Dashboard 管理会话
  - Dashboard Markdown 消息和知识库搜索预览统一通过 DOMPurify 净化后再进入 `v-html`，修复模型输出、会话摘要和检索内容导致的 XSS 风险
  - Scheduler 与 public conversation 前端调用改为在访问 `/api` 时自动携带 Admin Token，并避免启动日志重复打印完整 Workflow API Key / MCP Token
  - 系统设置 API 不再向前端返回 `ADMIN_TOKEN`、`WORKFLOW_API_KEY`、数据库/Redis/MinIO 密钥的明文 `raw_value`，设置持久化文件改为 `0600` 权限并默认忽略 `.agentclaw/` 运行态目录
  - 文件下载响应统一生成 RFC 5987 `Content-Disposition`，清理 CR/LF 注入片段，并对 `text/html`、`image/svg+xml` 等主动内容强制 attachment + `X-Content-Type-Options: nosniff`
  - 增加全局请求体大小限制，覆盖 workflow、scheduler、channel、MCP、debug/settings 等 JSON/body 端点；上传与知识库导入继续使用独立较大限制，并在 `.env` / 设置页暴露 `AGENTCLAW_MAX_REQUEST_BODY_BYTES`
  - Admin API fallback 路由在主 Admin router 加载失败时也会先挂载 Admin Token 认证，避免简化版 prompts/workflows 管理接口匿名暴露
  - download-tools / skill-tools 生成临时下载链接前会检查文件大小并限制 TTL，避免大文件整包读入内存并写入 Redis，并在 `.env` / 设置页暴露下载大小与 TTL 限制
  - Scheduler 手动触发和 webhook 触发现在返回真实 `JobExecution.id`，触发时先创建 pending 执行记录，便于调用方立即按 execution id 查询状态
  - Dashboard Workflow Debug 流式连接遇到 401 会清理本地 Admin Token 并触发登录弹窗，其他 SSE 连接失败也会写入调试历史和输出面板

- **Windows 启动与退出稳定性**:
  - 修复 PostgreSQL / Redis 不可达时启动阶段可能长时间停留在 `Waiting for application startup` 的问题，连接失败会快速降级并继续启动
  - Docker 启动模式不再覆盖当前进程已有 PG/Redis 环境变量；若已有环境变量与 Docker 默认值不同，会给出显式提示
  - `agentclaw up` 生成新项目时会复用已有环境变量或 `.env` 中的 Auth Token，不再重复询问并覆盖已有 Token
  - Docker 启动模式会额外验证宿主机 PostgreSQL / Redis 端口可连接，避免容器 running 但 `server.py` 仍连不上 Redis
  - Docker Redis 可用性检测从 TCP 握手升级为 Redis 协议 `PING/PONG`，避免 Windows 端口映射异常时误判为可用
  - 内置 Docker Compose 支持通过项目 `.env` 的 `PG_PORT` / `REDIS_PORT` 改宿主机映射端口，可绕开本机异常或占用的 6379
  - Docker 启动模式会写入并检查 Milvus 宿主机端口，新增 `MILVUS_PORT` / `MILVUS_HTTP_PORT` 端口映射配置，避免 Agent 仍连接空 Milvus URI 或容器内服务名
  - Redis 连接不可达时改为 warning，并明确提示 Redis 相关能力降级，避免将可选能力降级误判为服务启动失败
  - Redis 默认启动连接超时从 3 秒调整为 10 秒，降低 Windows / Docker Desktop 启动后端口映射较慢时的误降级概率
  - 修复 Windows 同步 PostgreSQL checkpointer 分支清理残留 checkpoint 时误用 `async with` 导致的 warning
  - 修复 `agentclaw up` / `agentclaw serve` 收到 Ctrl+C 后可能被 Channel、Scheduler、ResourceManager 或数据库连接关闭流程卡住的问题
  - 启动完成后新增 `AgentClaw 服务启动完成` 日志，便于区分“仍在 startup 阶段”和“服务已可访问”
  - 未配置项目 `skills/` 目录时不再误报 `加载 Skills 失败: 'NoneType' object has no attribute 'refresh'`

- **系统配置页显示**:
  - 修复运行时参数响应缺字段时 `最大上下文消息数` 可能显示为空的问题
  - 运行时参数输入框与说明文案改为可换行布局，避免长提示在窄屏或缩放场景下挤压输入框
  - 移除运行时参数和基础设施编辑弹窗中的 `.env: XXX` 常驻页面提示
  - Dashboard 静态资源响应增加 no-cache 头，降低浏览器继续使用旧前端 chunk 的概率
  - 修复 Windows 启动后首个空会话默认折叠执行过程，导致首个问题看不到节点、工具和 Harness 后处理信息的问题
  - 修复页面初始化/会话加载尚未完成时首条消息可发送，随后迟到的 `loadConversation` 覆盖流式运行态，导致首次工具调用和智能体执行过程被吞掉的问题
  - 前端 SSE 读取会在流结束时 flush `TextDecoder` 并处理剩余 buffer，同时记录 JSON 解析失败日志，避免最后一条 UTF-8 执行事件被静默丢弃

- **Examples 运行与路由稳定性**:
  - 修复 `Workflow.add_llm_router()` 内部 JSON 示例未转义导致 prompt 变量替换 warning 的问题
  - 修复 `human_approval` 示例对 `workflow.resume()` 返回值结构的错误假设，保证人工审核示例可直接运行
  - 修正 examples MCP 目录命名为 `mcps/`，避免项目目录与第三方 `mcp` Python 包名称冲突

- **占位密钥误加载**:
  - 启动加载 `.env` 前会自动注释旧项目中仍处于生效状态的占位密钥，避免 `sk-your-api-key` 被当成真实模型密钥
  - 模型管理器会识别常见 `api_key` 占位值并视为未配置，缺少模型密钥时给出指向 `models.json` 的清晰错误
  - 保留 `models.json` 中 `${OPENAI_API_KEY}` 这类显式环境变量引用能力，但不再隐式从 `.env` 兜底读取模型密钥

- **文档读取稳定性**:
  - `read_file` 读取 PDF/DOCX/PPTX/XLSX 等文档时改为在独立子进程中调用 MarkItDown，并新增 `SKILL_TOOLS_DOCUMENT_READ_TIMEOUT` 超时保护，避免异常文档转换卡死 MCP server
  - 修复 Windows 下 `read_file` 解析 PDF 等文档时因事件循环不支持 asyncio 子进程导致快速失败并输出空白错误的问题
  - 修复 MarkItDown 已完成转换但包装子进程被后台线程拖住不退出，导致 Windows 下 DOCX/PDF 读取等到 `SKILL_TOOLS_DOCUMENT_READ_TIMEOUT` 才失败的问题
  - MarkItDown 包装子进程强制使用 UTF-8 stdout/stderr，避免 Windows GBK 代码页遇到 `•` 等字符时 `UnicodeEncodeError` 导致 DOCX 读取失败
  - 内置工具子进程统一断开继承的 MCP stdio 输入，避免子命令意外读取工具通信管道或等待交互输入

- **截图工具参数容错**:
  - `screenshot` 工具补充 region 默认参数说明，并将 `width` / `height` 缺失、为 0 或负数的 region 视为全屏截图，避免 Windows 下创建 `Bitmap(0, 0)` 报错
  - `screenshot` 新增可选 `prompt` 参数；只有在需要读取截图内容时才触发视觉模型分析，未填写时仍只保存截图并返回文件路径

- **内置工具输出解码**:
  - 修复 Windows 下 `shell` / `python` / `javascript` 工具读取中文路径或本地代码页输出时按 UTF-8 解码导致失败的问题
  - `python` / `javascript` 工具新增 `timeout` 参数，并在超时时终止子进程树，避免脚本内部执行 `pip` 或其他子进程时工具长期卡住

- **Harness 工具续跑稳定性**:
  - 修复部分 OpenAI-compatible 模型在强制继续调用工具时将 `<minimax:tool_call>` 作为普通文本输出，导致反馈后没有真正执行下一步工具的问题
  - 后处理要求继续调用工具时，如果模型连续返回纯文本而没有真实工具调用，Harness 会有限次数强制重试并在超过上限后释放流程，避免前端无响应卡住
  - `harness_post_tool` 后处理控制模型调用新增硬超时 `HARNESS_POST_TOOL_TIMEOUT`，默认值调整为 60 秒，避免模型网关无响应时卡在工具后处理阶段
  - 后处理模型输出空响应、非法 JSON、异常或超时时会触发最多 3 次重试，并通过前端执行过程显示重试原因
  - LLM 请求创建阶段增加 `asyncio.wait_for` 硬超时兜底，避免 OpenAI-compatible 网关不触发客户端 timeout 时长期悬挂
  - MCP 工具调用新增 `AGENTCLAW_MCP_TOOL_TIMEOUT` 硬超时，避免远程或异常 MCP Server 长期不返回导致 agent 卡住

## [1.0.2] - 2026-04-26

**Added**

- **Agent Creator 演示视频**:
  - README 中新增 `assets/agent_creator.mp4` 产品预览，展示从自然语言创建系统日志审计智能体、配置定时任务、执行并生成 Markdown 报告的完整流程
  - 中英文 README 均保留直接打开视频的兜底链接，兼容不支持内嵌 `<video>` 的 Markdown 渲染器

- **Agent Creator 数据/SQL 构建参考**:
  - 新增 `agent_creator/references/nl2sql.md`，覆盖 NL2SQL、数据库问答、分析报表、日志审计和定时数据报告的构建模式
  - 补充工具型 agentic SQL 助手与流程型 SQL 工作流两种设计，并强调读取表结构、SQL 校验、最多一次修复、再执行的可靠路径
  - 新增 skill/reference 读取诊断，帮助发现数据库/报表类任务在写代码前未读取关键模式参考的情况

**Changed**

- **版本号更新**:
  - 项目版本从 `1.0.1` 更新为 `1.0.2`，同步 `VERSION`、Python 包元数据、管理后台 package 元数据、`uv.lock` 和 README 徽章

- **Agent Creator 构建思想**:
  - 强化“先模式、后实现”的构建协议，引导模型把命中的 skill 作为默认架构骨架，而不是仅作为背景资料
  - 补充证据流、验证门、确定性节点与 LLM 节点职责分工，鼓励报告、总结、风险解释和建议等语义内容由 `LLMNode` 生成
  - 将旧的分散 reference 内容收敛为更聚焦的主 playbook 与 NL2SQL/数据报告参考，减少模板噪音

- **工具与前端体验**:
  - `replace_in_file` 在替换成功后自动追加语法检查反馈，帮助模型第一时间发现本次替换引入的语法问题
  - 仪表盘和日志页的耗时条在存在巨大离群值时使用对数比例，避免其他记录的耗时条被压缩到几乎不可见
  - Harness 工具后处理反馈放宽为不超过 160 字的一句话进度说明，便于展示“刚完成什么、接下来做什么”

**Fixed**

- **LLMNode 非流式输出丢失**:
  - 修复非流式、无工具调用场景下普通字符串响应未进入 `postprocess_model_output()` 文本通道的问题
  - 解决 `LLMNode(output_key=...)` 接收不到模型正文，进而导致报告节点写入“报告生成失败：未获得报告正文。”兜底内容的问题

### 2026-04-25

**Changed**

- **版本号更新**:
  - 项目版本从 `1.0.0` 更新为 `1.0.1`，同步 `VERSION`、Python 包元数据、管理后台 package 元数据和 README 徽章

- **Agentic Harness 与模型调用**:
  - 后处理反馈改为基于原始用户请求、最近上下文和本轮工具结果生成一句用户友好的进度说明，并写回后续上下文
  - agentic 模式不再应用最大上下文消息数截断，普通模式截断后会修复 OpenAI tool-call 消息序列，避免孤立工具结果触发请求错误
  - 模型调用重试和失败会通过流式事件反馈到前端，避免前端在 504 等异常场景下无提示卡住

- **管理后台体验**:
  - 对话消息区域滚动条增强为稳定可见的轨道和滑块，方便用户判断当前阅读位置
  - “最大上下文消息数”默认改为 `0`（不限制），并在设置说明中标注该配置不影响 agentic 模式

- **运行日志与工具说明**:
  - 启动日志显示实际按日期落盘的日志文件路径，并记录外部 MCP 与内置 skill/tool 加载摘要
  - `agentclaw_api` 技能说明补充定时任务创建能力，帮助模型在需要自动调度时选择正确 API

### 2026-04-25

**Added**

- **Agent Runtime Harness**:
  - 新增 agentic 模式 Harness 运行层，封装模型输出解析、工具调用参数校验、工具结果信封、后处理决策和最终回复生成
  - 后处理模型调用采用短字段控制流程，仅用于状态推进与简短用户反馈，并避免将控制 JSON 展示给用户
  - 工具执行环境快照新增当前 Python 可执行文件与推荐 pip 安装命令，减少模型误用错误虚拟环境

- **模型权限与工具确认**:
  - 聊天页右侧下方新增“模型权限 / 自动执行权限”配置，支持按 `off/high/medium/low` 调整工具确认阈值
  - 工作流运行 API 新增 `tool_confirmation_level`，并继续兼容旧的 `tool_confirmation_required` 字段
  - Harness 工具执行器支持按工具风险级别触发用户确认

**Changed**

- **请求级模型切换**:
  - 右上角模型选择改为请求级模型覆盖，仅影响未显式指定 `model_id` 的 LLM 节点
  - 内置 `__builtin__` 智能体不再把全局当前模型写入节点 `model_id`，避免切换模型后仍沿用旧模型
  - LangGraph 恢复中断时同步本次请求级模型和工具确认配置，避免 checkpoint 中旧状态污染本次请求

- **agent_creator 指南**:
  - 补充 `agent_style="agentic"` 工作流建议将执行超时设置为 `240` 秒

**Fixed**

- **聊天运行状态**:
  - 切换/新建会话时重置运行期 token 计数与流式状态，避免不同会话上下文长度串用
  - 后处理用户反馈改为同语言、短反馈策略，避免英文反馈或过长内容阻塞前端

- **MCP 初始化**:
  - MCP Server 连接超时后保留后台初始化任务，避免用户过早发起对话导致慢启动工具被取消

- **定时任务页面**:
  - 修复定时任务列表操作按钮点击事件冒泡导致误进入任务详情的问题

### 2026-04-24

**Added**

- **Admin Dashboard 国际化基础设施**:
  - 接入 `vue-i18n`，新增中文/英文语言包、语言切换组件和语言偏好本地持久化
  - Naive UI 组件 locale / date-locale 改为跟随当前界面语言，不再固定中文
  - 管理后台主要页面、通用组件、聊天组件、调度器、知识库、渠道、执行追踪、工作流配置等文案切换为 i18n key
  - 新增 i18n 审计/批量替换脚本，以及 locale、格式化函数和内置工作流翻译相关前端测试

- **运行路径上下文解析**:
  - 新增 `RuntimePathContext`，统一解析项目目录、skills 目录、模型配置、MCP 配置、环境文件和工作流 memory 路径
  - LLM 节点和管理端工具配置接口复用统一路径解析，避免从 `skills_dir.parent` 反推项目目录导致多项目/嵌套项目跑偏

- **手动上下文压缩与长期记忆沉淀**:
  - 管理后台聊天页支持点击上下文用量框手动触发上下文压缩，并使用统一确认弹窗二次确认
  - 压缩过程中在对话区展示“正在压缩上下文”状态，完成后自动显示展开的上下文摘要并刷新上下文长度
  - 压缩 API 返回压缩后的上下文 token 数、memory 写入状态与 memory 路径

- **日志按日期落盘**:
  - 新增按天切换的文件日志处理器，日志文件自动写入带日期后缀的文件并在跨天时切换

- **统一版本号来源**:
  - 新增仓库根目录 `VERSION` 文件作为项目版本单一来源，当前版本为 `1.0.0`
  - Python 包、OpenAPI、健康检查、MCP serverInfo、内置工作流和管理后台侧栏统一读取该版本号
  - 同步 README 徽章、API 文档、Python/前端包元数据与锁文件版本

**Changed**

- **内置 AgentClaw 智能体行为**:
  - 内置智能体系统提示词调整为更主动的执行型助手，鼓励使用技能、工具、文件、API、知识库和运行环境推进任务
  - 工具/技能预过滤提示改为更包容，研究型、开放式、创意型或需要参考信息的任务会优先保留可帮助探索的工具与技能
  - 内置 `agent_creator` 技能描述扩展到工作流检查、更新、调试、验证、提示词/人格/路由/工具配置迭代等场景

- **Agentic 技能提示与规划协议**:
  - LLM 节点注入的技能使用协议从强制首步读取改为面向执行的相关性读取，减少机械步骤并保留必要约束
  - 内置提示词中的规划说明改为更短的执行导向版本，聚焦技能读取、上下文收集、工具调用和验证

- **上下文压缩写入 memory.md 策略**:
  - 压缩后仅由模型提取通用、稳定、跨会话可复用的长期记忆，明确排除未完成任务、当前会话计划和临时搜索结果
  - 移除基于关键词黑名单的硬编码 memory 过滤逻辑，代码侧仅归一化模型输出格式

- **工作流记忆更新语义**:
  - `update_memory` 默认只替换首个正则匹配，避免重复标题或多处匹配时误批量覆盖
  - 新增 `replace_all` 参数用于显式替换所有匹配，并在返回结果中暴露总匹配数与替换模式

**Fixed**

- **流式 token 用量覆盖问题**:
  - `message_end` 不再用末次 usage 覆盖已累计 token，避免多段流式输出或工具链路结束时统计被重置

- **项目级路径注入偏移**:
  - 内置 `skill-tools` 与 `coding-tools` 使用统一项目根目录作为工作目录，避免内置工具在嵌套 skills 目录下读写到错误位置

**Removed**

- **旧版 Claude 说明文件**:
  - 移除仓库根目录过时的 `CLAUDE.md` 与 `CLAUDE_REFERENCE.md`，避免与当前项目说明重复或冲突

### 2026-04-22

**Changed**

- **README 产品叙事重构**:
  - `README_CN.md` 重新整理为面向个人开发者与团队的产品型首页，突出“声明式 Agent 工作流框架 + Claw 智能体底座”的双重定位
  - 新增产品预览占位、核心价值、能力矩阵、从想法到上线、对比表格与商业支持等结构，弱化对 Skills 的单点叙事
  - `README.md` 英文版同步为同一套结构与表达，方便中英文用户获得一致的一线认知

**Added**

- **Admin Dashboard 中英切换设计文档**:
  - 补充管理后台 i18n 设计说明，规划 `vue-i18n`、Naive UI locale、格式化函数与语言偏好持久化方案
  - 新增分任务实施计划，覆盖测试基建、共享布局、主要视图翻译与剩余页面收尾步骤，便于后续按阶段落地

### 2026-04-21

**Added**

- **工作流级全局记忆**:
  - 新增本地 `memory.md` 存储，按工作流写入 `.agentclaw/workflows/<workflow_id>/memory.md`
  - LLM 节点新增 `enable_memory` 开关，开启后会在执行时动态注入当前工作流记忆
  - `skill-tools` 新增 `update_memory` 与 `compress_memory` 工具，支持正则更新与压缩整理工作流记忆
  - 智能体配置页新增全局记忆编辑入口，并显示当前字符数与超限提示

- **渠道主动推送消息**:
  - 打通 `POST /api/channels/push`，支持从 AgentClaw 后端主动向飞书、钉钉、QQ、企业微信渠道推送文本消息
  - `agentclaw_api` 的渠道文档补充主动推送接口、参数约束和各渠道目标 ID 说明

**Changed**

- **内置工作流默认启用记忆**:
  - 内置 `__builtin__` 智能体默认开启 `enable_memory`
  - `agentclaw init` 生成的默认 `hello_world` 工作流模板也默认开启全局记忆

- **知识库检索默认值与智能体卡片统计**:
  - 知识库默认相似度阈值统一调整为 `0.3`
  - 创建/编辑知识库与测试检索时都支持显式关闭 rerank，测试面板额外支持“跟随知识库配置 / 关闭重排序 / 指定模型”
  - 智能体列表卡片和表格统计统一改为展示近 24 小时数据，成功率在无执行记录时显示为 `-`

**Fixed**

- **文件更新工具并发覆盖风险**:
  - 新增统一文件写入锁，优先使用 Redis，未配置或不可用时自动退回进程内内存锁
  - `write_file`、`write_code`、`update_memory`、`compress_memory`、`update_code`、`replace_in_file` 统一接入共享锁，避免并发写入同一路径时互相覆盖
  - 修复文件锁在隔离事件循环测试场景下复用已关闭 loop 资源的问题

- **初始化环境模板对齐**:
  - `.env.example` 补齐 `ADMIN_TOKEN`、`WORKFLOW_API_KEY`、`MCP_TOKEN` 的注释占位，和 `agentclaw init` 生成 `.env` 的替换逻辑保持一致

- **远程 MCP 连接稳定性与代理支持**:
  - 新增 `AGENTCLAW_MCP_PROXY` 环境变量，仅作用于远程 MCP 连接，自动跳过 `localhost/127.0.0.1`
  - 当 `mcp.json` 中 URL 类型的 server 未显式指定 transport 时，先尝试 `sse`，失败后自动回退到 `streamable_http`
  - MCP 连接支持统一超时控制，单个 server 超时后会被跳过，不再卡住整个工作流启动或执行
  - 未配置任何外部 MCP Server 时改为信息日志，不再输出误导性的失败警告

- **启动期噪音与兼容性回归**:
  - psycopg async 连接池统一改为显式 `open=False` 后再 `await open()`，消除启动期弃用警告
  - 调度器启动时会自动禁用已过期的一次性任务，避免 APScheduler `misfire` 噪音
  - Milvus gRPC keepalive 调整为更保守配置，降低 `too_many_pings` 告警概率

- **渠道推送错误处理与返回语义**:
  - `ChannelManager.push_message()` 改为返回结构化结果，不再只用布尔值吞掉失败原因
  - `POST /api/channels/push` 现在会根据错误类型返回 `400/404/500`
  - 飞书、钉钉、QQ、企业微信推送失败时统一抛出明确异常，便于接口层和日志准确定位问题

### 2026-04-18

**Added**

- **统一配置覆盖能力**:
  - 新增 `/admin/settings` 管理接口，支持系统默认参数、基础设施配置、工作流配置和节点配置的读取与覆盖
  - 用户自定义配置持久化到项目目录 `.agentclaw/` 下的本地 JSON 文件
  - 覆盖规则改为“仅保存用户显式填写的项”，留空字段继续继承工作流或系统默认值

- **独立智能体配置页**:
  - 新增智能体配置入口，将工作流配置、节点配置和提示词配置统一收敛到智能体维度
  - 节点配置新增独立提示词面板，并按 `基础定义 / 记忆与工具 / 高级容错设置 / 大模型引擎` 重新排版

**Fixed**

- **Windows 主机环境兼容性**:
  - 统一在 CLI、API Server、数据库与 Checkpointer 初始化阶段应用 `WindowsSelectorEventLoopPolicy`，修复 psycopg async 与 ProactorEventLoop 不兼容问题
  - 当服务运行在宿主机而 PostgreSQL / Redis 运行在 docker-compose 容器中时，自动将 `postgres` / `redis` 主机名回退到 `127.0.0.1`
  - 工具运行时环境改为按当前平台生成，避免内置工具和提示词将 Windows 误判为 Linux 沙盒

- **对话模型选择混入 embedding / rerank**:
  - 工作流详情、智能体配置页、系统默认节点配置统一过滤非对话模型
  - 知识库专用的 embedding / rerank 模型选择保持原有行为，不受影响

**Changed**

- **智能体反馈统计可见化**:
  - 基于 `message_feedback` 按工作流聚合点赞 / 点踩数量
  - 智能体列表、仪表盘概览表和智能体详情页新增反馈展示

- **系统配置认证信息展示**:
  - 系统配置页的 `Admin Token` 与 `Workflow API Key` 不再隐藏为 `***`
  - 认证信息仍然保持只读，继续通过环境变量管理

### 2026-04-16

**Fixed**

- **执行追踪时间筛选与统计异常**: 统一筛选时间的时区归一化逻辑，修复 `offset-naive` / `offset-aware` datetime 混用导致的日志为空和统计失败问题
  - 执行追踪列表与统计现在使用同一套时间范围处理
  - 渠道日志补齐时间筛选，筛选后列表与统计同步更新
  - 渠道统计查询修复 `GROUP BY` 与聚合不一致导致的 500 错误

- **Token 消耗统计不一致**: 统一执行追踪、工作流列表、仪表盘和渠道日志的 token 聚合查询，避免同一指标在不同页面各自取数
  - 工作流与执行追踪补充输入/输出 token 拆分
  - Token 显示支持 `K / M / B` 动态单位
  - 智能体卡片、工作流列表和执行追踪复用同一套 token 汇总来源，修复卡片 token 长期显示为 0 的问题

- **内置智能体关闭智能筛选后仍执行筛选节点**: 调整内置工作流 DAG，关闭智能筛选时直接跳过技能/工具筛选节点
  - 关闭后不再出现 `正在筛选相关技能...` / `正在筛选相关工具...`
  - 开启时合并为单个 `正在智能筛选...` 步骤

- **渠道启动卡住与日志刷屏**:
  - 飞书 worker 连接阶段改为异步等待，避免启动过程因握手超时长期阻塞
  - 运行期日志改为以项目目录 `logs/` 为主输出，并压缩过长的 trace / LLM / streaming 日志内容
  - 控制台保留最小必要的启动提示，便于确认服务是否已成功启动

- **执行输出追踪缺失**: 工作流日志补充 `output_data` 持久化，执行追踪与详情页可直接查看用户可见输出内容
  - 渠道消息日志补充 `trace_id` 关联，便于从渠道日志跳转到对应执行追踪

**Changed**

- **管理后台导航与信息架构优化**:
  - `工作流` 入口重命名并承担智能体主入口，原独立 `智能体` 入口移除
  - `提示词管理` 合并进工作流详情
  - `执行追踪` 合并到仪表盘
  - `渠道日志` 合并到渠道配置

- **仪表盘与智能体卡片重构**:
  - 智能体卡片改为更简洁的信息布局，点击卡片直接进入体验，点击详情进入详情页
  - 卡片移除节点数、空闲标签和冗余体验按钮，改为展示 token 消耗
  - 仪表盘支持筛选是否包含内置智能体，并调整卡片排序
  - 仪表盘执行追踪统计项移除“运行中”，改为展示 token 消耗

- **筛选交互优化**:
  - 删除独立筛选按钮，选择条件后自动筛选
  - 开始时间与结束时间并排展示，提升时间范围筛选效率
  - 渠道日志中的超时指标替换为 token 消耗，与执行追踪保持一致
  - 工作流、执行追踪与渠道日志的筛选项和统计口径进一步对齐

### 2026-04-13

**Fixed**

- **Token 统计改为 tiktoken 实际计数**: `push_message_end` 不再使用 LLM API 返回的累加 usage（多轮调用会膨胀），改为用 tiktoken 直接统计 `__messages__` 中的 token 数
  - `prompt_tokens` = 非 assistant 消息（用户输入 + 工具结果）
  - `completion_tokens` = assistant 消息
  - `total_tokens` = 全部对话记录（不含 system prompt）

- **知识库文档上传后索引失败（文件系统不同步）**: `FileStorage.save_with_prefix()` 的 hash 去重逻辑在数据库找到匹配记录后直接返回，未验证文件是否仍在磁盘上
  - 现在 `find_by_hash` 命中后增加 `backend.exists()` 验证，文件丢失时清理脏记录并重新写入
  - 新增 `_delete_from_db()` 方法

- **工具结果截断导致文档读取不完整**: `TOOL_RESULT_MAX_LENGTH` 默认值从 4000 调整为 20000
  - 截断改为行边界对齐，附带位置标注（`line X/Y, chars shown/total`），提示使用 `line_start` 继续读取

- **重复工具调用强制退出策略移除**: 移除 `_REPEAT_THRESHOLD` 和 `_consecutive_repeats` 强制退出逻辑，仅注入警告，由模型自行决定

- **模型空响应处理**: LLM 返回空响应（0 token）时自动重试当前轮次

- **工具调用失败时附带原始参数**: 工具失败结果中追加 `[Your call arguments: ...]`，帮助模型理解失败原因

- **残留挂起状态清理**: 取消/超时导致的非正常挂起，下次对话时自动检测并清理 checkpoint，保留对话上下文

**Changed**

- **流式输出改为实时推送**: 工具调用轮次中 `push_to_context` 改为 `self.output_to_user`，中间轮文本在产出时实时推送到 SSE，无需结束后回放

- **读文件工具自动添加行号**: `read_file` 和 `read_skill_file` 输出带行号（`N| content`）
  - `read_file` 新增 `line_start` 参数，截断后可从指定行继续读取

- **执行追踪 `__messages__` 优化**: 不再存储完整消息列表
  - 输入侧：改为摘要（总数 + 最近 6 条，内容截断至 200 字符）
  - 输出侧：仅记录本节点新增的消息

- **上下文截断诊断日志**: `_build_messages` 在裁剪历史消息时记录 `总历史/max_context_messages/丢弃条数`

- **Skill 提示词正向化**: agent_creator SKILL.md 和 principle.md 中所有负面警告转为正向引导

- **`agentclaw_api` skill 默认注入**: `metadata.always_inject=true`，不受 `skills_filter_key` 过滤

- **Skill 阅读协议优化**: 技能头部提示从 `MANDATORY FIRST STEP` 改为 `Skill Reading Protocol`，引导模型按需读取 SKILL.md 及其引用文档

- **前端 Drawer 拖拽调整宽度**: 多个页面的 n-drawer 支持拖拽调整宽度
  - 新增 `useResizableDrawer.js` composable

### 2026-04-09

**Fixed**

- **内置 Agent 超时问题**: `workflow.timeout=0` 时仍按 300s 超时
  - `_wrap_node_for_langgraph()` 未将 `Workflow.timeout` 传递给 `WorkflowContext`，导致默认 300s 生效
  - `_execute_builtin()` 同步修复，`timeout=0` 统一视为无超时

- **对话界面工具详情面板滚动体验**: 工具调用详情面板始终渲染在步骤列表底部，查看需大量滚动
  - `ChatMessage.vue` / `StreamingMessage.vue`: 将 `ToolDetailsPanel` 从底部移至对应工具组内联显示

- **追踪详情抽屉宽度与工具调用可读性**:
  - 抽屉宽度从 500px 调整为 720px
  - 工具调用改为卡片式布局，左侧彩色边框区分状态（蓝=调用、绿=成功、红=失败）
  - 调用参数与返回结果分区显示，背景色区分

**Changed**

- **移除 workflow-tools MCP**: 删除 `workflow_tools.py`、`workflow_skill` 内置 skill 及相关注册/合并逻辑
  - `LLMNode` 不再初始化 workflow-tools MCP manager
  - `_resolve_prompt()` 不再接收 `workflow_mcp_manager` 参数

- **skill-tools `read_skill_file` 支持 `{BASE_URL}` 运行时替换**: 读取 skill 文件时自动注入服务端地址

- **agent_creator skill 全面优化**:
  - 新增 §2.2 ToolKit 使用模式：`ToolKit()` + `@toolkit.tool` + `register_toolkit()` 完整示例，延迟导入、环境变量配置
  - 新增 §2.6 包安装指南：通过 shell 工具安装（venv 感知），避免 PEP 668 问题
  - 构建循环增加预注册验证门控（步骤 6）：注册前必须通过 import 验证
  - 注册流程修正：API 热注册为主，`server.py` 导入改为注册成功后添加
  - `principle.md` 新增 §18 ToolKit 运行时模式、§19 预注册验证流程
  - 全部负面提示改为正向引导

- **内置 skill `agentclaw_api` 默认注入**: 设置 `metadata.always_inject=true`，启用内置 skill 后不受 `skills_filter_key` 过滤

- **前端全面迁移 Naive UI**: 移除自定义 CSS 变量和手写组件（StatCard、StatusBadge、ConfirmDialog、Toast），统一使用 Naive UI 组件库
  - 删除 `src/styles/main.css`、原型 HTML 文件、测试脚本等冗余文件

### 2026-04-07

**Added**

#### 统一文件存储

- **存储后端抽象层**: `agentclaw/database/storage_backend.py`
  - `StorageBackend` 协议：统一 `save / get / delete / exists / get_local_path` 接口
  - `LocalStorageBackend`: 本地文件系统存储
  - `MinIOStorageBackend`: MinIO 对象存储，支持 `download_to_local()` 供 parser 等需要磁盘路径的组件使用
  - `create_storage_backend()` 工厂函数，根据配置自动选择后端

- **MinIO 配置**: `agentclaw/config.py`
  - `UploadConfig` 新增 `minio_endpoint / minio_access_key / minio_secret_key / minio_bucket / minio_secure` 字段
  - `use_minio` 属性：当三项必填字段非空时自动启用 MinIO
  - 默认存储目录从 `.uploads` 改为 `.storage`

- **统一文件存储服务重构**: `agentclaw/database/file_storage.py`
  - 所有文件（通用上传 + 知识库文档）统一通过 `FileStorage` 管理
  - 文件以 storage key（如 `uploads/{hash}.png`、`knowledgebase/{kb_id}/{hash}.pdf`）存储
  - 元数据记录到 PostgreSQL `files` 表，支持按 ID / hash 查询和去重
  - 兼容旧数据的绝对路径格式

- **公开文件下载 API**: `agentclaw/api/routers/public/files.py`
  - `GET /api/files/{file_id}` — 按文件 ID 下载/预览
  - 图片和 PDF 默认内联显示，其余格式作为附件下载
  - 支持 `?download=true` 强制下载

- **download-tools MCP 新增 `get_file_url` 工具**: `agentclaw/mcp/builtin_servers/download_tools.py`
  - 根据文件 ID 生成永久下载 URL `/api/files/{file_id}`
  - 与 `create_download_url`（临时 Redis 链接）互补

#### KnowledgeBaseNode 知识库检索节点

- **新增 `KnowledgeBaseNode`**: `agentclaw/node/knowledgebase.py`
  - 根据输入查询从知识库检索相关内容分块，支持溯源
  - 参数：`knowledgebase_id / top_k / mode / score_threshold / rerank_model_id / content_template`
  - 输出：`chunks`（带分数、来源文档、下载 URL）+ `sources`（去重文档列表）+ `formatted_text`（可选模板格式化）
  - `download_url` 优先使用统一路径 `/api/files/{file_id}`，旧数据回退到 admin 路径
  - 在 `node/__init__.py` 和 `agentclaw/__init__.py` 导出

- **示例工作流**: `agentclaw/examples/ex11_knowledge.py`
  - 两节点 RAG 工作流示例：KnowledgeBaseNode → LLMNode

**Changed**

#### 知识库

- **知识库存储委托给统一 FileStorage**: `agentclaw/knowledgebase/storage.py`
  - `save_document()` 优先通过 `FileStorage.save_with_prefix()` 保存，记录 `file_id`
  - `delete_document_assets()` 使用统一后端删除，兼容旧数据直接删磁盘
- **文档索引路径解析**: `agentclaw/knowledgebase/service.py`
  - `_index_document()` 通过 `FileStorage.get_local_path_by_key()` 解析 storage key 为本地路径
  - 兼容旧数据的绝对路径直接传给 parser
- **admin 文档下载端点**: `agentclaw/api/routers/admin/knowledgebases.py`
  - 优先通过统一 `FileStorage._read_file()` 读取，旧数据回退到 `FileResponse`

**Fixed**

- **知识库分数阈值过滤使用错误字段**: `agentclaw/knowledgebase/service.py`
  - `_apply_score_threshold` 之前用 `dense_score` 与阈值比较，改为使用最终加权后的 `score`
- **知识库检索 RRF 分数不匹配**: 替换为加权合并策略
- **中文关键词搜索失效**: 增加 2-gram ILIKE 兜底
- **Rerank 覆写分数**: 改为仅重排序，不覆盖原始分数

### 2026-03-27

**Added**

#### WeCom Bot Worker

- **企业微信智能体机器人 API 模式接入**: 新增 Node Worker 适配官方 `@wecom/aibot-node-sdk`
  - `agentclaw/channels/wecom_worker/package.json`
  - `agentclaw/channels/wecom_worker/worker.mjs`
  - 使用 `bot_id + secret + websocket_url` 建立官方 WebSocket 长连接
  - 支持被动流式回复 `replyStream`
  - 支持主动发送 `sendMessage`

#### QQ 渠道简化

- **QQ 渠道切换为 AppID + AppSecret 主路径**
  - `agentclaw/channels/qq.py`
  - `agentclaw/channels/probe.py`
  - 后端接受 `app_secret` 作为主字段，保留 `client_secret` 兼容别名
  - 新增 `QQChannel.on_message()` 实现，修复抽象类无法实例化问题
  - 新增 QQ 主动推送支持

#### 文档请求

- **新增下一阶段需求文档**: `agentclaw/docs/request/REQUEST.md`
  - 知识库开发需求：Milvus、默认混合检索、`models.json` 云端模型、`markitdown` 解析、本地文件存储、知识库 MCP 工具
  - 框架操作 SKILL 需求：框架配置说明、API 操作说明、资源发现能力
  - 持久化记忆需求：`memory.md`、agentic 提示词维护策略、对话 compact 持久化到默认知识库

**Changed**

#### 渠道配置与管理

- **渠道更新时运行时实例同步刷新**: `agentclaw/api/routers/admin/channels.py`
  - 编辑渠道配置后，运行中的实例会立即停止并按新配置重新创建
  - 修复“后台已改工作流，但实际仍调用旧实例”问题

#### WeCom 渠道

- **企业微信渠道重构为双路径**
  - `agentclaw/channels/wecom.py`
  - 默认主路径为智能体机器人 API 模式
  - 保留群机器人 `Webhook` 仅发送模式
  - 旧自建应用模式仅保留兼容能力，不再作为主入口

- **企业微信主动群推送策略调整**
  - bot 模式下若配置 `webhook_key`，主动群推送优先走 Webhook
  - 避免 WebSocket 主动发送只表现为“应用提醒”而非群消息气泡
  - 管理后台在 WeCom bot 模式下重新开放可选 `Webhook Key / URL`

- **企业微信首包时机优化**
  - SSE 建立后立即发送隐藏的 thinking 占位流，先占住企微回复窗口
  - 工具调用或长推理场景下，再用同一条流式消息更新为最终结果
  - 缓解 `Reply ack timeout` 导致的最终回复丢失

#### Admin Dashboard

- **渠道编辑弹窗交互修复**: `agentclaw/admin-dashboard/src/views/Channels.vue`
  - 点击弹窗旁边空白区域不再自动关闭编辑卡片

- **WeCom / QQ 渠道配置表单简化**
  - WeCom 主配置聚焦 `bot` 与 `webhook` 两种模式
  - QQ 配置明确为 `App ID + App Secret`
  - 更新字段提示，减少误导性 Webhook / 自建应用配置

**Fixed**

#### 工具调用后的流式输出

- **修复工具调用轮次导致最终流式失效**
  - `agentclaw/channels/__init__.py`
  - `agentclaw/node/llm.py`
  - 工具调用期间未实时推送给用户的文本，会在最终阶段按原始 chunk 回放
  - 修复“有工具调用时最终输出经常不流式显示”问题

#### Feishu 渠道

- **飞书消息编辑接口改为正确的更新方式**: `agentclaw/channels/feishu.py`
  - 使用 `PUT /open-apis/im/v1/messages/:message_id`
  - 文本更新体改为 `msg_type + content`
  - PatchMessage 流式更新去重逻辑保留

- **忽略飞书不支持的噪声事件**
  - 忽略如 `im.chat.access_event.bot_p2p_chat_entered_v1`、`im.message.message_read_v1`
  - 避免控制台反复打印 `processor not found`

#### DingTalk 渠道

- **修复钉钉 Stream 模式兼容性**
  - `agentclaw/channels/dingtalk.py`
  - 对齐当前安装的 `dingtalk-stream` SDK 行为
  - 修复服务已启动但机器人消息无本地响应的问题

#### WeCom 渠道

- **修复企业微信 `scene` 类型错误**
  - WebSocket 认证参数中的 `scene` 改为数值 `1`
  - 修复 `field body.scene expect type uint32` 错误

- **改进 WeCom 启动容错**
  - Worker 连接中时不再因短暂未 ready 导致后台保存渠道失败
  - 允许异步连接完成，减少 `startup timeout` 误报

- **改进 WeCom 目标保留与日志**
  - 单聊消息也保留统一的 `chat_id`
  - 主动发送成功回执增加明确日志，便于定位群/单聊目标

#### WeChat 渠道

- **移除官方插件依赖的微信渠道**
  - 删除 `agentclaw/channels/wechat.py`
  - 移除模型、路由、探测与后台类型枚举中的 `wechat`
  - 保留企业微信 `wecom`，仅删除独立微信机器人渠道

**Dependencies**

- **pyproject.toml**
  - 增加 `tiktoken`
  - 同步渠道与工具链所需依赖更新

### 2026-03-23

**Fixed**

- **coding_tools.py**: 移除语法验证阻断，改为警告信息
  - `update_code` 工具不再因语法错误拒绝写入
  - 语法问题以 `syntax_warning` 字段返回，由 LLM 决定如何处理

**Added**

- **LLMManager**: 新增 `fast` 模型配置选项
  - 支持在 `models.json` 中配置 `"fast": "model-id"`
  - 用于小任务快速响应场景

### 2026-03-23 (Earlier)

**Added**

#### 示例项目 (examples/)

- **完整示例集恢复**: `agentclaw/examples/` 重新引入 10 个渐进式示例
  - `ex01_hello_world.py` — 最简工作流
  - `ex02_intent_router.py` — 意图路由
  - `ex03_tool_agent.py` — 工具调用 Agent
  - `ex04_human_approval.py` — 人工审批节点
  - `ex05_parallel.py` — 并行执行
  - `ex06_skills.py` — 技能系统集成
  - `ex07_mcp.py` — MCP 协议对接
  - `ex08_custom_node.py` — 自定义节点
  - `ex09_advanced_llm.py` — 高级 LLM 配置
  - `ex10_document.py` — 文档处理
  - `nl2sql.py` — NL2SQL 完整示例 (含 @workflow.tool)
  - `server.py` — 示例启动入口 (工厂函数模式)
- **配置模板**: `models.json.example`, `.env.example`, `mcp.json`
- **技能示例**: `skills/slack-gif-creator/` (含 easing、frame_composer、gif_builder)

#### 内置技能 (Builtin Skills)

- **agent_creator 脚本工具**:
  - `scripts/register_workflow.py` — 4 步注册: AST 预检 → API 热注册 → bootstrap 同步 → 可见性验证
  - `scripts/validate_workflow.py` — 3 探测验证: 注册检查 → 直接运行 (含工厂函数自动发现) → API 运行
  - 支持 `/_internal/` 中转调用 (无需 auth token)
  - validate 脚本增加节点数量验证 (空节点给出明确反馈)

- **scheduler_skill**: 定时任务管理技能
  - `SKILL.md` — 使用指南和 API 参考
  - `scripts/scheduler_api.py` — 定时任务 CRUD 脚本

- **skill_creator**: 技能创建向导
  - `SKILL.md` — 技能创建标准和规范
  - `scripts/init_skill.py` — 技能骨架初始化
  - `scripts/package_skill.py` — 技能打包
  - `scripts/quick_validate.py` — 快速校验

- **clawhub**: 技能市场集成
  - `SKILL.md` — ClawhHub 技能发布指南

#### 工作流热注册增强

- **register-file 端点工厂函数自动发现**: `api/routers/admin/workflows.py`
  - `exec_module()` 后若无新工作流注册，自动扫描 `create_*_workflow()` 工厂函数并调用
  - Fallback 2: 查找模块中的 `Workflow` 实例并直接 `publish()`
  - 返回 `loaded_module` 对象供后续检查

- **register_workflow.py 路径支持增强**:
  - 移除 `workflows/` 目录限制，支持任意项目相对路径
  - `_sync_bootstrap_import` 为单级路径生成 `import <module>`，多级路径生成 `import a.b as b`
  - 向 API 发送解析后的绝对路径 (不再依赖服务端路径解析)
  - 已有 import 检测兼容 `from <module> import ...` 模式

#### 前端 - 推理内容折叠

- **StreamingMessage.vue 推理块可折叠**: 匹配 ChatMessage.vue 的 `mini-thinking` 模式
  - 点击展开/收起推理内容
  - 思考图标 + "思考" 标签 + 展开箭头
  - 并行和顺序 segment 均支持
  - CSS: `.mini-thinking` / `.mini-thinking-header` / `.mini-thinking-body`

#### 前端 - UI 增强

- **AgentChat.vue**: 多项交互改进
- **Scheduler.vue**: 调度器页面优化
- **TraceDetail.vue**: Trace 详情展示增强
- **WorkflowGraph.vue**: 工作流图优化
- **ChatMessage.vue**: 消息渲染改进

#### 输入系统

- **inputs 模块扩展**: `agentclaw/inputs/`
  - `__init__.py` 新增导出
  - `types.py` 新增输入类型定义
  - `parser.py` 解析逻辑优化

#### Tracing 增强

- **tracing 模块补充**: `agentclaw/runtime/tracing/`
  - `base.py` 新增基础字段
  - `db_tracer.py` 数据库 tracer 增强
  - `wrappers.py` 包装器扩展

**Changed**

#### LLMNode 架构重构

- **LLMNode 拆分为 4 个模块**: 从单一 `llm.py` 拆分为职责明确的子模块
  - `llm.py` — 核心节点逻辑和执行入口
  - `llm_tools.py` — 工具调用执行、结果分类、重复检测、失败汇总、schema 去重
  - `llm_skills.py` — 技能加载和 MCP 管理
  - `llm_prompt.py` — Prompt 模板和构建逻辑

#### LLM 中间文本推送

- **工具调用轮间文本推送到前端**: `llm.py`
  - `push_to_context=False` 导致中间轮文本未推送，现在补推给用户
  - 模型输出的解释/思考文本 (如 "好的，我来帮你...") 在工具调用前展示
  - 增加 reasoning 传播诊断日志

#### Skill Tools MCP 兼容性

- **args schema 移除严格类型约束**: `skill_tools.py`
  - `python` 和 `javascript` 工具的 `args` 参数不再强制 `"type": "array"`
  - 移除 JSON Schema 类型验证，避免模型将数组序列化为字符串时被拒绝
  - Handler 新增 JSON 字符串解析: `json.loads(raw_args)` 尝试还原为数组

#### CLI 扩展

- **CLI 命令增强**: `agentclaw/cli.py` 大量新增功能

#### API 层

- **auth middleware**: 认证中间件调整
- **builtin_agent.py**: 内置 Agent 更新
- **execution router**: 执行路由增强
- **model service**: 模型服务优化
- **server.py**: 服务器配置扩展

#### 工作流引擎

- **workflow.py**: 工作流引擎多项改进 (图构建、执行逻辑)

#### Model Manager

- **manager.py**: LLM 管理器功能扩展 (流式、非流式、工具调用)

#### 其他

- **config.py**: 配置项调整
- **database/**: 数据库管理器和文件存储更新
- **custom.py**: CustomNode 增强
- **document.py**: DocumentNode 改进
- **human.py**: HumanNode 扩展
- **skills/parser.py**: 技能解析器重构
- **skills/schema.py**: 技能 schema 更新
- **coding_tools.py**: 代码工具服务器改进
- **workflow_tools.py**: 工作流工具增强
- **CLAUDE.md**: 精简为项目指南核心内容，详细参考分离到 `CLAUDE_REFERENCE.md`
- **SKILL.md (agent_creator)**: 使用指南更新
- **SKILL.md (coding_skill)**: 编码技能文档更新

**Dependencies**

- **pyproject.toml**: 依赖项更新
- **uv.lock**: 锁文件同步更新

---

### 2026-03-17

**Added**

#### 定时任务调度 (Scheduler)

- **完整的定时任务模块**: `agentclaw/scheduler/`，基于 APScheduler 3.x
  - 数据模型 (`models.py`): ScheduledJob、JobExecution、WebhookConfig、TriggerConfig
  - 三种触发器: cron 表达式、固定间隔 (interval)、一次性定时 (date)
  - 持久化存储 (`store.py`): PostgresJobStore (asyncpg)、MemoryJobStore (测试用)
  - 调度核心 (`scheduler.py`): WorkflowScheduler，启动时加载所有 ENABLED 任务
  - 执行器 (`runner.py`): 超时控制、指数退避重试、并发策略 (skip/queue/parallel)
  - 分布式锁 (`lock.py`): PostgreSQL advisory lock 防止重复执行
  - REST API (`api.py`): 任务 CRUD、暂停/恢复、手动触发、Webhook 触发、执行历史

- **Scheduler API 路由** (挂载于 `/api/scheduler/`):
  - `POST /jobs` — 创建定时任务
  - `GET /jobs` — 列表 (支持 status、workflow_id 过滤)
  - `GET/PUT/DELETE /jobs/{id}` — 详情、更新、删除
  - `POST /jobs/{id}/pause|resume|trigger` — 暂停、恢复、手动触发
  - `POST /jobs/{id}/webhook` — Webhook 触发 (X-Webhook-Secret 验证)
  - `GET /jobs/{id}/executions` — 执行历史

- **SchedulerConfig**: `agentclaw/config.py` 新增调度器配置
  - 环境变量: SCHEDULER_TIMEZONE, SCHEDULER_MAX_WORKERS, SCHEDULER_COALESCE, SCHEDULER_MAX_INSTANCES
  - 默认启用，时区 Asia/Shanghai

- **服务器生命周期集成**: `api/server.py` startup 启动 scheduler，shutdown 优雅停止

#### Docker 基础设施

- **Docker Compose 编排**: `agentclaw/docker/docker-compose.yml`
  - PostgreSQL 16 (Alpine) + Redis 7 (Alpine) + Adminer
  - 健康检查、命名卷持久化、自动重启

- **一键启动脚本**: `agentclaw/docker/start.sh`
  - 检查 Python/agentclaw 环境，缺失时自动安装
  - 检查项目目录、server.py、models.json
  - Docker 不可用时降级为内存模式
  - 注入数据库环境变量后启动服务器

- **停止脚本**: `agentclaw/docker/stop.sh`

- **环境变量模板**: `agentclaw/docker/.env.example`，包含全部可配置项

#### CLI 命令

- **`agentclaw up`**: 一键启动基础设施 + 服务器
  - 自动检测 Docker，不可用则降级
  - 选项: `--port`, `--host`, `--project-dir`, `--workers`, `--reload`, `--no-docker`

- **`agentclaw down`**: 停止 Docker 基础设施

- **`agentclaw skill`**: 技能管理命令组
  - 子命令: `list`, `info`, `create`, `remove`
  - `agentclaw skill env`: 技能环境管理 (`list`, `reset`, `clean`, `init`)

#### 前端 - 调度器页面

- **Scheduler.vue**: 定时任务列表页
  - 任务卡片、状态徽章、统计概览
  - 创建任务弹窗 (集成 CronBuilder)
  - 搜索过滤、分页、快捷操作 (触发/暂停/删除)

- **SchedulerDetail.vue**: 任务详情页
  - 编辑表单、执行历史表格
  - 执行详情弹窗 (输入/输出/错误日志)
  - 手动触发、暂停/恢复/删除操作

- **CronBuilder.vue**: 可视化 Cron 构建器
  - 频率选择: 每天/每周/每月/自定义
  - 星期选择器、月历日期选择
  - 时间选择 (时:分)
  - Cron 表达式预览 + 自然语言描述

- **schedulerApi**: `src/api/index.js` 新增调度器 API 方法
- **路由**: `/scheduler`, `/scheduler/:id`
- **侧边栏**: 新增 "⏰ 定时任务" 导航项

#### 前端 - 聊天增强

- **上下文压缩消息展示**: ChatMessage.vue 支持 `is_summary` 消息类型
  - 摘要气泡展示，可展开/收起
  - 显示压缩消息数量等元数据

- **动态消息可见数量**: AgentChat.vue 根据字符预算 (3000) 计算可见消息数
  - "显示全部消息" 提示条
  - 对话创建时更新 URL 中的 conversation_id 参数

#### 文档

- **部署文档**: `agentclaw/docs/zh/deployment.md`
  - 三种部署模式: 一键启动、远程数据库、全量 Docker
  - 功能依赖矩阵 (14 项 PG 依赖、2 项 Redis 依赖)
  - 数据库表清单 (11 张表)

- **调度器设计文档**: `agentclaw/docs/zh/scheduler_design.md`
  - 架构设计、数据模型、API 规范、Webhook 集成、执行流程

- **用户指南/API 参考更新**: 中英文文档新增调度器章节

**Changed**

#### 工作流引擎

- **节点输出优化**: `graph/workflow.py` node_finished 事件仅包含新增/变更的 state key
  - 执行前快照 `state_keys_before`，执行后对比差异
  - 减少 SSE 事件数据量，提升流式输出清晰度

#### 内置 Agent

- **更新描述和欢迎语**: builtin_agent.py 统一为 "全能 AI 助手" 定位

#### 运行时

- **SSE 默认非流式**: `runtime/streaming/context.py` output() 的 `stream` 参数默认值改为 `False`

**Removed**

#### 示例目录

- **删除 `agentclaw/examples/`**: 移除全部示例文件 (14 个文件)
  - 包括 ex01-ex07 示例脚本、server.py、配置模板
  - 包括 slack-gif-creator 技能示例
  - 已由 `agentclaw init` 脚手架命令替代

**Dependencies**

- **新增可选依赖组 `scheduler`**: pyproject.toml
  - `APScheduler>=3.10.0,<4.0.0`
  - `croniter>=2.0.0`

---

### 2026-03-13

**Added**

#### Context Compression

- **LLM-based context compression**: Automatic compression when token threshold exceeded
  - New module: `agentclaw/runtime/context_compressor.py`
  - Uses LLM to generate intelligent summaries preserving key information
  - Preserves system prompt and welcome message, compresses all other messages into one summary
  - Configurable via `LLMNode` parameters: `enable_compression`, `compression_threshold`, `compression_max_length`, `compression_model`
  - Triggered after LLM call completes, updates `__messages__` state and persists to database
  - Falls back to rule-based summarization if LLM fails

- **Context Compression SSE Events**: Real-time frontend notifications
  - `context_compression_started` - emitted when compression begins with original token count
  - `context_compression_finished` - emitted when compression completes with statistics
  - Schema models: `ContextCompressionStartedEvent`, `ContextCompressionFinishedEvent`
  - Frontend displays "📦 Compressing context..." / "✅ Context compression completed" status

#### Parallel Execution

- **Parallel node execution fix**: Fixed LangGraph state overwrites in parallel branches
  - Fixed `add_edge("__start__", [list])` to create virtual `__start_fork__` node for parallel execution
  - Fixed `_last_value` reducer to preserve non-None values (prevents `None` from one branch overwriting valid data from another)
  - Enables proper parallel execution of nodes like `tool_filter` and `skill_filter`

#### Node Enhancements

- **Node description field**: Human-readable display names for nodes
  - Added `description` parameter to `CustomNode.__init__`
  - Used in frontend node status display and trace views
  - Example: `description="Filtering relevant tools..."`

#### Dynamic Discovery

- **Dynamic tool/skill filtering**: Replaced hardcoded lists with dynamic discovery
  - Tool filter and skill filter nodes now discover available MCP servers and skills at runtime
  - Filters are applied to the full set of tools/skills, not just hardcoded builtin ones
  - Includes user-configured MCP servers in filtering scope

**Changed**

#### Frontend Improvements

- **Auto-scroll enhancement**: Only auto-scrolls when user is near bottom of chat
  - Threshold: 100px from bottom
  - Prevents annoying jumps when user is reading earlier content

- **Thinking content improvements**:
  - Collapsible thinking/reasoning content
  - Preserves newline formatting for better readability
  - Clean expand/collapse UI

---

### 2026-03-12

**Added**

#### Built-in Skills

- **Agent Creator skill**: Design and create workflows from natural language
  - Location: `agentclaw/skills/builtin_skills/agent_creator/`
  - Creates workflows from requirements, adds routing/tools/skills
  - Supports Lean Mode (minimal edits) and Full Mode (complete rewrites)
  - References: principle, syntax error fixes, API docs, template library

- **Coding Skill**: Safe code inspection and editing within project boundaries
  - Location: `agentclaw/skills/builtin_skills/coding_skill/`
  - Tools: search_code, read_code, replace_in_file, update_code, syntax check
  - Enforces project_dir-relative paths for security
  - Workflow references for agent_workflow coding patterns

#### Built-in MCP Servers (Restructured)

- **Modular server package**: `agentclaw/mcp/builtin_servers/` now a proper package
  - `__init__.py`: Central exports and server registry
  - `registry.py`: Server registration and configuration management
  - `skill_tools.py`: Skill-related tools (python, shell, file operations)
  - `coding_tools.py`: Code search and editing tools (search_code, read_code, replace_in_file)
  - `workflow_tools.py`: Workflow management tools (CRUD operations)
  - `planning_tools.py`: Task planning and todo management
  - `browser_tools.py`: Browser automation via Playwright
  - `computer_tools.py`: System control and screenshots
  - `download_tools.py`: File download with token generation
  - `search_tools.py`: SearXNG integration (conditional)

#### Welcome API

- **Conversation welcome endpoint**: `GET /api/conversations/{workflow_id}/welcome`
  - Returns workflow's welcome message for display in chat UI
  - Used by AgentChat to show initial greeting bubble

#### State Schema Changes

- **State renamed to inputs**: Frontend-facing state key changed from `state` to `inputs`
  - Aligns with LangGraph state/inputs convention
  - Affects AgentChat.vue and workflow execution API
  - Backward compatible for existing workflows

#### Dashboard Agent Management

- **New Agents.vue page**: Dedicated agent/workflow management UI
  - List all registered workflows
  - Edit workflow configuration inline
  - Toggle workflow enable/disable status

- **Sidebar navigation**: Added "Agents" menu item for quick access

---

### 2026-03-04

**Added**

#### Configuration System
- **Unified config module**: Added `agentclaw.config` as a centralized configuration entrypoint
  - Auto-loads `.env` on first `get_config()` call
  - Auto-discovers `skills/`, `mcp.json`, `models.json`, `.env` from script dir/CWD
  - Provides typed config models for database/redis/auth/workflow/upload/project
  - Supports `load_config(reload=True)` for explicit runtime reload

#### Built-in Agent
- **Built-in workflow registration**: Added `__builtin__` workflow auto-registration on server startup
  - New module: `agentclaw/api/builtin_agent.py`
  - Built-in node defaults: `agent_style="agentic"`, `skills="*"`, `tools="*"`, `enable_builtin_tools=True` (includes planning tools)
  - Dashboard entry supports direct chat with built-in assistant

#### Public Upload API
- **Attachment upload endpoints**: Added upload router under `/api`
  - `GET /api/upload/status`: checks upload availability + max size
  - `POST /api/upload`: authenticated file upload with DB availability guard and size limit
  - New schema module: `agentclaw/api/schemas/upload.py`

#### Built-in MCP Servers
- **`search-tools` server** (SearXNG): Added web/news/image search tools
  - Conditional activation via `SEARXNG_BASE_URL`
  - Tools: `search_web`, `search_news`, `search_images`
- **`computer-tools` server**: Added screenshot and system simulation tools
  - Tools: `screenshot`, `mouse_click`, `mouse_move`, `keyboard_type`, `keyboard_key`, `get_screen_size`
- **Browser MCP split**: Added dedicated browser server module `agentclaw/mcp/browser_server.py`
  - Browser automation runtime isolated from `builtin_servers.py`

**Changed**

#### API & Runtime
- **Tool config persistence**: `ToolConfigManager` now persists disabled skills/tools to project-local files
  - Storage path: `<project_dir>/.agentclaw/*_tool_config.json`
  - Config survives server restart
  - Added stale-config warnings for unavailable tools/skills in `__builtin__` workflow

- **File upload configuration**:
  - Added `MAX_UPLOAD_SIZE_MB` to `.env.example`
  - Upload directory resolution now prefers absolute path and project-local fallback (`<project_dir>/.uploads`)

- **Auth token loading**:
  - `AdminTokenManager` and `WorkflowAPIKeyManager` now read from unified config (`get_config().auth.*`)
  - Keeps token loading behavior consistent with `.env` auto-discovery

#### LLM & Tool Runtime
- **Built-in tool injection expansion**:
  - `enable_builtin_tools=True` now manages `skill-tools`, `browser-tools`, `computer-tools`, `download-tools`
  - `search-tools` is auto-injected when `SEARXNG_BASE_URL` is configured
- **Tool-call round execution**:
  - Parallel execution per round via `asyncio.gather`
  - Merged multi-tool calls into one assistant message + multiple tool messages
  - Added structured markers: `[TOOL_SUCCESS]` / `[TOOL_FAILED:<CODE>]`
  - Injects `<TOOL_EXECUTION_SUMMARY>` when failures occur (and deduplicates previous summaries)
- **Tool schema safety**: Added final dedupe by `function.name` to avoid duplicate function-definition provider errors
- **File attachment injection**:
  - Added `inject_files` option in `LLMNode` (`None` = auto for `agentic`)
  - Injects uploaded file paths into the latest user message as `<attached_files>`
  - Workflow state schema now includes `__files__`

#### Skill Tools
- **`read_file` capability upgrades**:
  - Document conversion via `markitdown` for PDF/DOCX/PPTX/XLSX and related formats
  - Vision-based image analysis via `models.json` `vision` config + optional prompt
  - Supports absolute-path reads in addition to `working_dir` relative paths
- **Non-blocking skill startup**:
  - Skill loading moved to background executor/thread to avoid blocking MCP server startup
  - Allows core builtin tools to be available while skills are still loading

#### API & Dashboard
- **Workflow execution payload**: `POST /api/workflow/run` now accepts `files` and maps them to `inputs["__files__"]`
- **Conversation API pagination**:
  - `GET /conversations/{workflow_id}` now supports `page` + `page_size`
  - Returns `total`, `page`, and `page_size`
- **Builtin workflow entry in dashboard**:
  - New route `/builtin` and `BuiltinAgent.vue`
  - Sidebar adds "内置智能体" entry
  - Workflow/agent/prompt lists filter out `__builtin__` where needed
- **AgentChat UX updates**:
  - Added attachment upload chips and upload status probing (`/api/upload/status`)
  - Added custom confirmation dialog with optional sudo password input
  - Split skill config and tool config panels; show stale disabled-item warnings from backend

#### Documentation
- **Docs relocation**: Moved user docs from `docs/` to `agentclaw/docs/`
- **API docs refresh**: Updated public API endpoint documentation to include:
  - `/api/confirm/{confirm_id}`
  - `/api/download/{token}`
  - `/api/upload/status`, `/api/upload`
  - `/api/conversations/*`
- **Quickstart update**: Updated non-stream mode example to use `mode: "blocking"`

**Removed**

#### Repository Cleanup
- **Removed `agentclaw/clawdemo/` tree**:
  - Removed legacy demo app entry files and bundled skill assets/templates/fonts
  - Reduced repository size and removed duplicated skill distribution content

### 2026-03-02

**Fixed**

#### Builtin Tools Availability

- **skill-tools MCP server**: Now starts with `enable_builtin_tools=True` regardless of skills directory existence
  - 6 basic tools (python, javascript, shell, read_file, write_file, list_files) available without skills
  - Skill-specific features (venv, node_modules) only activate when skills directory exists
  - Fixed: Previously required skills directory to start, blocking builtin agent in projects without skills
  - Backend: [agentclaw/node/llm.py:745-791](agentclaw/node/llm.py#L745-L791)
  - Frontend API: [agentclaw/api/routers/admin/workflows.py:264-276](agentclaw/api/routers/admin/workflows.py#L264-L276)

### 2026-02-28

**Added**

#### Sudo Confirmation Support
- **`confirm_action` sudo support**: Extended `confirm_action` tool to support sudo password input
  - New parameter: `require_sudo` (bool) - request sudo password from user
  - Frontend receives password via SSE event and returns it through API
  - Password stored temporarily in workflow state for follow-up `execute_sudo_command`
  - Security: password only in memory, session-scoped

- **`execute_sudo_command` built-in tool**: Execute commands with sudo privileges
  - Requires prior `confirm_action(require_sudo=true)` authorization
  - Uses `echo password | sudo -S command` pattern
  - Filters sudo prompts from stderr output
  - Use cases: docker, systemctl, apt, system administration

- **API enhancements**:
  - `ConfirmActionRequest.sudo_password` field (optional)
  - `ConfirmActionResponse.require_sudo` and `sudo_received` fields
  - `ConfirmRequestEvent.require_sudo` field in SSE events
  - `POST /api/confirm/{confirm_id}` returns sudo status

#### MCP Server-Level Locking
- **Parallel execution safety**: Added `asyncio.Lock` per MCP server to prevent stdio pollution
  - Same server tools execute serially (via lock)
  - Different server tools execute in parallel (via `asyncio.gather`)
  - Prevents JSONRPC message corruption from concurrent stdio access
  - Locks managed in `MCPManager._server_locks`

**Fixed**

- **Duplicate failure summary injection**: Clear old `<TOOL_EXECUTION_SUMMARY>` messages before injecting new ones
- **MCP stdio parallel execution**: Resolved stdout pollution issues when multiple tools call same MCP server concurrently
- **MCP connection robustness**:
  - Added retry logic for MCP server connection/initialization
  - Added best-effort cleanup for failed session/transport contexts
  - Converts internal `anyio`/cancel-scope pseudo-cancel into recoverable connection errors

### 2026-02-12

**Added**

#### API Standardization (Issue #6)
- **Public API Router**: Extracted inline endpoints from `AgentClawServer._create_app()` to `agentclaw/api/routers/public/`
  - `execution.py` - workflow run, confirm action, file download, workflow list
  - `router.py` - aggregates all public routes under `/api` prefix
- **Execution schemas**: `WorkflowRunRequest`, `WorkflowRunResponse`, `WorkflowRunError`, `ConfirmActionRequest`, `ConfirmActionResponse` in `agentclaw/api/schemas/execution.py`
- **SSE event schemas**: All 11 SSE event types documented as Pydantic models in `agentclaw/api/schemas/sse_events.py`
- **Conversation schemas**: `ConversationMessage`, `ConversationInfo`, `FeedbackRequest` etc. in `agentclaw/api/schemas/conversation.py`
- **Conversation service layer**: `agentclaw/api/services/conversation_service.py` - database operations extracted from router
- **OpenAPI annotations**: All endpoints now have `summary`, `description`, and English docstrings

**Changed**

#### API Standardization
- **OpenAPI tags unified to English**: All router tags changed from Chinese to English (`workflows`, `traces`, `prompts`, `models`, `tasks`, `auth`, `dashboard`, `conversations`, `debug`, `health`, `execution`)
- **`_stream_workflow` extracted**: Moved from `AgentClawServer` class method to standalone function in `execution.py` router
- **`_create_app()` simplified**: Now only registers routers and middleware, no inline endpoint definitions
- **Conversations API refactored**: Database operations moved to `ConversationService`, router uses dependency injection
- **Conversations pagination**: List endpoint now supports `page` + `page_size` parameters with total count

#### LLMNode Enhancements
- **`enable_builtin_tools` parameter**: Enable built-in high-privilege tools (download-tools, etc.). Default: `False`
  - Provides `create_download_url` tool for generating temporary download links
  - Requires Redis for token storage
  - Files must be within `working_dir` for security
  
- **Planning tools activation**: planning-tools now follow `enable_builtin_tools=True`
  - No separate `enable_planning` field required
  - Helps agent break down complex tasks through Todo tools

- **Browser tools auto-injection**: Browser automation is injected as built-in tools
  - Enabled via `enable_builtin_tools=True`
  - Provides navigate, snapshot, click, fill, and other browser actions
  - Requires playwright: `pip install playwright && playwright install chromium`
  
- **`confirm_action` built-in tool**: Request user confirmation before destructive operations
  - Injected when `enable_builtin_tools=True` (non-disableable safety tool)
  - Blocks execution until user approves/rejects
  - 5-minute timeout
  - Use cases: file deletion, package installation, database modifications

- **Vision model auto-switching**: Automatically switches to vision model when images detected
  - Configure via `models.json`: `"vision": "model-id"` or `"type": "vision"`
  - Auto-detects images from state (file paths, data URLs, http URLs)
  - Supports `images_key` parameter for explicit image input

- **Enhanced AGENTIC_PROMPT_TEMPLATE**: Strengthened anti-fabrication rules
  - Rule 1: ABSOLUTE PROHIBITION ON FABRICATION - Never invent tool results, file contents, data, or facts
  - Rule 2: Always read SKILL.md before using a skill
  - Rule 3: Verify CLI tools exist with `which` before running
  - Rule 4: MANDATORY confirm_action for destructive operations
  - Rule 5: No shell command chaining (`&&`, `||`, `;`)
  - Rule 6: Report errors clearly, never make up output
  - Rule 7: Verify tool results, report failures honestly

- **Current time injection**: `{{__current_time__}}` automatically injected into state
  - Format: `YYYY-MM-DD HH:MM:SS DayOfWeek`
  - Available in AGENTIC_PROMPT_TEMPLATE

#### Vision Model Support
- **`models.json` vision field**: Configure vision model explicitly
  ```json
  {
    "default": "gpt-4",
    "vision": "gpt-4-vision",
    "models": [...]
  }
  ```
- **`LLMManager.get_vision_model_id()`**: Get configured vision model ID
  - Priority: explicit `vision` field > first model with `type: "vision"`

#### Skills System
- **Dynamic skill loading**: `SkillManager.refresh()` method for incremental discovery
  - Called automatically when `skills="*"` is used
  - Discovers new skills without restart
  
- **Skip directories with spaces**: Directories containing spaces in name are automatically skipped
  - Prevents import errors from invalid Python module names

#### Builtin MCP Servers
- **`browser-tools`**: Browser automation via CDP (Chrome DevTools Protocol)
  - Single `browser` tool with action-based dispatch
  - Actions: navigate, snapshot, click, fill, type, hover, drag, select, fill_form, scroll_into_view, press, wait, get_text, eval, tabs, switch_tab, new_tab, close_tab, close
  - Element refs (e1, e2...) via ariaSnapshot + getByRole for precise interaction
  - Auto-launches Chrome/Edge if no CDP connection found
  - Requires: `pip install playwright && playwright install chromium`
  - Enabled when `LLMNode(enable_builtin_tools=True)`

- **`download-tools`**: Generate temporary download URLs for files
  - Tool: `create_download_url(path, filename?, ttl?)`
  - Backend: Redis-based token storage
  - Endpoint: `GET /api/download/{token}`
  
- **`planning-tools`**: Task planning and tracking
  - Tools: `TodoWrite`, `GetTodos`
  - Helps agent organize multi-step tasks
  
- **`skill-tools`**: Execute skill scripts and read skill files
  - Tools: `python`, `shell`, `read_file`
  - Isolated virtual environments per skill

#### Admin Dashboard
- **Token tracking in Traces UI**:
  - Traces list shows total tokens per execution
  - TraceDetail shows per-node input/output tokens
  - Aggregated from `llm_logs` table via SQL join
  
- **Tool config panel enhancements**:
  - Group MCP tools by server name
  - Show builtin tools dynamically (planning-tools, download-tools, skill-tools)
  - Filter tools by node type (LLMNode only, exclude MCPNode)
  
- **Multi-conversation support in public agent page**:
  - Sidebar shows conversation history
  - Defaults to expanded in public mode
  - Wider container (1100px)

#### API & Server
- **`GET /api/download/{token}`**: Download files via temporary tokens
  - Validates token from Redis
  - Checks file path security (must be within working_dir)
  - Returns file with proper content-type
  
- **`GET /admin/workflows/{id}/tool-config`**: Get available tools for workflow
  - Returns tools grouped by server
  - Includes builtin tools (dynamically loaded)
  - Filters by node type (LLMNode only)
  
- **Merged `enable_admin` and `enable_admin_dashboard`**: Single `enable_admin` parameter
  - Controls both API and dashboard
  - Default: `True`

#### Workflow
- **`models_config` parameter**: Specify models.json path explicitly
  - Search order: explicit path → CWD → mcp_config's directory
  - Fixes issue where models.json was loaded from wrong directory

#### Additional Changes

- **`enable_mcp` renamed to `publish_as_mcp`**: More clearly indicates the workflow is being published as an MCP server
  ```python
  # Before
  workflow = Workflow(id="my_tool", enable_mcp=True)
  
  # After
  workflow = Workflow(id="my_tool", publish_as_mcp=True)
  ```

- **`max_tool_rounds` default**: Changed from 10 to 50
  - Allows more complex multi-step tasks
  - Configurable via `MAX_TOOL_ROUNDS` environment variable

- **Tool call error handling**: Wrap all tool calls in try/except
  - Returns `[ERROR]` prefix for failures
  - Prevents agent from ignoring errors

- **Prompt registration timing**: Moved to end of `_ensure_components()`
  - Ensures prompts are always registered
  - Fixes empty prompt management page

- **Frontend build**: Pre-built dist files included
  - No need to run `npm run build` for basic usage
  - Source changes require rebuild

**Removed**

- **Hardcoded tool switching strategies**: Removed rule 8 (NO REPETITIVE RETRIES)
  - Prompt-based rules are brittle workarounds
  - Model should learn tool selection naturally
  
- **`enable_admin_dashboard` parameter**: Merged into `enable_admin`
  - Simplifies configuration
  - Backward compatibility not maintained (breaking change)

- **`agents_dir` parameter**: Removed from AgentClawServer
  - Workflows should be registered explicitly via `workflow.publish()`

**Fixed**

- **Stop button disabled during streaming**: Fixed `canSend` logic
  - Stop button (⏹) now works during streaming
  - Changed to `:disabled="isStreaming ? false : !canSend"`

- **Empty prompt management page**: Fixed prompt registration timing
  - Prompts now registered after all components initialized

- **Vision model not used**: Fixed auto-detection and switching
  - Images auto-detected from state
  - Vision model automatically selected when images present

- **Skill directories with spaces**: Now skipped automatically
  - Prevents import errors

- **Tool result fabrication**: Enhanced error detection and reporting
  - All tool errors prefixed with `[ERROR]`
  - Strengthened anti-fabrication rules in prompt

**Security**

- **Download endpoint path validation**: Files must be within `working_dir`
  - Prevents directory traversal attacks
  - Returns 403 Forbidden for invalid paths

- **confirm_action for destructive operations**: Mandatory user confirmation
  - Prevents accidental data loss
  - Blocks execution until user approves

**Dependencies**

- **Added `redis` as optional dependency**: Required for download-tools
  - Install with: `pip install agentclaw-ai[redis]` or `pip install redis`

---

## Migration Guide

### Breaking Changes

1. **`enable_admin_dashboard` removed**: Use `enable_admin` instead
   ```python
   # Before
   server = AgentClawServer(enable_admin=True, enable_admin_dashboard=True)
   
   # After
   server = AgentClawServer(enable_admin=True)
   ```

2. **`agents_dir` removed**: Register workflows explicitly
   ```python
   # Before
   server = AgentClawServer(agents_dir="./agents")
   
   # After
   workflow = Workflow(...)
   workflow.publish()
   server = AgentClawServer()
   ```

### Recommended Updates

1. **Enable builtin tools for skills**:
   ```python
   LLMNode(
       skills="*",
       enable_builtin_tools=True,  # Add this
   )
   ```

2. **Configure vision model**:
   ```json
   {
     "default": "gpt-4",
     "vision": "gpt-4-vision",
     "models": [...]
   }
   ```

3. **Use agentic style for complex tasks**:
   ```python
   LLMNode(
       agent_style="agentic",
       enable_builtin_tools=True,
   )
   ```

---

## Notes

- All changes are backward compatible unless marked as "Breaking Changes"
- Frontend changes require `npm run build` in `agentclaw/admin-dashboard`
- Redis is optional but recommended for production use (download-tools, distributed state)
