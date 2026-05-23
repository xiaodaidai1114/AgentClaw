"""Main Werewolf state-machine helpers.

The main workflow owns deterministic flow control. Actor child workflows only
return decisions; this module applies those decisions to game state.
"""

from __future__ import annotations

import random
import json
from copy import deepcopy
from typing import Any

try:
    from .werewolf_input import (
        parse_election_choice,
        parse_witch_action,
        parse_day_order_direction,
        should_destroy_badge,
        should_self_explode,
        should_skip_shot,
        should_withdraw_election,
        target_from_text,
    )
    from .werewolf_rules import append_identity_review, check_win_condition, finish_game
    from .werewolf_state import (
        alive_seats,
        append_unique,
        format_seats,
        player,
        role_seats,
        seat_key,
    )
    from .werewolf_votes import can_player_vote, has_vote, record_vote, vote_matches, vote_winners
except ImportError:  # pragma: no cover - supports copied template direct import
    from werewolf_input import (  # type: ignore
        parse_election_choice,
        parse_witch_action,
        parse_day_order_direction,
        should_destroy_badge,
        should_self_explode,
        should_skip_shot,
        should_withdraw_election,
        target_from_text,
    )
    from werewolf_rules import append_identity_review, check_win_condition, finish_game  # type: ignore
    from werewolf_state import (  # type: ignore
        alive_seats,
        append_unique,
        format_seats,
        player,
        role_seats,
        seat_key,
    )
    from werewolf_votes import can_player_vote, has_vote, record_vote, vote_matches, vote_winners  # type: ignore


def build_actor_request(game: dict[str, Any], seat: int, kind: str, targets: list[int]) -> dict[str, Any]:
    item = player(game, seat)
    actor_state = game.get("actors", {}).get(seat_key(seat), {})
    request = {
        "kind": kind,
        "seat": seat,
        "role": item.get("role"),
        "role_name": item.get("role_name"),
        "persona": deepcopy(actor_state.get("persona") or {}),
        "day": game.get("day", 1),
        "user_seat": game.get("user_seat"),
        "target_seats": targets,
        "players": deepcopy(game.get("players", [])),
        "public_log": list(game.get("public_log", [])[-20:]),
        "phase": game.get("phase"),
        "sheriff_seat": game.get("sheriff_seat"),
        "votes": list(game.get("votes", [])),
        "day_speech_queue": list(game.get("day_speech_queue") or []),
        "day_vote": deepcopy(game.get("day_vote", {})),
        "night_summary": deepcopy(game.get("night", {})),
        "election": deepcopy(game.get("election", {})),
    }
    if kind == "witch":
        request["private_info"] = witch_private_info(game)
    if kind == "hunter_status":
        request["private_info"] = hunter_status_private_info(game, seat)
    private_info = dict(request.get("private_info") or {})
    if item.get("role") == "seer":
        private_info["seer_checks"] = list(game.get("seer_private_checks", {}).get(str(seat), []))
    if item.get("camp") == "wolf":
        private_info["wolf_team"] = [
            int(other.get("seat") or 0)
            for other in game.get("players", [])
            if other.get("camp") == "wolf"
        ]
    if private_info:
        request["private_info"] = private_info
    return request


def night_targets(game: dict[str, Any], kind: str, seat: int) -> list[int]:
    if kind == "night_kill":
        return [
            target
            for target in alive_seats(game)
            if player(game, target).get("camp") != "wolf"
        ]
    if kind in {"seer_check", "witch"}:
        if kind == "witch":
            return witch_targets(game)
        return [target for target in alive_seats(game) if target != seat]
    if kind == "guard":
        last_target = int(game.get("guard_last_target") or 0)
        return [target for target in alive_seats(game) if target != last_target]
    return []


def witch_private_info(game: dict[str, Any]) -> dict[str, Any]:
    wolf_target = game.get("night", {}).get("wolf_target")
    night_kill_target = int(wolf_target) if wolf_target else None
    can_save = bool(game.get("witch_save_available", True)) and bool(wolf_target)
    return {
        "night_kill_target": night_kill_target,
        "witch_save_target": night_kill_target,
        "witch_can_save": can_save,
        "witch_can_poison": bool(game.get("witch_poison_available", True)),
    }


def witch_targets(game: dict[str, Any]) -> list[int]:
    targets: list[int] = []
    info = witch_private_info(game)
    if info["witch_can_save"] and info["witch_save_target"]:
        targets.append(int(info["witch_save_target"]))
    if info["witch_can_poison"]:
        targets.extend(seat for seat in alive_seats(game) if seat not in targets)
    return targets


def witch_action_targets(game: dict[str, Any]) -> dict[str, list[int]]:
    info = witch_private_info(game)
    return {
        "save": [int(info["witch_save_target"])] if info["witch_can_save"] and info["witch_save_target"] else [],
        "poison": alive_seats(game) if info["witch_can_poison"] else [],
    }


def hunter_status_private_info(game: dict[str, Any], seat: int) -> dict[str, Any]:
    poisoned = int(game.get("night", {}).get("witch_poison_target") or 0) == int(seat)
    info = {"hunter_can_shoot": not poisoned}
    if poisoned:
        info["hunter_cannot_shoot_reason"] = "poison"
    return info


def record_seer_check(game: dict[str, Any], seat: int, target: int) -> None:
    target_player = player(game, target)
    alignment = "wolf" if target_player.get("camp") == "wolf" else "good"
    result_name = "狼人" if alignment == "wolf" else "好人"
    day = int(game.get("day") or 1)
    game.setdefault("night", {}).setdefault("seer_checks", {})[str(seat)] = int(target)
    game.setdefault("seer_private_checks", {}).setdefault(str(seat), []).append({
        "day": day,
        "target_seat": int(target),
        "alignment": alignment,
        "result_name": result_name,
    })
    game.setdefault("private_log", {}).setdefault(str(seat), []).append(
        f"第{day}晚查验：{target}号是{result_name}。"
    )


def set_user_request(game: dict[str, Any], kind: str, seat: int, targets: list[int], prompt: str) -> None:
    if game.get("user_spectating"):
        game["pending_request"] = None
        game["actor_requests"] = {}
        return
    if kind == "witch":
        info = witch_private_info(game)
        notes = []
        if info["night_kill_target"]:
            notes.append(f"昨夜被刀目标：{info['night_kill_target']}号")
        if info["night_kill_target"] and not info["witch_can_save"]:
            notes.append("解药已用")
        if not info["witch_can_poison"]:
            notes.append("毒药已用")
        if notes:
            prompt = f"{prompt}（{'；'.join(notes)}）"
    game["pending_request"] = {
        "kind": kind,
        "actor": "user",
        "seat": seat,
        "target_seats": targets,
        "prompt": prompt,
    }
    if kind == "witch":
        game["pending_request"]["private_info"] = witch_private_info(game)
        game["pending_request"]["action_targets"] = witch_action_targets(game)
    game["actor_requests"] = {}


def prepare_night_actor_requests(game: dict[str, Any], role: str, kind: str) -> bool:
    requests: dict[str, Any] = {}
    user_seat = int(game.get("user_seat") or 0)
    roles = ("wolf", "wolf_king") if role == "wolf" else (role,)
    seats = [seat for seat in role_seats(game, *roles) if seat != user_seat]
    if role == "wolf":
        seats = seats[:1]
    for seat in seats:
        requests[seat_key(seat)] = build_actor_request(
            game,
            seat,
            kind,
            night_targets(game, kind, seat),
        )

    game["actor_requests"] = requests
    game["actor_outputs"] = {}
    return bool(requests)


def advance_night_stage(
    game: dict[str, Any],
    *,
    phase: str,
    user_roles: set[str],
    ai_role: str,
    request_kind: str,
    next_phase: str,
    prompt: str,
) -> str:
    if game.get("phase") != phase:
        return "advance"

    user_seat = int(game.get("user_seat") or 0)
    user_role = player(game, user_seat).get("role") if user_seat else ""
    if user_role in user_roles and not game.get("user_spectating"):
        set_user_request(
            game,
            request_kind,
            user_seat,
            night_targets(game, request_kind, user_seat),
            prompt,
        )
        return "render"

    if prepare_night_actor_requests(game, ai_role, request_kind):
        return "actors"

    game["phase"] = next_phase
    return "advance"


def prepare_election_ai_choices(game: dict[str, Any]) -> bool:
    requests = {}
    user_seat = int(game.get("user_seat") or 0)
    for seat in alive_seats(game):
        if seat == user_seat:
            continue
        requests[seat_key(seat)] = build_actor_request(
            game,
            seat,
            "election_join",
            [],
        )
    game["actor_requests"] = requests
    game["actor_outputs"] = {}
    return bool(requests)


def prepare_current_ai_speech(game: dict[str, Any]) -> bool:
    queue = list(game.get("election", {}).get("speech_queue") or [])
    if not queue:
        return False
    seat = int(queue[0])
    if seat == int(game.get("user_seat") or 0) and not game.get("user_spectating"):
        game["pending_request"] = {
            "kind": "election_speech",
            "actor": "user",
            "seat": seat,
            "prompt": "轮到你发表警上发言。",
        }
        game["actor_requests"] = {}
        return False
    game["actor_requests"] = {
        seat_key(seat): build_actor_request(game, seat, "election_speech", [])
    }
    game["actor_outputs"] = {}
    return True


def set_user_election_vote_request(game: dict[str, Any]) -> None:
    targets = [int(seat) for seat in game.get("election", {}).get("candidates") or []]
    game["pending_request"] = {
        "kind": "election_vote",
        "actor": "user",
        "seat": game["user_seat"],
        "target_seats": targets,
        "prompt": f"请投票选择警长：{format_seats(targets)}。",
    }
    game["actor_requests"] = {}


