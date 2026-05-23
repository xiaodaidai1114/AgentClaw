"""Shared state helpers for the AI Werewolf Claw App."""

from __future__ import annotations

import random
from copy import deepcopy
from typing import Any

SESSION_STATE_KEY = "werewolf_session"

ROLE_NAMES = {
    "wolf": "狼人",
    "wolf_king": "狼王",
    "seer": "预言家",
    "witch": "女巫",
    "hunter": "猎人",
    "guard": "守卫",
    "idiot": "白痴",
    "villager": "平民",
}

ROLE_CAMPS = {
    "wolf": "wolf",
    "wolf_king": "wolf",
    "seer": "good",
    "witch": "good",
    "hunter": "good",
    "guard": "good",
    "idiot": "good",
    "villager": "good",
}

DEFAULT_ROLES = [
    "wolf",
    "wolf",
    "wolf",
    "wolf_king",
    "seer",
    "witch",
    "hunter",
    "guard",
    "idiot",
    "villager",
    "villager",
    "villager",
]


def empty_game() -> dict[str, Any]:
    return {
        "phase": "LOBBY",
        "day": 0,
        "seed": None,
        "players": [],
        "user_seat": None,
        "user_spectating": False,
        "post_death_return_phase": "",
        "public_log": [],
        "stream_log_index": 0,
        "private_log": {},
        "pending_request": None,
        "night": {},
        "seer_private_checks": {},
        "election": {
            "choices": {},
            "candidates": [],
            "voters": [],
            "speech_queue": [],
            "pk_candidates": [],
            "pk_speech_queue": [],
            "pk_voters": [],
        },
        "day_speech_queue": [],
        "day_vote": {
            "pk_candidates": [],
            "pk_speech_queue": [],
            "pk_voters": [],
        },
        "actors": {},
        "actor_requests": {},
        "actor_outputs": {},
        "dead": [],
        "death_queue": [],
        "death_causes": {},
        "last_words_queue": [],
        "death_followup_pending": False,
        "after_last_words_phase": "DAY_END",
        "sheriff_check_queue": [],
        "hunter_check_queue": [],
        "votes": [],
        "sheriff_seat": None,
        "guard_last_target": None,
        "witch_save_available": True,
        "witch_poison_available": True,
        "winner": "",
        "review_pending": False,
        "model_review": "",
    }


def coerce_game(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    game = empty_game()
    for key, value in raw.items():
        if key in game:
            game[key] = deepcopy(value)
    if not isinstance(game.get("public_log"), list):
        game["public_log"] = []
    if not isinstance(game.get("stream_log_index"), int):
        game["stream_log_index"] = 0
    if not isinstance(game.get("private_log"), dict):
        game["private_log"] = {}
    if not isinstance(game.get("actors"), dict):
        game["actors"] = {}
    if not isinstance(game.get("actor_requests"), dict):
        game["actor_requests"] = {}
    if not isinstance(game.get("actor_outputs"), dict):
        game["actor_outputs"] = {}
    if not isinstance(game.get("election"), dict):
        game["election"] = empty_game()["election"]
    for key, default in empty_game()["election"].items():
        game["election"].setdefault(key, deepcopy(default))
    if not isinstance(game.get("day_vote"), dict):
        game["day_vote"] = empty_game()["day_vote"]
    for key, default in empty_game()["day_vote"].items():
        game["day_vote"].setdefault(key, deepcopy(default))
    return game


def game_from_state(state: dict[str, Any]) -> dict[str, Any]:
    return coerce_game(state.get(SESSION_STATE_KEY) or state.get("session"))


def player(game: dict[str, Any], seat: int) -> dict[str, Any]:
    for item in game.get("players", []):
        if int(item.get("seat") or 0) == int(seat):
            return item
    raise KeyError(f"unknown seat: {seat}")


def alive_seats(game: dict[str, Any]) -> list[int]:
    return [
        int(item["seat"])
        for item in game.get("players", [])
        if item.get("alive", True)
    ]


def seat_key(seat: int | str) -> str:
    return f"p{int(seat)}"


def append_unique(lines: list[str], text: str) -> None:
    if text and text not in lines:
        lines.append(text)


def new_game(state: dict[str, Any]) -> dict[str, Any]:
    seed = state.get("debug_seed")
    if seed is None:
        seed = random.SystemRandom().randint(1, 2**63 - 1)
    rng = random.Random(seed)
    roles = list(DEFAULT_ROLES)
    rng.shuffle(roles)

    user_seat = int(state.get("debug_user_seat") or rng.randint(1, 12))
    user_role = state.get("debug_user_role")
    if user_role in ROLE_NAMES:
        try:
            role_index = roles.index(str(user_role))
            roles[user_seat - 1], roles[role_index] = roles[role_index], roles[user_seat - 1]
        except ValueError:
            pass

    players = []
    for seat, role in enumerate(roles, start=1):
        players.append({
            "seat": seat,
            "name": f"{seat}号",
            "role": role,
            "role_name": ROLE_NAMES[role],
            "camp": ROLE_CAMPS[role],
            "alive": True,
            "is_user": seat == user_seat,
            "can_vote": True,
        })

    game = empty_game()
    game["phase"] = "NIGHT_WOLF"
    game["day"] = 1
    game["seed"] = seed
    game["players"] = players
    game["user_seat"] = user_seat
    private_lines = [f"身份已发放。你是 {user_seat} 号，身份是 {ROLE_NAMES[roles[user_seat - 1]]}。"]
    if roles[user_seat - 1] in {"wolf", "wolf_king"}:
        teammates = [
            seat
            for seat, role in enumerate(roles, start=1)
            if seat != user_seat and ROLE_CAMPS[role] == "wolf"
        ]
        private_lines.append(f"你的狼队友：{format_seats(teammates)}。")
    game["private_log"] = {str(user_seat): private_lines}
    game["public_log"] = ["天黑请闭眼。"]
    game["actors"] = {
        seat_key(item["seat"]): {
            "seat": item["seat"],
            "memory": {},
            "persona": {},
        }
        for item in players
        if item["seat"] != user_seat
    }
    return game


def role_seats(game: dict[str, Any], *roles: str) -> list[int]:
    role_set = set(roles)
    return [
        int(item["seat"])
        for item in game.get("players", [])
        if item.get("alive", True) and item.get("role") in role_set
    ]


def format_seats(seats: list[int]) -> str:
    return "、".join(f"{seat}号" for seat in seats) if seats else "无"


# Backward-compatible private aliases for tests or imported template code that
# still expects the earlier single-file helper names.
_empty_game = empty_game
_coerce_game = coerce_game
_game_from_state = game_from_state
_player = player
_alive_seats = alive_seats
_seat_key = seat_key
_append_unique = append_unique
_new_game = new_game
_role_seats = role_seats
_format_seats = format_seats
