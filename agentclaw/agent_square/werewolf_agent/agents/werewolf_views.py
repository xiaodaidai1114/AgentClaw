"""View builders for Werewolf actor workflows."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


VOTE_PHASE_NOTES = {
    "election_vote": "警长投票：投给某人表示支持其当选警长，不表示放逐或攻击该玩家。",
    "election_pk_vote": "警长PK投票：投给某人表示支持其当选警长，不表示放逐或攻击该玩家。",
    "day_vote": "白天放逐投票：投给某人表示希望其出局。",
    "day_pk_vote": "白天PK放逐投票：投给某人表示希望其出局。",
}


def build_vote_records(votes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for vote in votes:
        from_seat = int(vote.get("from") or 0)
        target_seat = int(vote.get("to") or 0)
        phase = str(vote.get("phase") or "")
        if phase == "election_vote":
            meaning = f"{from_seat}号在警长投票中支持{target_seat}号当选警长，不表示放逐或攻击{target_seat}号。"
        elif phase == "election_pk_vote":
            meaning = f"{from_seat}号在警长PK投票中支持{target_seat}号当选警长，不表示放逐或攻击{target_seat}号。"
        elif phase == "day_vote":
            meaning = f"{from_seat}号在白天放逐投票中投{target_seat}号出局。"
        elif phase == "day_pk_vote":
            meaning = f"{from_seat}号在白天PK放逐投票中投{target_seat}号出局。"
        else:
            meaning = f"{from_seat}号在{phase}阶段投给{target_seat}号。"
        records.append({
            "from": from_seat,
            "to": target_seat,
            "phase": phase,
            "meaning": meaning,
        })
    return records


def build_actor_view(request: dict[str, Any], memory: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the information an actor may see for one decision.

    The main workflow owns the full game state. Child actor workflows should
    consume a filtered view so hidden roles and internal bookkeeping do not leak
    into prompts or fallback decision logic.
    """

    request = dict(request or {})
    seat = int(request.get("seat") or 0)
    role = str(request.get("role") or "")
    players = [dict(player) for player in request.get("players") or [] if isinstance(player, dict)]
    public_players = [
        {
            "seat": int(player.get("seat") or 0),
            "alive": bool(player.get("alive", True)),
            "is_sheriff": bool(player.get("is_sheriff", False)),
            "can_vote": bool(player.get("can_vote", True)),
        }
        for player in players
    ]

    wolf_team: list[int] = []
    if role in {"wolf", "wolf_king"}:
        wolf_team = [
            int(player.get("seat") or 0)
            for player in players
            if player.get("camp") == "wolf"
        ]
    votes = deepcopy(request.get("votes") or [])
    night_summary = deepcopy(request.get("night_summary") or {}) if str(request.get("kind") or "").startswith("night_") else {}

    return {
        "kind": request.get("kind"),
        "seat": seat,
        "role": role,
        "role_name": request.get("role_name"),
        "day": request.get("day", 1),
        "phase": request.get("phase"),
        "user_seat": request.get("user_seat"),
        "sheriff_seat": request.get("sheriff_seat"),
        "target_seats": [int(target) for target in request.get("target_seats") or []],
        "public_log": list(request.get("public_log") or []),
        "public_players": public_players,
        "votes": votes,
        "vote_phase_notes": dict(VOTE_PHASE_NOTES),
        "vote_records": build_vote_records(votes),
        "election": deepcopy(request.get("election") or {}),
        "day_vote": deepcopy(request.get("day_vote") or {}),
        "day_speech_queue": [int(seat) for seat in request.get("day_speech_queue") or []],
        "night_summary": night_summary,
        "persona": deepcopy(request.get("persona") or {}),
        "memory": dict(memory or {}),
        "private_info": {
            "wolf_team": wolf_team,
            **dict(request.get("private_info") or {}),
            "last_memory": dict(memory or {}),
        },
    }