def prepare_election_ai_votes(game: dict[str, Any]) -> bool:
    election = game.get("election", {})
    targets = [int(seat) for seat in election.get("candidates") or []]
    user_seat = int(game.get("user_seat") or 0)
    requests: dict[str, Any] = {}
    for seat in [int(item) for item in election.get("voters") or []]:
        if seat == user_seat or has_vote(game, seat, "election_vote"):
            continue
        requests[seat_key(seat)] = build_actor_request(game, seat, "election_vote", targets)
    game["actor_requests"] = requests
    game["actor_outputs"] = {}
    return bool(requests)


def prepare_current_election_pk_speech(game: dict[str, Any]) -> bool:
    queue = list(game.get("election", {}).get("pk_speech_queue") or [])
    if not queue:
        return False
    seat = int(queue[0])
    if seat == int(game.get("user_seat") or 0) and not game.get("user_spectating"):
        game["pending_request"] = {
            "kind": "election_pk_speech",
            "actor": "user",
            "seat": seat,
            "prompt": "你进入警长PK台。请发表PK发言。",
        }
        game["actor_requests"] = {}
        return False
    game["actor_requests"] = {
        seat_key(seat): build_actor_request(game, seat, "election_pk_speech", [])
    }
    game["actor_outputs"] = {}
    return True


def set_user_election_pk_vote_request(game: dict[str, Any]) -> None:
    targets = [int(seat) for seat in game.get("election", {}).get("pk_candidates") or []]
    game["pending_request"] = {
        "kind": "election_pk_vote",
        "actor": "user",
        "seat": game["user_seat"],
        "target_seats": targets,
        "prompt": f"请在警长PK玩家中投票：{format_seats(targets)}。",
    }
    game["actor_requests"] = {}


def prepare_election_pk_ai_votes(game: dict[str, Any]) -> bool:
    election = game.get("election", {})
    targets = [int(seat) for seat in election.get("pk_candidates") or []]
    user_seat = int(game.get("user_seat") or 0)
    requests: dict[str, Any] = {}
    for seat in [int(item) for item in election.get("pk_voters") or []]:
        if seat == user_seat or has_vote(game, seat, "election_pk_vote"):
            continue
        requests[seat_key(seat)] = build_actor_request(game, seat, "election_pk_vote", targets)
    game["actor_requests"] = requests
    game["actor_outputs"] = {}
    return bool(requests)


def build_day_speech_order(game: dict[str, Any]) -> None:
    alive = alive_seats(game)
    sheriff = game.get("sheriff_seat")
    sheriff_seat = int(sheriff) if sheriff else 0
    if sheriff_seat in alive and len(alive) > 1:
        targets = [seat for seat in alive if seat != sheriff_seat]
        if sheriff_seat == int(game.get("user_seat") or 0) and not game.get("user_spectating"):
            game["pending_request"] = {
                "kind": "day_order",
                "actor": "user",
                "seat": sheriff_seat,
                "target_seats": targets,
                "prompt": f"你是警长，请选择首位发言玩家，警长最后归票：{format_seats(targets)}。",
            }
            game["actor_requests"] = {}
            game["phase"] = "DAY_ORDER"
            return
        game["actor_requests"] = {
            seat_key(sheriff_seat): build_actor_request(game, sheriff_seat, "day_order", targets)
        }
        game["actor_outputs"] = {}
        game["phase"] = "DAY_ORDER_AI"
    else:
        speech_order = alive
        append_unique(game.setdefault("public_log", []), "本轮没有警长，按座位顺序发言。")
        game["day_speech_queue"] = speech_order
        game["phase"] = "DAY_NEXT_SPEECH"


def apply_day_speech_order(game: dict[str, Any], first_seat: int | None) -> None:
    alive = alive_seats(game)
    sheriff_seat = int(game.get("sheriff_seat") or 0)
    candidates = [seat for seat in alive if seat != sheriff_seat]
    first = int(first_seat) if first_seat in candidates else (candidates[0] if candidates else sheriff_seat)
    ordered = [seat for seat in range(first, 13) if seat in candidates]
    ordered.extend(seat for seat in range(1, first) if seat in candidates)
    if sheriff_seat in alive:
        ordered.append(sheriff_seat)
        append_unique(game.setdefault("public_log", []), f"{sheriff_seat}号警长决定从{first}号开始发言，警长最后归票。")
    else:
        append_unique(game.setdefault("public_log", []), f"本轮从{first}号开始发言。")
    game["day_speech_queue"] = ordered
    game["phase"] = "DAY_NEXT_SPEECH"


def apply_day_speech_direction(game: dict[str, Any], direction: str) -> None:
    alive = alive_seats(game)
    sheriff_seat = int(game.get("sheriff_seat") or 0)
    if sheriff_seat not in alive:
        apply_day_speech_order(game, None)
        return

    if direction == "left":
        ordered = [
            seat
            for offset in range(1, 12)
            for seat in [((sheriff_seat - offset - 1) % 12) + 1]
            if seat in alive and seat != sheriff_seat
        ]
        label = "警左"
    else:
        ordered = [
            seat
            for offset in range(1, 12)
            for seat in [((sheriff_seat + offset - 1) % 12) + 1]
            if seat in alive and seat != sheriff_seat
        ]
        label = "警右"

    ordered.append(sheriff_seat)
    game["day_speech_queue"] = ordered
    game["phase"] = "DAY_NEXT_SPEECH"
    append_unique(game.setdefault("public_log", []), f"{sheriff_seat}号警长选择{label}发言，警长最后归票。")


def can_self_explode(game: dict[str, Any], seat: int) -> bool:
    return str(player(game, seat).get("role") or "") in {"wolf", "wolf_king"}


def apply_self_explosion(game: dict[str, Any], seat: int, speech: str = "") -> None:
    item = player(game, seat)
    role_name = str(item.get("role_name") or "狼人")
    was_sheriff = int(game.get("sheriff_seat") or 0) == int(seat)
    item["alive"] = False
    if seat not in game.setdefault("dead", []):
        game["dead"].append(seat)
    if speech:
        append_unique(game.setdefault("public_log", []), f"{seat}号：{speech}")
    if was_sheriff:
        for player_item in game.get("players", []):
            player_item["is_sheriff"] = False
        game["sheriff_seat"] = None
        append_unique(game.setdefault("public_log", []), f"{seat}号警长自爆，警徽撕毁。")
    append_unique(game.setdefault("public_log", []), f"{seat}号{role_name}自爆，白天立即结束，进入黑夜。")
    game["day_speech_queue"] = []
    game.setdefault("election", {})["speech_queue"] = []
    game.setdefault("election", {})["pk_speech_queue"] = []
    game.setdefault("day_vote", {})["pk_speech_queue"] = []
    game["last_words_queue"] = [int(seat)]
    game["after_last_words_phase"] = "DAY_END"
    game["sheriff_check_queue"] = []
    game["hunter_check_queue"] = []
    game["pending_request"] = None
    game["actor_requests"] = {}
    game["actor_outputs"] = {}
    game["phase"] = "LAST_WORDS_NEXT"


def user_is_dead(game: dict[str, Any]) -> bool:
    user_seat = int(game.get("user_seat") or 0)
    if not user_seat:
        return False
    return not bool(player(game, user_seat).get("alive", True))


def mark_post_death_choice_if_needed(game: dict[str, Any], return_phase: str) -> None:
    if not user_is_dead(game) or game.get("user_spectating") or game.get("post_death_choice_done"):
        return
    game["post_death_return_phase"] = return_phase
    game["post_death_choice_pending"] = True


def set_post_death_choice_request(game: dict[str, Any]) -> None:
    game["pending_request"] = {
        "kind": "post_death_choice",
        "actor": "user",
        "seat": int(game.get("user_seat") or 0),
        "target_seats": [],
        "prompt": "你已出局。可以选择继续旁观，或结束游戏并查看身份复盘。",
    }
    game["actor_requests"] = {}
    game["actor_outputs"] = {}
    game["phase"] = "POST_DEATH_CHOICE"


def should_end_after_death(text: str) -> bool:
    lowered = text.strip().lower()
    return any(token in lowered for token in ("结束", "复盘", "不旁观", "退出", "end", "stop"))


def request_model_review(game: dict[str, Any], message: str) -> None:
    game["winner"] = "ended_by_user"
    game["phase"] = "MODEL_REVIEW"
    game["pending_request"] = None
    game["actor_requests"] = {}
    game["actor_outputs"] = {}
    game["review_pending"] = True
    append_unique(game.setdefault("public_log", []), message)


def set_post_game_choice_request(game: dict[str, Any]) -> None:
    game["pending_request"] = {
        "kind": "post_game_choice",
        "actor": "user",
        "seat": int(game.get("user_seat") or 0),
        "target_seats": [],
        "prompt": "复盘已生成。是否开启下一轮？",
    }
    game["phase"] = "POST_GAME_CHOICE"


def should_start_next_game(text: str) -> bool:
    lowered = text.strip().lower()
    return any(token in lowered for token in ("下一轮", "再来", "开", "开始", "new", "again", "start"))


def review_round_events(game: dict[str, Any]) -> list[str]:
    events: list[str] = []
    current_day = 1
    current_part = "夜"
    for raw_line in game.get("public_log", []):
        line = str(raw_line).strip()
        if not line or review_should_skip_line(line):
            continue
        if "白天结束，进入下一晚" in line:
            current_day += 1
            current_part = "夜"
        elif "天亮了" in line:
            current_part = "天"
        elif "天黑请闭眼" in line:
            current_part = "夜"
        if not review_is_key_event(line):
            continue
        events.append(f"第{current_day}{current_part}：{review_compact_line(line)}")
    return events


def review_should_skip_line(line: str) -> bool:
    if "玩家开始" in line and line.endswith("发言："):
        return True
    prefix, _, body = line.partition("：")
    if prefix.endswith("号") and prefix[:-1].isdigit():
        return bool(body)
    return False


