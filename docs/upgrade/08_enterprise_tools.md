# 企业工具接入框架（Enterprise Tools）

> 状态：✅ 已完成
> 交付物：`agentclaw/tools/` 子包（spec/executor/loader/server）+ 3 个示例 + mcp.json 配置 + 14 测试
> 验收：14 passed，MCP server 启动正常，不破坏现有功能

---

## 1. 目标

把**异构工具**（Python 函数 / HTTP API / CLI 脚本）统一成一份规范，暴露为**全局 MCP server**，让所有 agent 自动可用。**加工具只加 YAML，不改代码**。

## 2. 统一规范（ToolSpec）

每个工具一份 YAML，放 `tools/specs/`：

```yaml
name: query_order                    # 工具名（snake_case，AI 调用用）
description: 根据订单号查询订单状态     # AI 看这个决定何时调用（写清楚做什么+何时用）
input_schema:                        # JSON Schema 参数定义
  type: object
  properties:
    order_id: { type: string, description: 订单号 }
  required: [order_id]
handler:                             # 实现适配（异构统一到这）
  type: http                         # python | http | cli
  method: GET
  url: "https://api.internal/orders/{order_id}"   # {param} 占位
  auth_env: ORDER_API_KEY            # 密钥走环境变量，不进配置
  timeout: 10
permission: read_only                # read_only | write_with_approval | write_auto（Phase 9 接 RBAC）
domain: sales                        # 可选，按领域过滤
```

## 3. 三类 Handler

| type | 字段 | 执行方式 |
|---|---|---|
| `python` | module + function | importlib 反射调用（支持 sync/async 函数） |
| `http` | method + url{占位} + auth_env + body_template + headers | httpx 异步请求，auth_env 自动注入 Bearer |
| `cli` | command + args{占位} + cwd + timeout | subprocess.run（to_thread，兼容 Windows selector loop） |

**关键点**：
- HTTP/CLI 的 `{param}` 占位由 input_schema 参数自动替换
- HTTP 的密钥走 `auth_env`（环境变量名），**不写进配置**（安全）
- CLI 用 `subprocess.run + asyncio.to_thread`，绕过 agentclaw 的 Windows selector event loop 不支持 `asyncio.create_subprocess_exec` 的限制
- 所有执行错误捕获返回 `[Error] ...`，不抛异常（避免 agent 卡死）

## 4. 接入流程

1. **写工具定义**：在 `tools/specs/` 下为每个工具写一份 YAML
2. **mcp.json 配置**（已配好，见 [mcp.json](mcp.json)）：
   ```json
   "enterprise-tools": {
     "command": "python",
     "args": ["-m", "agentclaw.tools.server", "--specs-dir", "tools/specs"]
   }
   ```
3. **agent 自动使用**：所有 agent 通过 MCPManager 加载，`LLMNode(enable_builtin_tools=True)` 或 `MCPNode` 直接调用

加新工具：写一份 YAML 放 `tools/specs/`，重启 server 即生效（agent 自动发现新工具）。

## 5. 模块结构

```
agentclaw/tools/
├── __init__.py      # 导出
├── spec.py          # ToolSpec + HandlerSpec（统一规范）
├── executor.py      # ToolExecutor（python/http/cli 执行）
├── loader.py        # load_specs（tools/specs/*.yaml 批量加载）
└── server.py        # stdio MCP server（python -m agentclaw.tools.server）

tools/specs/         # 用户工具定义（项目根，YAML）
├── ping_host.yaml       # 示例：cli 工具
├── query_order.yaml     # 示例：http 工具（含 auth_env）
└── format_json.yaml     # 示例：python 工具
```

## 6. 示例工具（已带）

| 工具 | 类型 | 说明 |
|---|---|---|
| `ping_host` | cli | ping 主机检查连通性（`ping -n 4 {host}`） |
| `query_order` | http | 查询订单 API（`GET /orders/{order_id}`，auth_env=ORDER_API_KEY） |
| `format_json` | python | json.dumps 序列化（演示 module/function） |

## 7. 怎么加你的工具（典型场景）

**Python 函数**（如 `my_company.tools.reports.monthly_report`）：
```yaml
name: monthly_report
description: 生成本月运营月报
input_schema: { type: object, properties: { dept: { type: string } }, required: [dept] }
handler: { type: python, module: my_company.tools.reports, function: monthly_report }
permission: write_with_approval
```

**HTTP API**（如内部 CRM）：
```yaml
name: crm_get_customer
description: 查询 CRM 客户信息
input_schema: { type: object, properties: { customer_id: { type: string } }, required: [customer_id] }
handler:
  type: http
  method: GET
  url: "https://crm.internal/customers/{customer_id}"
  auth_env: CRM_API_KEY
permission: read_only
```

**CLI/脚本**（如公司内部工具）：
```yaml
name: run_etl
description: 触发 ETL 任务
input_schema: { type: object, properties: { job: { type: string } }, required: [job] }
handler: { type: cli, command: "/opt/etl/run.sh", args: ["{job}"], timeout: 120 }
permission: write_with_approval
```

## 8. 测试（[test_enterprise_tools.py](agentclaw/test/unit/test_enterprise_tools.py)）

14 个测试：加载（3 示例 + 缺目录）/ 三类 executor（python 同步+异步 / cli 子进程+参数替换 / http mock URL 占位）/ 错误处理（未知工具 + 模块缺失）/ MCP server 构建 / 不破坏 import。

**结果**：`14 passed`，MCP server 启动正常。

## 9. 衔接

| 阶段 | 如何用本框架 |
|---|---|
| Phase 9 RBAC | `permission` 字段（read_only/write_with_approval/write_auto）接入工具权限校验 |
| Agent Factory | 生成的 agent blueprint.tools 可引用企业工具（`tools/specs/` 定义的 name） |
| 后续（已有 MCP/OpenAPI） | 已有 MCP server 可直接进 mcp.json；OpenAPI 可写脚本批量生成 ToolSpec YAML |

## 10. 回滚

删除 `agentclaw/tools/` + 移除 mcp.json 的 `enterprise-tools` 条目即完全回滚。
