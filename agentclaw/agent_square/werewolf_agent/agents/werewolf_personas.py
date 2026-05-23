"""Persona generation helpers for Werewolf AI seats."""

from __future__ import annotations

import json
from typing import Any


PERSONA_FIELDS = ("temperament", "speech_style", "strategic_bias", "table_habits")
PERSONA_PROMPT_KEY = "werewolf_persona_generation"


def _seat_key(seat: int | str) -> str:
    return f"p{int(seat)}"


def _alive_seats(game: dict[str, Any]) -> list[int]:
    return [
        int(item["seat"])
        for item in game.get("players", [])
        if item.get("alive", True)
    ]


def _player(game: dict[str, Any], seat: int) -> dict[str, Any]:
    for item in game.get("players", []):
        if int(item.get("seat") or 0) == int(seat):
            return item
    return {}


def fallback_persona(game: dict[str, Any], seat: int) -> dict[str, str]:
    return {}


def ensure_actor_personas(game: dict[str, Any]) -> None:
    user_seat = int(game.get("user_seat") or 0)
    actors = game.setdefault("actors", {})
    for seat in _alive_seats(game):
        if seat == user_seat:
            continue
        actor = actors.setdefault(_seat_key(seat), {"seat": seat, "memory": {}})
        actor.setdefault("seat", seat)
        actor.setdefault("memory", {})
        persona = actor.get("persona")
        if not isinstance(persona, dict):
            actor["persona"] = {}


def build_persona_generation_prompt(game: dict[str, Any], prompt_manager=None) -> str:
    seats = [
        {
            "actor_id": _seat_key(seat),
            "seat": seat,
            "role_name": _player(game, seat).get("role_name"),
        }
        for seat in _alive_seats(game)
        if seat != int(game.get("user_seat") or 0)
    ]
    variables = {"seats_json": json.dumps(seats, ensure_ascii=False)}
    if prompt_manager is None:
        return "{@werewolf_persona_generation}\n\nseats_json:\n" + variables["seats_json"]
    return prompt_manager.get_prompt(PERSONA_PROMPT_KEY, variables)


def parse_persona_response(text: str) -> dict[str, dict[str, str]]:
    try:
        data = json.loads(text)
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    parsed: dict[str, dict[str, str]] = {}
    for actor_id, raw in data.items():
        if not isinstance(actor_id, str) or not isinstance(raw, dict):
            continue
        persona = {
            field: " ".join(str(raw.get(field) or "").split())
            for field in PERSONA_FIELDS
        }
        if all(persona.values()):
            parsed[actor_id] = persona
    return parsed


async def generate_personas_node(state: dict[str, Any], context) -> dict[str, Any]:
    try:
        from .werewolf_state import SESSION_STATE_KEY, game_from_state
    except ImportError:  # pragma: no cover
        from werewolf_state import SESSION_STATE_KEY, game_from_state  # type: ignore

    game = game_from_state(state)
    ensure_actor_personas(game)
    manager = getattr(context, "llm_manager", None)
    if manager is not None:
        try:
            result = await manager.invoke([
                {
                    "role": "user",
                    "content": build_persona_generation_prompt(
                        game,
                        getattr(context, "prompt_manager", None),
                    ),
                }
            ])
            content = result.content if hasattr(result, "content") else str(result)
            generated = parse_persona_response(content)
            for actor_id, persona in generated.items():
                if actor_id in game.get("actors", {}):
                    game["actors"][actor_id]["persona"] = persona
        except Exception:
            pass
    ensure_actor_personas(game)
    return {
        "session": game,
        SESSION_STATE_KEY: game,
        "actors": game.get("actors", {}),
    }


_fallback_persona = fallback_persona
_ensure_actor_personas = ensure_actor_personas
_generate_personas_node = generate_personas_node