def review_is_key_event(line: str) -> bool:
    keywords = (
        "天黑请闭眼",
        "天亮了",
        "平安夜",
        "昨夜死亡",
        "无人出局",
        "放逐出局",
        "出局玩家",
        "警长",
        "放逐投票",
        "投票结果",
        "票型",
        "平票",
        "退水",
        "自爆",
        "翻牌",
        "开枪",
        "被毒",
        "胜利",
        "身份复盘",
        "白天结束",
        "玩家选择结束游戏",
    )
    return any(keyword in line for keyword in keywords)


def review_compact_line(line: str) -> str:
    limit = 120
    return line if len(line) <= limit else line[:limit] + "..."


def review_context(game: dict[str, Any]) -> str:
    players = [
        {
            "seat": int(item.get("seat") or 0),
            "role": item.get("role_name"),
            "camp": item.get("camp"),
            "alive": bool(item.get("alive", True)),
        }
        for item in game.get("players", [])
        if isinstance(item, dict)
    ]
    payload = {
        "winner": game.get("winner") or "",
        "day": int(game.get("day") or 0),
        "sheriff_seat": game.get("sheriff_seat"),
        "user_seat": game.get("user_seat"),
        "players": players,
        "votes": game.get("votes", [])[-40:],
        "round_events": review_round_events(game),
        "public_log": [
            review_compact_line(str(line))
            for line in game.get("public_log", [])[-40:]
            if not review_should_skip_line(str(line)) and review_is_key_event(str(line))
        ],
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)


def handle_post_death_choice(game: dict[str, Any], user_input: str) -> None:
    game["pending_request"] = None
    game["post_death_choice_pending"] = False
    game["post_death_choice_done"] = True
    if should_end_after_death(user_input):
        request_model_review(game, "玩家选择结束游戏，进入模型复盘。")
        return
    game["user_spectating"] = True
    append_unique(game.setdefault("public_log", []), "你已选择继续旁观，后续流程将不再等待你的行动。")
    game["phase"] = str(game.get("post_death_return_phase") or game.get("after_last_words_phase") or "DAY_END")


def prepare_current_day_speech(game: dict[str, Any]) -> bool:
    queue = list(game.get("day_speech_queue") or [])
    if not queue:
        return False
    seat = int(queue[0])
    if seat == int(game.get("user_seat") or 0) and not game.get("user_spectating"):
        game["pending_request"] = {
            "kind": "day_speech",
            "actor": "user",
            "seat": seat,
            "prompt": "轮到你发表白天发言。",
        }
        game["actor_requests"] = {}
        return False
    game["actor_requests"] = {
        seat_key(seat): build_actor_request(game, seat, "day_speech", [])
    }
    game["actor_outputs"] = {}
    return True


def set_user_day_vote_request(game: dict[str, Any]) -> None:
    user_seat = int(game.get("user_seat") or 0)
    targets = [seat for seat in alive_seats(game) if seat != user_seat]
    game["pending_request"] = {
        "kind": "day_vote",
        "actor": "user",
        "seat": user_seat,
        "target_seats": targets,
        "prompt": f"请投票放逐一名玩家：{format_seats(targets)}。",
    }
    game["actor_requests"] = {}


def prepare_day_ai_votes(game: dict[str, Any]) -> bool:
    user_seat = int(game.get("user_seat") or 0)
    requests: dict[str, Any] = {}
    for seat in alive_seats(game):
        if seat == user_seat or not can_player_vote(game, seat) or has_vote(game, seat, "day_vote"):
            continue
        targets = [target for target in alive_seats(game) if target != seat]
        requests[seat_key(seat)] = build_actor_request(game, seat, "day_vote", targets)
    game["actor_requests"] = requests
    game["actor_outputs"] = {}
    return bool(requests)


def prepare_current_day_pk_speech(game: dict[str, Any]) -> bool:
    queue = list(game.get("day_vote", {}).get("pk_speech_queue") or [])
    if not queue:
        return False
    seat = int(queue[0])
    if seat == int(game.get("user_seat") or 0) and not game.get("user_spectating"):
        game["pending_request"] = {
            "kind": "day_pk_speech",
            "actor": "user",
            "seat": seat,
            "prompt": "你进入PK台。请发表PK发言。",
        }
        game["actor_requests"] = {}
        return False
    game["actor_requests"] = {
        seat_key(seat): build_actor_request(game, seat, "day_pk_speech", [])
    }
    game["actor_outputs"] = {}
    return True


def set_user_day_pk_vote_request(game: dict[str, Any]) -> None:
    user_seat = int(game.get("user_seat") or 0)
    targets = [int(seat) for seat in game.get("day_vote", {}).get("pk_candidates") or []]
    game["pending_request"] = {
        "kind": "day_pk_vote",
        "actor": "user",
        "seat": user_seat,
        "target_seats": targets,
        "prompt": f"请在PK玩家中投票：{format_seats(targets)}。",
    }
    game["actor_requests"] = {}


def prepare_day_pk_ai_votes(game: dict[str, Any]) -> bool:
    user_seat = int(game.get("user_seat") or 0)
    targets = [int(seat) for seat in game.get("day_vote", {}).get("pk_candidates") or []]
    voters = [int(seat) for seat in game.get("day_vote", {}).get("pk_voters") or []]
    requests: dict[str, Any] = {}
    for seat in voters:
        if seat == user_seat or not can_player_vote(game, seat) or has_vote(game, seat, "day_pk_vote"):
            continue
        requests[seat_key(seat)] = build_actor_request(game, seat, "day_pk_vote", targets)
    game["actor_requests"] = requests
    game["actor_outputs"] = {}
    return bool(requests)


def prepare_current_ai_last_words(game: dict[str, Any]) -> bool:
    queue = list(game.get("last_words_queue") or [])
    if not queue:
        return False
    seat = int(queue[0])
    if seat == int(game.get("user_seat") or 0) and not game.get("user_spectating"):
        game["pending_request"] = {
            "kind": "last_words",
            "actor": "user",
            "seat": seat,
            "prompt": "你已出局。请发表遗言。",
        }
        game["actor_requests"] = {}
        return False
    game["actor_requests"] = {
        seat_key(seat): build_actor_request(game, seat, "last_words", [])
    }
    game["actor_outputs"] = {}
    return True


def sheriff_badge_targets(game: dict[str, Any], seat: int) -> list[int]:
    return [target for target in alive_seats(game) if target != seat]


def set_user_sheriff_badge_request(game: dict[str, Any], seat: int) -> None:
    targets = sheriff_badge_targets(game, seat)
    game["pending_request"] = {
        "kind": "sheriff_badge",
        "actor": "user",
        "seat": seat,
        "target_seats": targets,
        "prompt": f"你是死亡警长，请选择警徽移交目标，或回复撕毁警徽：{format_seats(targets)}。",
    }
    game["actor_requests"] = {}


def prepare_ai_sheriff_badge(game: dict[str, Any], seat: int) -> bool:
    game["actor_requests"] = {
        seat_key(seat): build_actor_request(game, seat, "sheriff_badge", sheriff_badge_targets(game, seat))
    }
    game["actor_outputs"] = {}
    return True


def transfer_sheriff_badge(game: dict[str, Any], old_seat: int, target: int | None) -> None:
    for item in game.get("players", []):
        item["is_sheriff"] = int(item.get("seat") or 0) == int(target or 0)
    if target:
        game["sheriff_seat"] = int(target)
        append_unique(game.setdefault("public_log", []), f"{old_seat}号警长将警徽移交给{target}号。")
    else:
        game["sheriff_seat"] = None
        append_unique(game.setdefault("public_log", []), f"{old_seat}号警长撕毁警徽。")


def prepare_next_sheriff_interrupt(game: dict[str, Any]) -> str:
    queue = [int(seat) for seat in game.get("sheriff_check_queue") or []]
    while queue:
        seat = int(queue.pop(0))
        game["sheriff_check_queue"] = queue
        if int(game.get("sheriff_seat") or 0) != seat:
            continue
        if seat == int(game.get("user_seat") or 0) and not game.get("user_spectating"):
            set_user_sheriff_badge_request(game, seat)
            game["phase"] = "SHERIFF_BADGE"
            return "render"
        game["phase"] = "SHERIFF_BADGE_AI"
        return "actors" if prepare_ai_sheriff_badge(game, seat) else "advance"

    game["phase"] = "HUNTER_CHECK"
    return "advance"


def death_shot_targets(game: dict[str, Any], seat: int) -> list[int]:
    return [target for target in alive_seats(game) if target != seat]


def death_shot_kind(game: dict[str, Any], seat: int) -> str | None:
    role = str(player(game, seat).get("role") or "")
    if role == "hunter":
        return "hunter_shot"
    if role == "wolf_king":
        return "wolf_king_shot"
    return None


def death_shot_role_name(kind: str) -> str:
    return "狼王" if kind == "wolf_king_shot" else "猎人"


def record_death_shot(game: dict[str, Any], shooter: int, target: int, kind: str) -> None:
    game["death_queue"] = [int(target)]
    game["death_causes"] = {str(target): kind}
    role_name = death_shot_role_name(kind)
    append_unique(game.setdefault("public_log", []), f"{shooter}号{role_name}开枪带走{target}号。")
    game["phase"] = "DEATH_ANNOUNCE"


def hunter_night_status_prompt(game: dict[str, Any], seat: int) -> str:
    status = "可以开枪" if hunter_status_private_info(game, seat)["hunter_can_shoot"] else "不能开枪"
    return f"猎人请睁眼。你的开枪状态：{status}。"


