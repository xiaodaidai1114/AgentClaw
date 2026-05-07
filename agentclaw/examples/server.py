"""AgentClaw examples project server.

Usage:
    cd agentclaw/examples
    agentclaw up
    # or
    agentclaw serve

Then open:
    http://localhost:8000/dashboard
"""

import agents  # noqa: F401


if __name__ == "__main__":
    from agentclaw import AgentClawServer

    server = AgentClawServer()
    server.run()
