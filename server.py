"""
AgentClaw 服务入口

启动方式：
  agentclaw serve
  # 或
  python server.py
"""

# 导入 agents 模块，自动注册所有工作流
import agents  # noqa: F401

# 如果直接运行此文件，启动服务器
if __name__ == "__main__":
    from agentclaw import AgentClawServer

    server = AgentClawServer()
    server.run()