def set_user_death_shot_request(game: dict[str, Any], seat: int, kind: str) -> None:
    targets = death_shot_targets(game, seat)
    role_name = death_shot_role_name(kind)
    game["pending_request"] = {
        "kind": kind,
        "actor": "user",
        "seat": seat,
        "target_seats": targets,
        "prompt": f"你是{role_name}，可以选择开枪带走一名玩家，也可以回复不开枪：{format_seats(targets)}。",
    }
    game["actor_requests"] = {}


def prepare_ai_death_shot(game: dict[str, Any], seat: int, kind: str) -> bool:
    game["actor_requests"] = {
        seat_key(seat): build_actor_request(game, seat, kind, death_shot_targets(game, seat))
    }
    game["actor_outputs"] = {}
    return True


def prepare_next_hunter_interrupt(game: dict[str, Any]) -> str:
    queue = [int(seat) for seat in game.get("hunter_check_queue") or []]
    while queue:
        seat = int(queue.pop(0))
        game["hunter_check_queue"] = queue
        item = player(game, seat)
        kind = death_shot_kind(game, seat)
        if not kind:
            continue
        if str(game.get("death_causes", {}).get(str(seat)) or "") == "poison":
            append_unique(game.setdefault("public_log", []), f"{seat}号{death_shot_role_name(kind)}被毒，不能开枪。")
            continue
        if seat == int(game.get("user_seat") or 0) and not game.get("user_spectating"):
            set_user_death_shot_request(game, seat, kind)
            game["phase"] = "WOLF_KING_SHOT" if kind == "wolf_king_shot" else "HUNTER_SHOT"
            return "render"
        game["phase"] = "WOLF_KING_SHOT_AI" if kind == "wolf_king_shot" else "HUNTER_SHOT_AI"
        return "actors" if prepare_ai_death_shot(game, seat, kind) else "advance"

    if game.get("last_words_queue"):
        game["phase"] = "LAST_WORDS_NEXT"
        return "advance"
    if check_win_condition(game):
        return "render"
    game["phase"] = str(game.get("after_last_words_phase") or "DAY_END")
    return "advance"


def exile_player(game: dict[str, Any], seat: int) -> None:
    game["death_queue"] = [int(seat)]
    game["death_causes"] = {str(seat): "exile"}
    game["after_last_words_phase"] = "DAY_END"
    append_unique(game.setdefault("public_log", []), f"放逐投票结束，{seat}号出局。")
    game["phase"] = "DEATH_ANNOUNCE"


def handle_idiot_exile(game: dict[str, Any], seat: int) -> bool:
    item = player(game, seat)
    if item.get("role") != "idiot":
        return False
    item["can_vote"] = False
    append_unique(game.setdefault("public_log", []), f"{seat}号白痴翻牌免死，失去后续投票权。")
    game["last_words_queue"] = []
    game["phase"] = "DAY_END"
    return True


def begin_day_vote_pk(game: dict[str, Any], candidates: list[int]) -> None:
    voters = [seat for seat in alive_seats(game) if seat not in candidates and can_player_vote(game, seat)]
    game["day_vote"] = {
        "pk_candidates": candidates,
        "pk_speech_queue": list(candidates),
        "pk_voters": voters,
    }
    append_unique(game.setdefault("public_log", []), f"放逐投票平票：{format_seats(candidates)}，进入PK发言。")
    game["phase"] = "DAY_VOTE_PK_NEXT_SPEECH"


def vote_count_summary(game: dict[str, Any], phase: str, candidates: list[int]) -> str:
    counts = {int(seat): 0 for seat in candidates}
    for vote in game.get("votes", []):
        if not isinstance(vote, dict) or not vote_matches(game, vote, phase):
            continue
        target = int(vote.get("to") or 0)
        if target in counts:
            counts[target] += 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return "、".join(f"{seat}号{count}票" for seat, count in ordered) if ordered else "无"


def vote_breakdown_summary(game: dict[str, Any], phase: str) -> str:
    votes = [
        (int(vote.get("from") or 0), int(vote.get("to") or 0))
        for vote in game.get("votes", [])
        if isinstance(vote, dict) and vote_matches(game, vote, phase)
    ]
    votes = [(voter, target) for voter, target in votes if voter > 0 and target > 0]
    votes.sort(key=lambda item: item[0])
    return "、".join(f"{voter}号投{target}号" for voter, target in votes) if votes else "无"


def append_vote_result(game: dict[str, Any], title: str, phase: str, candidates: list[int]) -> None:
    append_unique(game.setdefault("public_log", []), f"{title}：{vote_count_summary(game, phase, candidates)}。")
    append_unique(game.setdefault("public_log", []), f"票型：{vote_breakdown_summary(game, phase)}。")


def resolve_day_vote(game: dict[str, Any]) -> None:
    alive = alive_seats(game)
    if not alive:
        append_unique(game.setdefault("public_log", []), "放逐投票结束，无人投票，本日无人出局。")
        game["phase"] = "DAY_END"
        return

    append_vote_result(game, "放逐投票结果", "day_vote", alive)
    winners = vote_winners(game, "day_vote", alive)
    if not winners:
        append_unique(game.setdefault("public_log", []), "放逐投票结束，无人投票，本日无人出局。")
        game["phase"] = "DAY_END"
        return
    if len(winners) != 1:
        begin_day_vote_pk(game, winners)
        return

    if handle_idiot_exile(game, winners[0]):
        return
    exile_player(game, winners[0])


def resolve_day_pk_vote(game: dict[str, Any]) -> None:
    candidates = [int(seat) for seat in game.get("day_vote", {}).get("pk_candidates") or []]
    append_vote_result(game, "PK投票结果", "day_pk_vote", candidates)
    winners = vote_winners(game, "day_pk_vote", candidates)
    if len(winners) != 1:
        append_unique(game.setdefault("public_log", []), "PK投票仍然平票，本日无人出局。")
        game["phase"] = "DAY_END"
        return
    if handle_idiot_exile(game, winners[0]):
        return
    exile_player(game, winners[0])


def resolve_election_vote(game: dict[str, Any]) -> None:
    candidates = [int(seat) for seat in game.get("election", {}).get("candidates") or []]
    if not candidates:
        game["sheriff_seat"] = None
        game["phase"] = "DEATH_ANNOUNCE"
        append_unique(game.setdefault("public_log", []), "无人上警，本局暂时没有警长。")
        return

    counts = {seat: 0 for seat in candidates}
    for vote in game.get("votes", []):
        if not isinstance(vote, dict) or vote.get("phase") != "election_vote":
            continue
        target = int(vote.get("to") or 0)
        if target in counts:
            counts[target] += 1

    top_count = max(counts.values()) if counts else 0
    winners = [seat for seat, count in counts.items() if count == top_count]
    append_vote_result(game, "警长投票结果", "election_vote", candidates)
    if len(winners) != 1:
        voters = [
            seat for seat in alive_seats(game)
            if seat not in winners
        ]
        election = game.setdefault("election", {})
        election["pk_candidates"] = winners
        election["pk_speech_queue"] = list(winners)
        election["pk_voters"] = voters
        game["phase"] = "ELECTION_PK_NEXT_SPEECH"
        append_unique(game.setdefault("public_log", []), f"警长投票平票：{format_seats(winners)}，进入PK发言。")
        return

    winner = winners[0]
    for item in game.get("players", []):
        item["is_sheriff"] = int(item.get("seat") or 0) == winner
    game["sheriff_seat"] = winner
    game["phase"] = "DEATH_ANNOUNCE"
    append_unique(game.setdefault("public_log", []), f"警长投票结束，{winner}号当选警长。")


def resolve_election_pk_vote(game: dict[str, Any]) -> None:
    candidates = [int(seat) for seat in game.get("election", {}).get("pk_candidates") or []]
    append_vote_result(game, "警长PK投票结果", "election_pk_vote", candidates)
    winners = vote_winners(game, "election_pk_vote", candidates)
    if len(winners) != 1:
        for item in game.get("players", []):
            item["is_sheriff"] = False
        game["sheriff_seat"] = None
        game["phase"] = "DEATH_ANNOUNCE"
        append_unique(game.setdefault("public_log", []), "警长PK投票仍然平票，本局暂时没有警长。")
        return

    winner = winners[0]
    for item in game.get("players", []):
        item["is_sheriff"] = int(item.get("seat") or 0) == winner
    game["sheriff_seat"] = winner
    game["phase"] = "DEATH_ANNOUNCE"
    append_unique(game.setdefault("public_log", []), f"警长PK投票结束，{winner}号当选警长。")


def withdraw_from_sheriff_campaign(game: dict[str, Any], seat: int) -> None:
    election = game.setdefault("election", {})
    election["candidates"] = [int(item) for item in election.get("candidates") or [] if int(item) != int(seat)]
    voters = [int(item) for item in election.get("voters") or []]
    if seat not in voters:
        voters.append(seat)
    election["voters"] = sorted(voters)
    withdrawn = [int(item) for item in election.get("withdrawn") or []]
    if seat not in withdrawn:
        withdrawn.append(seat)
    election["withdrawn"] = sorted(withdrawn)
    append_unique(game.setdefault("public_log", []), f"{seat}号退水，留在警下参与警长投票。")


