"""Input parsing helpers for the Werewolf main workflow."""

from __future__ import annotations

import json
import re


_NEGATIVE_MARKERS = ("不", "别", "无", "弃", "过")
_ELECTION_SKIP_MARKERS = ("不上", "不警", "下警", "退水")
_ELECTION_JOIN_MARKERS = ("上警", "竞选", "警徽")
_BADGE_DESTROY_MARKERS = ("撕", "毁")
_WITCH_SAVE_MARKERS = ("救", "解药")
_WITCH_POISON_MARKERS = ("毒", "毒药")
_LEFT_ORDER_MARKERS = ("警左", "左边", "左置位", "逆时针")
_RIGHT_ORDER_MARKERS = ("警右", "右边", "右置位", "顺时针")
_WITHDRAW_ACTIONS = {"withdraw_election"}
_SELF_EXPLODE_ACTIONS = {"self_explode"}


def action_kind_from_text(text: str) -> str:
    try:
        data = json.loads(text)
    except Exception:
        return ""
    if not isinstance(data, dict):
        return ""
    kind = data.get("kind")
    return str(kind or "")


def target_from_text(text: str, targets: list[int]) -> int | None:
    for match in re.findall(r"\d+", text):
        seat = int(match)
        if seat in targets:
            return seat
    return targets[0] if targets else None


def parse_election_choice(text: str) -> str:
    if any(marker in text for marker in _ELECTION_SKIP_MARKERS):
        return "skip"
    if any(marker in text for marker in _ELECTION_JOIN_MARKERS):
        return "join"
    return "join"


def should_skip_shot(text: str) -> bool:
    return any(marker in text for marker in _NEGATIVE_MARKERS)


def should_destroy_badge(text: str) -> bool:
    return any(marker in text for marker in _BADGE_DESTROY_MARKERS)


def should_withdraw_election(text: str) -> bool:
    return action_kind_from_text(text) in _WITHDRAW_ACTIONS


def should_self_explode(text: str) -> bool:
    return action_kind_from_text(text) in _SELF_EXPLODE_ACTIONS


def parse_day_order_direction(text: str) -> str | None:
    if any(marker in text for marker in _LEFT_ORDER_MARKERS):
        return "left"
    if any(marker in text for marker in _RIGHT_ORDER_MARKERS):
        return "right"
    return None


def parse_witch_action(
    text: str,
    *,
    target: int | None,
    can_save: bool,
    can_poison: bool,
) -> tuple[str, int | None]:
    if can_save and any(marker in text for marker in _WITCH_SAVE_MARKERS):
        return "save", None
    if can_poison and target and any(marker in text for marker in _WITCH_POISON_MARKERS):
        return "poison", target
    return "skip", None


_target_from_text = target_from_text
_action_kind_from_text = action_kind_from_text
_parse_election_choice = parse_election_choice
_should_skip_shot = should_skip_shot
_should_destroy_badge = should_destroy_badge
_should_withdraw_election = should_withdraw_election
_should_self_explode = should_self_explode
_parse_day_order_direction = parse_day_order_direction
_parse_witch_action = parse_witch_action
