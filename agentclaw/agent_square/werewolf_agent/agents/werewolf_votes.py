"""Voting helpers shared by Werewolf election and day phases."""

from __future__ import annotations

from typing import Any

try:
    from .werewolf_state import player
except ImportError:  # pragma: no cover - supports copied template direct import
    from werewolf_state import player  # type: ignore


def can_player_vote(game: dict[str, Any], seat: int) -> bool:
    item = player(game, seat)
    return bool(item.get("alive", True)) and bool(item.get("can_vote", True))


def vote_matches(game: dict[str, Any], vote: dict[str, Any], phase: str) -> bool:
    if vote.get("phase") != phase:
        return False
    if phase not in {"day_vote", "day_pk_vote"}:
        return True
    vote_day = int(vote.get("day") or 1)
    current_day = int(game.get("day") or 1)
    return vote_day == current_day


def has_vote(game: dict[str, Any], seat: int, phase: str) -> bool:
    return any(
        int(vote.get("from") or 0) == int(seat) and vote_matches(game, vote, phase)
        for vote in game.get("votes", [])
        if isinstance(vote, dict)
    )


def record_vote(game: dict[str, Any], seat: int, target: int, phase: str) -> None:
    if not can_player_vote(game, seat):
        return
    votes = [
        vote
        for vote in game.get("votes", [])
        if not (
            isinstance(vote, dict)
            and int(vote.get("from") or 0) == int(seat)
            and vote_matches(game, vote, phase)
        )
    ]
    record = {"from": int(seat), "to": int(target), "phase": phase}
    if phase in {"day_vote", "day_pk_vote"}:
        record["day"] = int(game.get("day") or 1)
    votes.append(record)
    game["votes"] = votes


def vote_winners(game: dict[str, Any], phase: str, candidates: list[int]) -> list[int]:
    counts = {seat: 0 for seat in candidates}
    for vote in game.get("votes", []):
        if not isinstance(vote, dict) or not vote_matches(game, vote, phase):
            continue
        target = int(vote.get("to") or 0)
        if target in counts:
            counts[target] += 1

    top_count = max(counts.values()) if counts else 0
    return [seat for seat, count in counts.items() if count == top_count and count > 0]


_can_player_vote = can_player_vote
_vote_matches = vote_matches
_has_vote = has_vote
_record_vote = record_vote
_vote_winners = vote_winners