def apply_actor_outputs(game: dict[str, Any]) -> None:
    outputs = game.get("actor_outputs")
    if not isinstance(outputs, dict):
        return
    current_actor_ids = set((game.get("actor_requests") or {}).keys())
    if current_actor_ids:
        outputs = {
            actor_id: output
            for actor_id, output in outputs.items()
            if actor_id in current_actor_ids
        }

    if game.get("phase") in {"NIGHT_WOLF", "NIGHT_SEER", "NIGHT_GUARD", "NIGHT_WITCH", "NIGHT_HUNTER"}:
        for actor_id, output in sorted(outputs.items()):
            action = output.get("action") if isinstance(output, dict) else {}
            kind = action.get("kind") if isinstance(action, dict) else ""
            if kind == "kill" and action.get("target_seat"):
                game.setdefault("night", {})["wolf_target"] = int(action["target_seat"])
            elif kind == "check" and action.get("target_seat"):
                record_seer_check(game, int(action["seat"]), int(action["target_seat"]))
            elif kind == "guard" and action.get("target_seat"):
                game.setdefault("night", {})["guard_target"] = int(action["target_seat"])
            elif kind == "witch_save" and game.get("witch_save_available", True):
                game.setdefault("night", {})["witch_saved"] = True
                game["witch_save_available"] = False
            elif kind == "witch_poison" and action.get("target_seat") and game.get("witch_poison_available", True):
                game.setdefault("night", {})["witch_poison_target"] = int(action["target_seat"])
                game["witch_poison_available"] = False
            elif kind == "hunter_status":
                game.setdefault("night", {})["hunter_status_checked"] = True
        game["phase"] = {
            "NIGHT_WOLF": "NIGHT_SEER",
            "NIGHT_SEER": "NIGHT_GUARD",
            "NIGHT_GUARD": "NIGHT_WITCH",
            "NIGHT_WITCH": "NIGHT_HUNTER",
            "NIGHT_HUNTER": "DAYBREAK",
        }.get(str(game.get("phase")), "DAYBREAK")
        game["actor_requests"] = {}
        game["actor_outputs"] = {}
        return

    if game.get("phase") == "ELECTION_AI_JOIN":
        choices = game.setdefault("election", {}).setdefault("choices", {})
        for actor_id, output in sorted(outputs.items()):
            action = output.get("action") if isinstance(output, dict) else {}
            seat = int(action.get("seat") or actor_id.removeprefix("p") or 0)
            choices[str(seat)] = "join" if action.get("kind") == "join_election" else "skip"
        game["phase"] = "ELECTION_BUILD"
        game["actor_requests"] = {}
        game["actor_outputs"] = {}
        return

    if game.get("phase") == "ELECTION_AI_SPEECH":
        election = game.setdefault("election", {})
        queue = list(election.get("speech_queue") or [])
        for actor_id, output in sorted(outputs.items()):
            action = output.get("action") if isinstance(output, dict) else {}
            seat = int(action.get("seat") or actor_id.removeprefix("p") or 0)
            speech = str(action.get("speech") or "").strip()
            if speech:
                append_unique(game.setdefault("public_log", []), f"{seat}号玩家开始发言：")
                append_unique(game.setdefault("public_log", []), f"{seat}号：{speech}")
            if queue and int(queue[0]) == seat:
                queue.pop(0)
        election["speech_queue"] = queue
        game["actor_requests"] = {}
        game["actor_outputs"] = {}
        game["phase"] = "ELECTION_NEXT_SPEECH"
        return

    if game.get("phase") == "ELECTION_PK_AI_SPEECH":
        election = game.setdefault("election", {})
        queue = list(election.get("pk_speech_queue") or [])
        for actor_id, output in sorted(outputs.items()):
            action = output.get("action") if isinstance(output, dict) else {}
            seat = int(action.get("seat") or actor_id.removeprefix("p") or 0)
            speech = str(action.get("speech") or "").strip()
            if speech:
                append_unique(game.setdefault("public_log", []), f"{seat}号玩家开始警长PK发言：")
                append_unique(game.setdefault("public_log", []), f"{seat}号：{speech}")
            if queue and int(queue[0]) == seat:
                queue.pop(0)
        election["pk_speech_queue"] = queue
        game["actor_requests"] = {}
        game["actor_outputs"] = {}
        game["phase"] = "ELECTION_PK_NEXT_SPEECH"
        return

    if game.get("phase") == "ELECTION_AI_VOTE":
        for actor_id, output in sorted(outputs.items()):
            action = output.get("action") if isinstance(output, dict) else {}
            if not isinstance(action, dict) or action.get("kind") != "vote":
                continue
            seat = int(action.get("seat") or actor_id.removeprefix("p") or 0)
            target = int(action.get("target_seat") or 0)
            if seat and target:
                record_vote(game, seat, target, "election_vote")
        game["actor_requests"] = {}
        game["actor_outputs"] = {}
        game["phase"] = "ELECTION_RESOLVE"
        return

    if game.get("phase") == "ELECTION_PK_AI_VOTE":
        for actor_id, output in sorted(outputs.items()):
            action = output.get("action") if isinstance(output, dict) else {}
            if not isinstance(action, dict) or action.get("kind") != "vote":
                continue
            seat = int(action.get("seat") or actor_id.removeprefix("p") or 0)
            target = int(action.get("target_seat") or 0)
            if seat and target:
                record_vote(game, seat, target, "election_pk_vote")
        game["actor_requests"] = {}
        game["actor_outputs"] = {}
        game["phase"] = "ELECTION_PK_RESOLVE"
        return

    if game.get("phase") == "DAY_AI_SPEECH":
        queue = list(game.get("day_speech_queue") or [])
        for actor_id, output in sorted(outputs.items()):
            action = output.get("action") if isinstance(output, dict) else {}
            seat = int(action.get("seat") or actor_id.removeprefix("p") or 0)
            speech = str(action.get("speech") or "").strip()
            if seat and isinstance(action, dict) and action.get("kind") == "self_explode" and can_self_explode(game, seat):
                apply_self_explosion(game, seat, speech)
                return
            if speech:
                append_unique(game.setdefault("public_log", []), f"{seat}号玩家开始发言：")
                append_unique(game.setdefault("public_log", []), f"{seat}号：{speech}")
            if queue and int(queue[0]) == seat:
                queue.pop(0)
        game["day_speech_queue"] = queue
        game["actor_requests"] = {}
        game["actor_outputs"] = {}
        game["phase"] = "DAY_NEXT_SPEECH"
        return

    if game.get("phase") == "DAY_ORDER_AI":
        for actor_id, output in sorted(outputs.items()):
            action = output.get("action") if isinstance(output, dict) else {}
            direction = str(action.get("direction") or "") if isinstance(action, dict) else ""
            if action.get("kind") == "choose_direction" and direction in {"left", "right"}:
                apply_day_speech_direction(game, direction)
                break
            target = int(action.get("target_seat") or 0) if isinstance(action, dict) else 0
            apply_day_speech_order(game, target)
            break
        else:
            apply_day_speech_order(game, None)
        game["actor_requests"] = {}
        game["actor_outputs"] = {}
        return

    if game.get("phase") == "DAY_VOTE_PK_AI_SPEECH":
        day_vote = game.setdefault("day_vote", {})
        queue = list(day_vote.get("pk_speech_queue") or [])
        for actor_id, output in sorted(outputs.items()):
            action = output.get("action") if isinstance(output, dict) else {}
            seat = int(action.get("seat") or actor_id.removeprefix("p") or 0)
            speech = str(action.get("speech") or "").strip()
            if speech:
                append_unique(game.setdefault("public_log", []), f"{seat}号玩家开始PK发言：")
                append_unique(game.setdefault("public_log", []), f"{seat}号：{speech}")
            if queue and int(queue[0]) == seat:
                queue.pop(0)
        day_vote["pk_speech_queue"] = queue
        game["actor_requests"] = {}
        game["actor_outputs"] = {}
        game["phase"] = "DAY_VOTE_PK_NEXT_SPEECH"
        return

    if game.get("phase") == "DAY_AI_VOTE":
        for actor_id, output in sorted(outputs.items()):
            action = output.get("action") if isinstance(output, dict) else {}
            if not isinstance(action, dict) or action.get("kind") != "vote":
                continue
            seat = int(action.get("seat") or actor_id.removeprefix("p") or 0)
            target = int(action.get("target_seat") or 0)
            if seat and target:
                record_vote(game, seat, target, "day_vote")
        game["actor_requests"] = {}
        game["actor_outputs"] = {}
        game["phase"] = "DAY_RESOLVE_VOTE"
        return

    if game.get("phase") == "DAY_VOTE_PK_AI_VOTE":
        for actor_id, output in sorted(outputs.items()):
            action = output.get("action") if isinstance(output, dict) else {}
            if not isinstance(action, dict) or action.get("kind") != "vote":
                continue
            seat = int(action.get("seat") or actor_id.removeprefix("p") or 0)
            target = int(action.get("target_seat") or 0)
            if seat and target:
                record_vote(game, seat, target, "day_pk_vote")
        game["actor_requests"] = {}
        game["actor_outputs"] = {}
        game["phase"] = "DAY_VOTE_PK_RESOLVE"
        return

    if game.get("phase") == "LAST_WORDS_AI":
        queue = list(game.get("last_words_queue") or [])
        for actor_id, output in sorted(outputs.items()):
            action = output.get("action") if isinstance(output, dict) else {}
            seat = int(action.get("seat") or actor_id.removeprefix("p") or 0)
            speech = str(action.get("speech") or "").strip()
            if speech:
                append_unique(game.setdefault("public_log", []), f"{seat}号遗言：{speech}")
            if queue and int(queue[0]) == seat:
                queue.pop(0)
        game["last_words_queue"] = queue
        game["actor_requests"] = {}
        game["actor_outputs"] = {}
        game["phase"] = "LAST_WORDS_NEXT" if queue or game.get("death_followup_pending") else str(game.get("after_last_words_phase") or "DAY_END")
        return

    if game.get("phase") in {"HUNTER_SHOT_AI", "WOLF_KING_SHOT_AI"}:
        cause = "wolf_king_shot" if game.get("phase") == "WOLF_KING_SHOT_AI" else "hunter_shot"
        for actor_id, output in sorted(outputs.items()):
            action = output.get("action") if isinstance(output, dict) else {}
            if not isinstance(action, dict) or action.get("kind") != "shoot":
                continue
            target = int(action.get("target_seat") or 0)
            if target:
                shooter = int(action.get("seat") or actor_id.removeprefix("p") or 0)
                record_death_shot(game, shooter, target, cause)
                break
        else:
            game["phase"] = "LAST_WORDS_NEXT" if game.get("last_words_queue") else str(game.get("after_last_words_phase") or "DAY_END")
        game["actor_requests"] = {}
        game["actor_outputs"] = {}
        return

    if game.get("phase") == "SHERIFF_BADGE_AI":
        for actor_id, output in sorted(outputs.items()):
            action = output.get("action") if isinstance(output, dict) else {}
            if not isinstance(action, dict):
                continue
            old_seat = int(action.get("seat") or actor_id.removeprefix("p") or 0)
            target = int(action.get("target_seat") or 0)
            if action.get("kind") == "transfer_badge" and target:
                transfer_sheriff_badge(game, old_seat, target)
            else:
                transfer_sheriff_badge(game, old_seat, None)
            break
        game["actor_requests"] = {}
        game["actor_outputs"] = {}
        game["phase"] = "HUNTER_CHECK"
        return


