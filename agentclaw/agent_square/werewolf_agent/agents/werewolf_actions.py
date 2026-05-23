"""Action helpers for Werewolf actor workflows."""

from __future__ import annotations

from typing import Any


ALLOWED_ACTION_KINDS_BY_REQUEST = {
    "night_kill": {"kill"},
    "seer_check": {"check"},
    "guard": {"guard"},
    "witch": {"skip", "witch_save", "witch_poison"},
    "hunter_status": {"hunter_status"},
    "hunter_shot": {"shoot", "skip"},
    "wolf_king_shot": {"shoot", "skip"},
    "sheriff_badge": {"transfer_badge", "destroy_badge"},
    "election_join": {"join_election", "skip_election"},
    "election_speech": {"speak", "self_explode"},
    "election_vote": {"vote", "skip"},
    "election_pk_speech": {"speak", "self_explode"},
    "election_pk_vote": {"vote", "skip"},
    "day_speech": {"speak", "self_explode"},
    "day_order": {"choose_order", "choose_direction"},
    "day_vote": {"vote", "skip"},
    "day_pk_speech": {"speak", "self_explode"},
    "day_pk_vote": {"vote", "skip"},
    "last_words": {"speak"},
}


def fallback_actor_action(actor_view: dict[str, Any]) -> dict[str, Any]:
    """Return a legal placeholder action without strategy or generated content."""

    kind = str(actor_view.get("kind") or "")
    seat = int(actor_view.get("seat") or 0)
    targets = [int(target) for target in actor_view.get("target_seats") or []]

    if kind == "night_kill":
        return {"seat": seat, "kind": "kill", "target_seat": targets[0] if targets else None}
    if kind == "seer_check":
        return {"seat": seat, "kind": "check", "target_seat": targets[0] if targets else None}
    if kind == "guard":
        return {"seat": seat, "kind": "guard", "target_seat": targets[-1] if targets else None}
    if kind == "witch":
        return {"seat": seat, "kind": "skip"}
    if kind == "hunter_status":
        return {"seat": seat, "kind": "hunter_status"}
    if kind in {"hunter_shot", "wolf_king_shot"}:
        return {"seat": seat, "kind": "shoot", "target_seat": targets[0] if targets else None}
    if kind == "sheriff_badge":
        return {
            "seat": seat,
            "kind": "transfer_badge" if targets else "destroy_badge",
            "target_seat": targets[0] if targets else None,
        }
    if kind == "election_join":
        return {"seat": seat, "kind": "skip_election"}
    if kind == "election_speech":
        return {"seat": seat, "kind": "speak", "speech": ""}
    if kind == "election_vote":
        return {"seat": seat, "kind": "vote", "target_seat": targets[0] if targets else None}
    if kind == "election_pk_speech":
        return {"seat": seat, "kind": "speak", "speech": ""}
    if kind == "election_pk_vote":
        return {"seat": seat, "kind": "vote", "target_seat": targets[0] if targets else None}
    if kind == "day_speech":
        return {"seat": seat, "kind": "speak", "speech": ""}
    if kind == "day_order":
        return {"seat": seat, "kind": "choose_direction", "direction": "right"}
    if kind == "day_vote":
        return {"seat": seat, "kind": "vote", "target_seat": targets[0] if targets else None}
    if kind == "day_pk_speech":
        return {"seat": seat, "kind": "speak", "speech": ""}
    if kind == "day_pk_vote":
        return {"seat": seat, "kind": "vote", "target_seat": targets[0] if targets else None}
    if kind == "last_words":
        return {"seat": seat, "kind": "speak", "speech": ""}
    return {"seat": seat, "kind": "skip"}


def normalize_actor_action(actor_view: dict[str, Any], raw_action: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize an actor action and clamp illegal target choices."""

    action = dict(raw_action or {})
    seat = int(actor_view.get("seat") or action.get("seat") or 0)
    action["seat"] = seat
    action["kind"] = str(action.get("kind") or "skip")
    request_kind = str(actor_view.get("kind") or "")
    allowed_kinds = ALLOWED_ACTION_KINDS_BY_REQUEST.get(request_kind)
    if allowed_kinds and action["kind"] not in allowed_kinds:
        action = fallback_actor_action(actor_view)
        action["seat"] = seat

    targets = [int(target) for target in actor_view.get("target_seats") or []]
    target = action.get("target_seat")
    if target is not None:
        try:
            target = int(target)
        except (TypeError, ValueError):
            target = None
    if target is not None and targets and target not in targets:
        target = targets[0]
    if target is not None:
        action["target_seat"] = target
    elif "target_seat" in action:
        action["target_seat"] = None

    if action["kind"] == "speak":
        speech = " ".join(str(action.get("speech") or "").split())
        action["speech"] = speech
    if action["kind"] == "choose_direction":
        direction = str(action.get("direction") or "").lower()
        action["direction"] = direction if direction in {"left", "right"} else "right"

    return action
