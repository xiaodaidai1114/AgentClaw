"""Agent Factory public routes (Phase 2).

POST /api/agents/generate — 一句话生成企业 Agent。

仅在 AGENTCLAW_ENABLE_AGENT_FACTORY=true 时挂载（见 server.py）。
CLI create-agent 不受此开关影响，始终可用。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body
from pydantic import BaseModel, Field

router = APIRouter(prefix="/agents", tags=["agent-factory"])


class GenerateAgentRequest(BaseModel):
    request: str = Field(..., description="自然语言需求，如「创建一个销售线索分析助手」")
    register: bool = Field(False, description="生成后是否热注册到 WorkflowRegistry")
    templates_dir: Optional[str] = Field(None, description="额外企业模板目录")


@router.post("/generate", summary="一句话生成企业 Agent")
async def generate_agent_endpoint(req: GenerateAgentRequest = Body(...)):
    from agentclaw.agent_factory import generate_agent
    from agentclaw.config import get_config

    cfg = get_config().agent_factory
    register = req.register or cfg.auto_register

    result = generate_agent(
        req.request,
        register=register,
        templates_dir=req.templates_dir or cfg.templates_dir or None,
    )

    return {
        "agent_name": result.blueprint.name,
        "display_name": result.blueprint.display_name,
        "domain": result.domain,
        "template": result.template.display_name,
        "version": result.blueprint.version,
        "scaffold_dir": str(result.scaffold.scaffold_dir),
        "workflow_file": str(result.scaffold.workflow_file),
        "registered": result.registered,
        "blueprint": result.blueprint.model_dump(mode="json"),
    }