def build_election_lists(game: dict[str, Any]) -> None:
    election = game.setdefault("election", {})
    choices = election.setdefault("choices", {})
    alive = alive_seats(game)
    candidates = [seat for seat in alive if choices.get(str(seat)) == "join"]
    voters = [seat for seat in alive if seat not in candidates]
    start = random.Random(f"{game.get('seed')}:election_start").randint(1, 12)
    ordered_candidates = [seat for seat in range(start, 13) if seat in candidates]
    ordered_candidates.extend(seat for seat in range(1, start) if seat in candidates)
    election["candidates"] = candidates
    election["voters"] = voters
    election["speech_start"] = start
    election["speech_queue"] = ordered_candidates
    append_unique(game["public_log"], "警长竞选名单已确定。")
    append_unique(game["public_log"], f"本轮上警玩家：{format_seats(candidates)}。")
    append_unique(game["public_log"], f"本轮警下玩家：{format_seats(voters)}。")
    append_unique(
        game["public_log"],
        f"随机起点为{start}号，警上按座位顺序发言，首位发言是{ordered_candidates[0]}号。"
        if ordered_candidates
        else f"随机起点为{start}号，本轮无人上警。",
    )


def calculate_night_deaths(game: dict[str, Any]) -> list[int]:
    night = game.setdefault("night", {})
    deaths: list[int] = []
    causes = dict(game.get("death_causes") or {})
    wolf_target = night.get("wolf_target")
    if wolf_target:
        guarded = int(wolf_target) == int(night.get("guard_target") or 0)
        saved = bool(night.get("witch_saved"))
        if saved == guarded:
            seat = int(wolf_target)
            deaths.append(seat)
            causes[str(seat)] = "night"
    poison_target = night.get("witch_poison_target")
    if poison_target:
        seat = int(poison_target)
        if seat not in deaths:
            deaths.append(seat)
        causes[str(seat)] = "poison"
    game["death_queue"] = deaths
    game["death_causes"] = causes
    game["guard_last_target"] = night.get("guard_target")
    return deaths


def announce_deaths(game: dict[str, Any], *, cause: str, next_phase: str) -> None:
    deaths = [int(seat) for seat in game.get("death_queue") or []]
    game["death_queue"] = []
    if not deaths:
        append_unique(game.setdefault("public_log", []), "昨夜平安夜。" if cause == "night" else "无人出局。")
        game["phase"] = next_phase
        return

    for seat in deaths:
        player(game, seat)["alive"] = False
        if seat not in game.setdefault("dead", []):
            game["dead"].append(seat)
    causes = game.get("death_causes") if isinstance(game.get("death_causes"), dict) else {}
    if cause == "night" and all(str(causes.get(str(seat)) or "") in {"", "night", "poison"} for seat in deaths):
        append_unique(game.setdefault("public_log", []), f"昨夜死亡：{format_seats(deaths)}。")
    elif all(str(causes.get(str(seat)) or "") == "exile" for seat in deaths):
        append_unique(game.setdefault("public_log", []), f"放逐出局：{format_seats(deaths)}。")
    else:
        append_unique(game.setdefault("public_log", []), f"出局玩家：{format_seats(deaths)}。")

    has_last_words = cause == "exile" or (cause == "night" and int(game.get("day") or 1) == 1)
    game["last_words_queue"] = list(deaths) if has_last_words else []
    game["death_followup_pending"] = cause == "exile" and bool(game["last_words_queue"])
    game["sheriff_check_queue"] = list(deaths)
    game["hunter_check_queue"] = list(deaths)
    game["after_last_words_phase"] = next_phase
    mark_post_death_choice_if_needed(game, next_phase)
    game["phase"] = "LAST_WORDS_NEXT" if game["death_followup_pending"] else "SHERIFF_BADGE_CHECK"


def apply_user_input(game: dict[str, Any], user_input: str) -> None:
    text = user_input.strip()
    request = game.get("pending_request") if isinstance(game.get("pending_request"), dict) else None
    if not request:
        return
    if request.get("kind") == "post_death_choice":
        handle_post_death_choice(game, text)
        return
    if request.get("kind") == "post_game_choice":
        game["pending_request"] = None
        game["phase"] = "LOBBY" if should_start_next_game(text) else "GAME_OVER"
        return
    if request.get("kind") in {"night_kill", "seer_check", "guard", "witch", "hunter_status"}:
        kind = str(request.get("kind") or "")
        seat = int(request.get("seat") or game.get("user_seat") or 0)
        target = target_from_text(text, [int(item) for item in request.get("target_seats") or []])
        night = game.setdefault("night", {})
        if kind == "night_kill" and target:
            night["wolf_target"] = target
            game["phase"] = "NIGHT_SEER"
        elif kind == "seer_check" and target:
            record_seer_check(game, seat, target)
            game["phase"] = "NIGHT_GUARD"
        elif kind == "guard" and target:
            night["guard_target"] = target
            game["phase"] = "NIGHT_WITCH"
        elif kind == "witch":
            witch_action, witch_target = parse_witch_action(
                text,
                target=target,
                can_save=bool(game.get("witch_save_available", True)),
                can_poison=bool(game.get("witch_poison_available", True)),
            )
            if witch_action == "save":
                night["witch_saved"] = True
                game["witch_save_available"] = False
            elif witch_action == "poison" and witch_target:
                night["witch_poison_target"] = witch_target
                game["witch_poison_available"] = False
            game["phase"] = "NIGHT_HUNTER"
        elif kind == "hunter_status":
            night["hunter_status_checked"] = True
            game["phase"] = "DAYBREAK"
        game["pending_request"] = None
        return
    if request.get("kind") in {"hunter_shot", "wolf_king_shot"}:
        target = target_from_text(text, [int(item) for item in request.get("target_seats") or []])
        if target and not should_skip_shot(text):
            seat = int(request.get("seat") or game.get("user_seat") or 0)
            record_death_shot(game, seat, target, str(request.get("kind")))
        else:
            game["phase"] = "LAST_WORDS_NEXT" if game.get("last_words_queue") else str(game.get("after_last_words_phase") or "DAY_END")
        game["pending_request"] = None
        return
    if request.get("kind") == "sheriff_badge":
        seat = int(request.get("seat") or game.get("user_seat") or 0)
        target = target_from_text(text, [int(item) for item in request.get("target_seats") or []])
        if target and not should_destroy_badge(text):
            transfer_sheriff_badge(game, seat, target)
        else:
            transfer_sheriff_badge(game, seat, None)
        game["pending_request"] = None
        game["phase"] = "HUNTER_CHECK"
        return
    if request.get("kind") == "election_join":
        game.setdefault("election", {}).setdefault("choices", {})[str(game["user_seat"])] = parse_election_choice(text)
        game["pending_request"] = None
        game["phase"] = "ELECTION_AI_JOIN"
        return
    if request.get("kind") == "election_speech":
        seat = int(game.get("user_seat") or 0)
        if can_self_explode(game, seat) and should_self_explode(text):
            apply_self_explosion(game, seat, text)
            return
        append_unique(game.setdefault("public_log", []), f"{seat}号：{text}")
        queue = list(game.setdefault("election", {}).get("speech_queue") or [])
        if queue and int(queue[0]) == seat:
            queue.pop(0)
        game["election"]["speech_queue"] = queue
        if should_withdraw_election(text):
            withdraw_from_sheriff_campaign(game, seat)
        game["pending_request"] = None
        game["phase"] = "ELECTION_NEXT_SPEECH"
        return
    if request.get("kind") == "election_vote":
        seat = int(game.get("user_seat") or 0)
        target = target_from_text(text, [int(item) for item in request.get("target_seats") or []])
        if target:
            record_vote(game, seat, target, "election_vote")
        game["pending_request"] = None
        game["phase"] = "ELECTION_AI_VOTE"
        return
    if request.get("kind") == "election_pk_speech":
        seat = int(game.get("user_seat") or 0)
        if can_self_explode(game, seat) and should_self_explode(text):
            apply_self_explosion(game, seat, text)
            return
        append_unique(game.setdefault("public_log", []), f"{seat}号：{text}")
        queue = list(game.setdefault("election", {}).get("pk_speech_queue") or [])
        if queue and int(queue[0]) == seat:
            queue.pop(0)
        game["election"]["pk_speech_queue"] = queue
        game["pending_request"] = None
        game["phase"] = "ELECTION_PK_NEXT_SPEECH"
        return
    if request.get("kind") == "election_pk_vote":
        seat = int(game.get("user_seat") or 0)
        target = target_from_text(text, [int(item) for item in request.get("target_seats") or []])
        if target:
            record_vote(game, seat, target, "election_pk_vote")
        game["pending_request"] = None
        game["phase"] = "ELECTION_PK_AI_VOTE"
        return
    if request.get("kind") == "day_speech":
        seat = int(game.get("user_seat") or 0)
        if can_self_explode(game, seat) and should_self_explode(text):
            apply_self_explosion(game, seat, text)
            return
        append_unique(game.setdefault("public_log", []), f"{seat}号：{text}")
        queue = list(game.get("day_speech_queue") or [])
        if queue and int(queue[0]) == seat:
            queue.pop(0)
        game["day_speech_queue"] = queue
        game["pending_request"] = None
        game["phase"] = "DAY_NEXT_SPEECH"
        return
    if request.get("kind") == "day_order":
        direction = parse_day_order_direction(text)
        if direction:
            apply_day_speech_direction(game, direction)
            game["pending_request"] = None
            return
        target = target_from_text(text, [int(item) for item in request.get("target_seats") or []])
        apply_day_speech_order(game, target)
        game["pending_request"] = None
        return
    if request.get("kind") == "day_vote":
        seat = int(game.get("user_seat") or 0)
        target = target_from_text(text, [int(item) for item in request.get("target_seats") or []])
        if target:
            record_vote(game, seat, target, "day_vote")
        game["pending_request"] = None
        game["phase"] = "DAY_AI_VOTE"
        return
    if request.get("kind") == "day_pk_speech":
        seat = int(game.get("user_seat") or 0)
        if can_self_explode(game, seat) and should_self_explode(text):
            apply_self_explosion(game, seat, text)
            return
        append_unique(game.setdefault("public_log", []), f"{seat}号：{text}")
        queue = list(game.get("day_vote", {}).get("pk_speech_queue") or [])
        if queue and int(queue[0]) == seat:
            queue.pop(0)
        game.setdefault("day_vote", {})["pk_speech_queue"] = queue
        game["pending_request"] = None
        game["phase"] = "DAY_VOTE_PK_NEXT_SPEECH"
        return
    if request.get("kind") == "day_pk_vote":
        seat = int(game.get("user_seat") or 0)
        target = target_from_text(text, [int(item) for item in request.get("target_seats") or []])
        if target:
            record_vote(game, seat, target, "day_pk_vote")
        game["pending_request"] = None
        game["phase"] = "DAY_VOTE_PK_AI_VOTE"
        return
    if request.get("kind") == "last_words":
        seat = int(game.get("user_seat") or 0)
        append_unique(game.setdefault("public_log", []), f"{seat}号遗言：{text}")
        queue = list(game.get("last_words_queue") or [])
        if queue and int(queue[0]) == seat:
            queue.pop(0)
        game["last_words_queue"] = queue
        game["pending_request"] = None
        game["phase"] = "LAST_WORDS_NEXT" if queue or game.get("death_followup_pending") else str(game.get("after_last_words_phase") or "DAY_END")


