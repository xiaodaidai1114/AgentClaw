"""Prompt key helpers for the Werewolf Claw App."""

from __future__ import annotations

from pathlib import Path
from typing import Any


APP_DIR = Path(__file__).resolve().parents[1]
PROMPTS_DIR = APP_DIR / "prompts"

WOLF_TEAM_STRATEGY_PROMPT = """
狼队策略约束：
- 悍跳预言家时必须先像真预言家：验人、警徽流、验人理由、对跳压力和后续视角要自洽，不要只攻击真预言家或只保护狼队友。
- 狼队不要全员挤在同一种位置；悍跳狼、冲锋狼、倒钩狼、深水狼要拉开距离，警上警下也要有分布。
- 不要所有狼都上警；如果已有狼悍跳，其他狼可以留在警下控票、轻站边、倒钩或只打局部逻辑。
- 不要让所有狼人警徽票都投给狼队友；警徽票要考虑公开发言收益，可以有人站边真预言家、打保守票、弃弱队友或做身份。
- 上警狼队友不要默认给悍跳狼打冲锋；根据座位、发言质量和票型收益，分配倒钩、垫飞、切割、潜伏或轻站边。
- 狼人发言要先像自己声称的身份或闭眼好人视角，再服务狼队目标；不要暴露“我知道谁是狼队友”的信息。
- 被狼队友发金水或被队友保护时，不要无脑回护；可以质疑、保留、切割或只认发言不认身份。
"""

WEREWOLF_PROMPT_KEYS = (
    "werewolf_terms",
    "werewolf_actor_policy",
    "werewolf_persona_generation",
    "werewolf_night_action",
    "werewolf_sheriff_join",
    "werewolf_sheriff_speech",
    "werewolf_sheriff_vote",
    "werewolf_day_speech",
    "werewolf_day_order",
    "werewolf_day_vote",
)

PHASE_PROMPT_BY_KIND = {
    "night_kill": "werewolf_night_action",
    "seer_check": "werewolf_night_action",
    "guard": "werewolf_night_action",
    "witch": "werewolf_night_action",
    "hunter_status": "werewolf_night_action",
    "hunter_shot": "werewolf_day_vote",
    "wolf_king_shot": "werewolf_day_vote",
    "sheriff_badge": "werewolf_day_vote",
    "election_join": "werewolf_sheriff_join",
    "election_speech": "werewolf_sheriff_speech",
    "election_vote": "werewolf_sheriff_vote",
    "election_pk_speech": "werewolf_sheriff_speech",
    "election_pk_vote": "werewolf_sheriff_vote",
    "day_speech": "werewolf_day_speech",
    "day_order": "werewolf_day_order",
    "day_vote": "werewolf_day_vote",
    "day_pk_speech": "werewolf_day_speech",
    "day_pk_vote": "werewolf_day_vote",
    "last_words": "werewolf_day_speech",
}


def build_actor_prompt(actor_view: dict[str, Any]) -> str:
    """Build PromptManager references for one actor decision."""

    kind = str(actor_view.get("kind") or "")
    phase_prompt_key = PHASE_PROMPT_BY_KIND.get(kind, "werewolf_actor_policy")
    return (
        "{@werewolf_terms}\n\n"
        "{@werewolf_actor_policy}\n\n"
        f"{WOLF_TEAM_STRATEGY_PROMPT}\n\n"
        f"{{@{phase_prompt_key}}}\n\n"
        "请只基于 actor_view 决策。actor_view 会作为用户消息传入。"
    )
