"""Core Werewolf rule helpers that are independent from graph routing."""

from __future__ import annotations

from typing import Any

try:
    from .werewolf_state import append_unique
except ImportError:  # pragma: no cover - supports copied template direct import
    from werewolf_state import append_unique  # type: ignore


GOD_ROLES = {"seer", "witch", "hunter", "guard", "idiot"}


def append_identity_review(game: dict[str, Any]) -> None:
    identities = [
        f"{int(item.get('seat') or 0)}号{item.get('role_name')}"
        for item in game.get("players", [])
        if isinstance(item, dict)
    ]
    append_unique(game.setdefault("public_log", []), "身份复盘：" + "、".join(identities))


def finish_game(game: dict[str, Any], winner: str, message: str) -> bool:
    game["winner"] = winner
    game["phase"] = "MODEL_REVIEW"
    game["pending_request"] = None
    game["actor_requests"] = {}
    game["actor_outputs"] = {}
    game["review_pending"] = True
    append_unique(game.setdefault("public_log", []), message)
    return True


def check_win_condition(game: dict[str, Any]) -> bool:
    if game.get("phase") in {"GAME_OVER", "MODEL_REVIEW", "POST_GAME_CHOICE"} and game.get("winner"):
        return True

    alive_players = [
        item for item in game.get("players", [])
        if isinstance(item, dict) and item.get("alive", True)
    ]
    alive_wolves = [item for item in alive_players if item.get("camp") == "wolf"]
    if not alive_wolves:
        return finish_game(game, "good", "所有狼人已出局，好人阵营胜利。")

    alive_villagers = [item for item in alive_players if item.get("role") == "villager"]
    if not alive_villagers:
        return finish_game(game, "wolf", "平民牌已全部出局，狼人阵营屠民胜利。")

    alive_gods = [item for item in alive_players if item.get("role") in GOD_ROLES]
    if not alive_gods:
        return finish_game(game, "wolf", "神职牌已全部出局，狼人阵营屠神胜利。")

    return False


_append_identity_review = append_identity_review
_finish_game = finish_game
_check_win_condition = check_win_condition