def advance_state_machine(game: dict[str, Any]) -> str:
    if game.get("phase") == "NIGHT_WOLF":
        return advance_night_stage(
            game,
            phase="NIGHT_WOLF",
            user_roles={"wolf", "wolf_king"},
            ai_role="wolf",
            request_kind="night_kill",
            next_phase="NIGHT_SEER",
            prompt="狼人请睁眼。请选择今晚袭击目标。",
        )

    if game.get("phase") == "NIGHT_SEER":
        return advance_night_stage(
            game,
            phase="NIGHT_SEER",
            user_roles={"seer"},
            ai_role="seer",
            request_kind="seer_check",
            next_phase="NIGHT_GUARD",
            prompt="预言家请睁眼。请选择今晚查验目标。",
        )

    if game.get("phase") == "NIGHT_GUARD":
        return advance_night_stage(
            game,
            phase="NIGHT_GUARD",
            user_roles={"guard"},
            ai_role="guard",
            request_kind="guard",
            next_phase="NIGHT_WITCH",
            prompt="守卫请睁眼。请选择今晚守护目标。",
        )

    if game.get("phase") == "NIGHT_WITCH":
        return advance_night_stage(
            game,
            phase="NIGHT_WITCH",
            user_roles={"witch"},
            ai_role="witch",
            request_kind="witch",
            next_phase="NIGHT_HUNTER",
            prompt="女巫请睁眼。你可以选择救人、毒人或不使用药。",
        )

    if game.get("phase") == "NIGHT_HUNTER":
        user_seat = int(game.get("user_seat") or 0)
        return advance_night_stage(
            game,
            phase="NIGHT_HUNTER",
            user_roles={"hunter"},
            ai_role="hunter",
            request_kind="hunter_status",
            next_phase="DAYBREAK",
            prompt=hunter_night_status_prompt(game, user_seat),
        )

    if game.get("phase") == "DAYBREAK":
        append_unique(game["public_log"], "天亮了。")
        calculate_night_deaths(game)
        if int(game.get("day") or 1) > 1:
            game["phase"] = "DEATH_ANNOUNCE"
            game["pending_request"] = None
            return "advance"
        game["phase"] = "ELECTION_JOIN"
        game["pending_request"] = {
            "kind": "election_join",
            "actor": "user",
            "seat": game["user_seat"],
            "prompt": "你可以回复“上警”参加警长竞选，也可以回复“不上警”留在警下。",
        }
        return "render"

    if game.get("phase") == "POST_DEATH_CHOICE":
        return "render"

    if game.get("phase") == "DEATH_ANNOUNCE":
        death_causes = game.get("death_causes") if isinstance(game.get("death_causes"), dict) else {}
        deaths = [int(seat) for seat in game.get("death_queue") or []]
        is_day_exile = bool(deaths) and all(str(death_causes.get(str(seat)) or "") == "exile" for seat in deaths)
        is_death_shot = bool(deaths) and all(
            str(death_causes.get(str(seat)) or "") in {"hunter_shot", "wolf_king_shot"}
            for seat in deaths
        )
        announce_deaths(
            game,
            cause="exile" if is_day_exile else "death_shot" if is_death_shot else "night",
            next_phase=(
                "DAY_END"
                if is_day_exile
                else str(game.get("after_last_words_phase") or "DAY_END")
                if is_death_shot
                else "DAY_DISCUSS_ORDER"
            ),
        )
        return "advance"

    if game.get("phase") == "SHERIFF_BADGE_CHECK":
        return prepare_next_sheriff_interrupt(game)

    if game.get("phase") == "SHERIFF_BADGE_AI":
        return "actors" if game.get("actor_requests") else prepare_next_sheriff_interrupt(game)

    if game.get("phase") == "HUNTER_CHECK":
        return prepare_next_hunter_interrupt(game)

    if game.get("phase") in {"HUNTER_SHOT_AI", "WOLF_KING_SHOT_AI"}:
        return "actors" if game.get("actor_requests") else prepare_next_hunter_interrupt(game)

    if game.get("phase") == "ELECTION_AI_JOIN":
        return "actors" if prepare_election_ai_choices(game) else "advance"

    if game.get("phase") == "ELECTION_BUILD":
        build_election_lists(game)
        game["phase"] = "ELECTION_NEXT_SPEECH"
        return "advance"

    if game.get("phase") == "ELECTION_NEXT_SPEECH":
        if game.get("post_death_choice_pending"):
            set_post_death_choice_request(game)
            return "render"
        queue = game.get("election", {}).get("speech_queue") or []
        if not queue:
            game["phase"] = "ELECTION_VOTE" if game.get("election", {}).get("candidates") else "ELECTION_RESOLVE"
            game["pending_request"] = None
            if game.get("election", {}).get("candidates"):
                append_unique(game["public_log"], "警上发言结束，进入警长投票。")
            return "advance"
        if int(queue[0]) == int(game.get("user_seat") or 0) and not game.get("user_spectating"):
            game["pending_request"] = {
                "kind": "election_speech",
                "actor": "user",
                "seat": game["user_seat"],
                "prompt": "轮到你发表警上发言。",
            }
            return "render"
        game["phase"] = "ELECTION_AI_SPEECH"
        return "actors" if prepare_current_ai_speech(game) else "advance"

    if game.get("phase") == "ELECTION_AI_SPEECH":
        return "actors" if prepare_current_ai_speech(game) else "advance"

    if game.get("phase") == "ELECTION_VOTE":
        if not game.get("election", {}).get("candidates"):
            game["phase"] = "ELECTION_RESOLVE"
            game["pending_request"] = None
            return "advance"
        user_seat = int(game.get("user_seat") or 0)
        voters = [int(seat) for seat in game.get("election", {}).get("voters") or []]
        if not game.get("user_spectating") and user_seat in voters and not has_vote(game, user_seat, "election_vote"):
            set_user_election_vote_request(game)
            return "render"
        game["phase"] = "ELECTION_AI_VOTE"
        return "advance"

    if game.get("phase") == "ELECTION_AI_VOTE":
        return "actors" if prepare_election_ai_votes(game) else "advance"

    if game.get("phase") == "ELECTION_RESOLVE":
        resolve_election_vote(game)
        return "advance"

    if game.get("phase") == "ELECTION_PK_NEXT_SPEECH":
        if game.get("post_death_choice_pending"):
            set_post_death_choice_request(game)
            return "render"
        queue = game.get("election", {}).get("pk_speech_queue") or []
        if not queue:
            game["phase"] = "ELECTION_PK_VOTE"
            game["pending_request"] = None
            append_unique(game.setdefault("public_log", []), "警长PK发言结束，进入警长PK投票。")
            return "advance"
        if int(queue[0]) == int(game.get("user_seat") or 0) and not game.get("user_spectating"):
            game["pending_request"] = {
                "kind": "election_pk_speech",
                "actor": "user",
                "seat": game["user_seat"],
                "prompt": "你进入警长PK台。请发表PK发言。",
            }
            return "render"
        game["phase"] = "ELECTION_PK_AI_SPEECH"
        return "actors" if prepare_current_election_pk_speech(game) else "advance"

    if game.get("phase") == "ELECTION_PK_AI_SPEECH":
        return "actors" if prepare_current_election_pk_speech(game) else "advance"

    if game.get("phase") == "ELECTION_PK_VOTE":
        user_seat = int(game.get("user_seat") or 0)
        voters = [int(seat) for seat in game.get("election", {}).get("pk_voters") or []]
        if not game.get("user_spectating") and user_seat in voters and not has_vote(game, user_seat, "election_pk_vote"):
            set_user_election_pk_vote_request(game)
            return "render"
        game["phase"] = "ELECTION_PK_AI_VOTE"
        return "advance"

    if game.get("phase") == "ELECTION_PK_AI_VOTE":
        return "actors" if prepare_election_pk_ai_votes(game) else "advance"

    if game.get("phase") == "ELECTION_PK_RESOLVE":
        resolve_election_pk_vote(game)
        return "advance"

    if game.get("phase") == "DAY_DISCUSS_ORDER":
        if game.get("post_death_choice_pending"):
            set_post_death_choice_request(game)
            return "render"
        build_day_speech_order(game)
        if game.get("phase") == "DAY_ORDER":
            return "render"
        if game.get("phase") == "DAY_ORDER_AI":
            return "actors"
        return "advance"

    if game.get("phase") == "DAY_ORDER_AI":
        return "actors" if game.get("actor_requests") else "advance"

    if game.get("phase") == "DAY_NEXT_SPEECH":
        if game.get("post_death_choice_pending"):
            set_post_death_choice_request(game)
            return "render"
        queue = game.get("day_speech_queue") or []
        if not queue:
            game["phase"] = "DAY_VOTE"
            game["pending_request"] = None
            append_unique(game.setdefault("public_log", []), "所有玩家发言结束，进入放逐投票。")
            return "advance"
        if int(queue[0]) == int(game.get("user_seat") or 0) and not game.get("user_spectating"):
            game["pending_request"] = {
                "kind": "day_speech",
                "actor": "user",
                "seat": game["user_seat"],
                "prompt": "轮到你发表白天发言。",
            }
            return "render"
        game["phase"] = "DAY_AI_SPEECH"
        return "actors" if prepare_current_day_speech(game) else "advance"

    if game.get("phase") == "DAY_AI_SPEECH":
        return "actors" if prepare_current_day_speech(game) else "advance"

    if game.get("phase") == "DAY_VOTE":
        user_seat = int(game.get("user_seat") or 0)
        if not game.get("user_spectating") and can_player_vote(game, user_seat) and not has_vote(game, user_seat, "day_vote"):
            set_user_day_vote_request(game)
            return "render"
        game["phase"] = "DAY_AI_VOTE"
        return "advance"

    if game.get("phase") == "DAY_AI_VOTE":
        if prepare_day_ai_votes(game):
            return "actors"
        game["phase"] = "DAY_RESOLVE_VOTE"
        return "advance"

    if game.get("phase") == "DAY_RESOLVE_VOTE":
        resolve_day_vote(game)
        if check_win_condition(game):
            return "render"
        return "advance"

    if game.get("phase") == "DAY_VOTE_PK_NEXT_SPEECH":
        if game.get("post_death_choice_pending"):
            set_post_death_choice_request(game)
            return "render"
        queue = game.get("day_vote", {}).get("pk_speech_queue") or []
        if not queue:
            game["phase"] = "DAY_VOTE_PK_VOTE"
            game["pending_request"] = None
            append_unique(game.setdefault("public_log", []), "PK发言结束，进入PK投票。")
            return "advance"
        if int(queue[0]) == int(game.get("user_seat") or 0) and not game.get("user_spectating"):
            game["pending_request"] = {
                "kind": "day_pk_speech",
                "actor": "user",
                "seat": game["user_seat"],
                "prompt": "你进入PK台。请发表PK发言。",
            }
            return "render"
        game["phase"] = "DAY_VOTE_PK_AI_SPEECH"
        return "actors" if prepare_current_day_pk_speech(game) else "advance"

    if game.get("phase") == "DAY_VOTE_PK_AI_SPEECH":
        return "actors" if prepare_current_day_pk_speech(game) else "advance"

    if game.get("phase") == "DAY_VOTE_PK_VOTE":
        user_seat = int(game.get("user_seat") or 0)
        voters = [
            int(seat)
            for seat in game.get("day_vote", {}).get("pk_voters") or []
            if can_player_vote(game, int(seat))
        ]
        game.setdefault("day_vote", {})["pk_voters"] = voters
        if not game.get("user_spectating") and user_seat in voters and not has_vote(game, user_seat, "day_pk_vote"):
            set_user_day_pk_vote_request(game)
            return "render"
        game["phase"] = "DAY_VOTE_PK_AI_VOTE"
        return "advance"

    if game.get("phase") == "DAY_VOTE_PK_AI_VOTE":
        if prepare_day_pk_ai_votes(game):
            return "actors"
        game["phase"] = "DAY_VOTE_PK_RESOLVE"
        return "advance"

    if game.get("phase") == "DAY_VOTE_PK_RESOLVE":
        resolve_day_pk_vote(game)
        if check_win_condition(game):
            return "render"
        return "advance"

    if game.get("phase") == "LAST_WORDS_NEXT":
        queue = game.get("last_words_queue") or []
        if not queue:
            if game.get("death_followup_pending"):
                game["death_followup_pending"] = False
                game["phase"] = "SHERIFF_BADGE_CHECK"
                game["pending_request"] = None
                return "advance"
            if check_win_condition(game):
                return "render"
            if game.get("post_death_choice_pending"):
                set_post_death_choice_request(game)
                return "render"
            game["phase"] = str(game.get("after_last_words_phase") or "DAY_END")
            game["pending_request"] = None
            return "advance"
        if int(queue[0]) == int(game.get("user_seat") or 0) and not game.get("user_spectating"):
            game["pending_request"] = {
                "kind": "last_words",
                "actor": "user",
                "seat": game["user_seat"],
                "prompt": "你已出局。请发表遗言。",
            }
            return "render"
        game["phase"] = "LAST_WORDS_AI"
        return "actors" if prepare_current_ai_last_words(game) else "advance"

    if game.get("phase") == "LAST_WORDS_AI":
        return "actors" if prepare_current_ai_last_words(game) else "advance"

    if game.get("phase") == "DAY_END":
        if check_win_condition(game):
            return "render"
        append_unique(game.setdefault("public_log", []), "白天结束，进入下一晚。")
        game["day"] = int(game.get("day") or 1) + 1
        game["night"] = {}
        game["dead"] = []
        game["day_speech_queue"] = []
        game["phase"] = "NIGHT_WOLF"
        return "advance"

    return "render"


_build_actor_request = build_actor_request
_night_targets = night_targets
_record_seer_check = record_seer_check
_set_user_request = set_user_request
_prepare_night_actor_requests = prepare_night_actor_requests
_advance_night_stage = advance_night_stage
_prepare_election_ai_choices = prepare_election_ai_choices
_prepare_current_ai_speech = prepare_current_ai_speech
_has_vote = has_vote
_record_vote = record_vote
_set_user_election_vote_request = set_user_election_vote_request
_prepare_election_ai_votes = prepare_election_ai_votes
_prepare_current_election_pk_speech = prepare_current_election_pk_speech
_set_user_election_pk_vote_request = set_user_election_pk_vote_request
_prepare_election_pk_ai_votes = prepare_election_pk_ai_votes
_build_day_speech_order = build_day_speech_order
_apply_day_speech_order = apply_day_speech_order
_apply_day_speech_direction = apply_day_speech_direction
_can_self_explode = can_self_explode
_apply_self_explosion = apply_self_explosion
_prepare_current_day_speech = prepare_current_day_speech
_set_user_day_vote_request = set_user_day_vote_request
_prepare_day_ai_votes = prepare_day_ai_votes
_prepare_current_day_pk_speech = prepare_current_day_pk_speech
_set_user_day_pk_vote_request = set_user_day_pk_vote_request
_prepare_day_pk_ai_votes = prepare_day_pk_ai_votes
_prepare_current_ai_last_words = prepare_current_ai_last_words
_sheriff_badge_targets = sheriff_badge_targets
_set_user_sheriff_badge_request = set_user_sheriff_badge_request
_prepare_ai_sheriff_badge = prepare_ai_sheriff_badge
_transfer_sheriff_badge = transfer_sheriff_badge
_prepare_next_sheriff_interrupt = prepare_next_sheriff_interrupt
_hunter_shot_targets = death_shot_targets
_set_user_hunter_shot_request = set_user_death_shot_request
_prepare_ai_hunter_shot = prepare_ai_death_shot
_death_shot_targets = death_shot_targets
_death_shot_kind = death_shot_kind
_set_user_death_shot_request = set_user_death_shot_request
_prepare_ai_death_shot = prepare_ai_death_shot
_prepare_next_hunter_interrupt = prepare_next_hunter_interrupt
_vote_winners = vote_winners
_vote_count_summary = vote_count_summary
_exile_player = exile_player
_begin_day_vote_pk = begin_day_vote_pk
_resolve_day_vote = resolve_day_vote
_resolve_day_pk_vote = resolve_day_pk_vote
_append_identity_review = append_identity_review
_finish_game = finish_game
_check_win_condition = check_win_condition
_resolve_election_vote = resolve_election_vote
_resolve_election_pk_vote = resolve_election_pk_vote
_withdraw_from_sheriff_campaign = withdraw_from_sheriff_campaign
_apply_actor_outputs = apply_actor_outputs
_build_election_lists = build_election_lists
_calculate_night_deaths = calculate_night_deaths
_target_from_text = target_from_text
_apply_user_input = apply_user_input
_advance_state_machine = advance_state_machine
