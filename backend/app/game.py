"""주사위 주입으로 재현 가능한 서버 권위 판정. 간소화된 자체 전투 규칙."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any

from . import progression, tactical, world_effects
from .dice import Dice, Roller
from .memory import record_episode
from .world import COMMANDS, advance_time, available_actions, prepare, resolve_world


@dataclass(frozen=True)
class ActionProposal:
    intent: str
    action_type: str
    target_ids: tuple[str, ...]
    skill: str | None
    difficulty_band: str | None


@dataclass(frozen=True)
class TurnOutcome:
    event_type: str
    event_payload: dict[str, Any]
    state: dict[str, Any]
    narrative: str
    dice: dict[str, int | str]


def interpret_mock(text: str) -> ActionProposal:
    normalized = text.strip().lower()
    command = next(
        (value for label, value in COMMANDS.items() if label.lower() == normalized), None
    )
    if command is not None:
        intent, target = command
        return ActionProposal(intent, "exploration", (target,), None, None)
    stealth_words = ("숨", "잠입", "은신", "그림자", "몰래")
    if any(word in normalized for word in stealth_words):
        return ActionProposal(
            "hide_beside_door", "exploration", ("door_inn",), "stealth", "moderate"
        )
    if ("고블린" in normalized or "goblin" in normalized) and any(
        word in normalized for word in ("공격", "검을", "베어", "휘두르", "찌른", "attack")
    ):
        target = (
            "goblin_002"
            if any(word in normalized for word in ("두 번째", "두번째", "goblin_002"))
            else "goblin_001"
        )
        return ActionProposal("basic_attack", "attack", (target,), None, None)
    return ActionProposal("describe_action", "exploration", (), None, None)


def resolve_action(
    state: dict[str, Any], proposal: ActionProposal, *, roller: Roller | None = None
) -> TurnOutcome:
    outcome = _resolve_action(deepcopy(state), proposal, roller=roller)
    gained = progression.reward(state, outcome.state)
    payload, narrative = dict(outcome.event_payload), outcome.narrative
    if gained:
        payload["xp_gained"] = gained
        narrative += f" 경험치 {gained}을 얻었다."
    notice = world_effects.advance(outcome.state)
    if notice:
        payload["world_notice"] = notice
        narrative += " " + notice
        outcome.state.setdefault("journal", []).append(
            {
                "action": "world_notice",
                "target": "market",
                "text": notice,
                "day": outcome.state["day"],
                "time": outcome.state["time"],
            }
        )
        if proposal.intent == "talk" and len(proposal.target_ids) == 1:
            world_effects.notice_for_npc(outcome.state, proposal.target_ids[0])
    return replace(outcome, event_payload=payload, narrative=narrative)


def _resolve_action(
    state: dict[str, Any], proposal: ActionProposal, *, roller: Roller | None = None
) -> TurnOutcome:
    roller = roller if roller is not None else Dice()
    next_state = dict(state)
    if state.get("player", {}).get("hp", 0) <= 0:
        raise ValueError("전투 불능 상태입니다. 이전 저장을 복원해 주세요.")
    if state.get("quest", {}).get("ending"):
        allowed = {COMMANDS[label] for label in available_actions(state) if label in COMMANDS}
        if (
            len(proposal.target_ids) != 1
            or (proposal.intent, proposal.target_ids[0]) not in allowed
        ):
            raise ValueError("이전 사건은 끝났습니다. 현재 후속 사건의 행동을 선택해 주세요.")
    if proposal.intent in {command[0] for command in tactical.COMMANDS.values()}:
        outcome = tactical.resolve(state, proposal.intent, proposal.target_ids, roller=roller)
        result = outcome["state"]
        previous = int(state.get("combat", {}).get("elapsed_seconds", 0))
        elapsed = max(0, int(result.get("combat", {}).get("elapsed_seconds", 0)) - previous)
        before = int(state.get("combat_seconds", 0))
        result["combat_seconds"] = before + elapsed
        advance_time(result, (before + elapsed) // 60 - before // 60)
        result.setdefault("journal", []).append(
            {
                "action": proposal.intent,
                "target": "combat",
                "text": outcome["narrative"],
                "day": result["day"],
                "time": result["time"],
            }
        )
        return TurnOutcome(**outcome)
    if proposal.intent == "deceive_mayor":
        if proposal.target_ids != ("npc_harlan",) or not any(
            npc.get("id") == "npc_harlan" for npc in state.get("npcs", [])
        ):
            raise ValueError("현재 장소에 하를란이 없습니다.")
        if state.get("combat", {}).get("active"):
            raise ValueError("전투 중에는 이 대화를 할 수 없습니다.")
        result = prepare(state)
        claims = result["npc_knowledge"]["npc_harlan"]["claims"]
        previous = claims.get("mayor_sent_player")
        if previous:
            return TurnOutcome(
                "NPC_CLAIM_RECALLED",
                {"intent": proposal.intent, "target_id": "npc_harlan", "resolved": True},
                result,
                "Harlan: 그 주장은 이미 들었소. 새로운 증거가 없다면 내 판단은 같소.",
                {"outcome": "no_check_required"},
            )
        roll = roller.roll(20)
        bonus = int(result["player"].get("deception_bonus", 3))
        success = roll + bonus >= 14
        claims["mayor_sent_player"] = {
            "reaction": "believed" if success else "doubted",
            "source": "player_assertion",
            "verified": False,
            "roll": roll,
            "bonus": bonus,
            "dc": 14,
        }
        disposition = "trusting" if success else "suspicious"
        for npc in result["npcs"]:
            if npc["id"] == "npc_harlan":
                npc["disposition"] = disposition
        result["npc_relationships"]["npc_harlan"] = disposition
        advance_time(result, 1)
        record_episode(result, "npc_harlan", "mayor_claim")
        narrative = (
            "Harlan: 시장님의 사절이라고? 일단 믿겠소. 아직 확인은 하지 못했지만."
            if success
            else "Harlan: 시장님이 보냈다는 말만으로는 믿을 수 없소."
        )
        result["journal"].append(
            {
                "action": "deceive_mayor",
                "target": "npc_harlan",
                "text": narrative,
                "day": result["day"],
                "time": result["time"],
            }
        )
        return TurnOutcome(
            "NPC_CLAIM_RESOLVED",
            {
                "intent": proposal.intent,
                "target_id": "npc_harlan",
                "skill": "deception",
                "roll": roll,
                "bonus": bonus,
                "dc": 14,
                "success": success,
                "rule_id": "greyhaven-mayor-deception-v1",
            },
            result,
            narrative,
            {
                "roll": roll,
                "bonus": bonus,
                "total": roll + bonus,
                "dc": 14,
                "outcome": "success" if success else "failure",
            },
        )
    world_outcome = resolve_world(state, proposal.intent, proposal.target_ids, roller=roller)
    if world_outcome is not None:
        return TurnOutcome(**world_outcome)
    if proposal.intent != "hide_beside_door":
        return TurnOutcome(
            "PLAYER_ACTION_RECORDED",
            {"intent": proposal.intent, "resolved": False},
            next_state,
            "행동의 의도는 이해했지만, 아직 이 행동을 판정할 규칙이 준비되지 않았다. "
            "어떻게 하겠는가?",
            {"outcome": "no_state_change"},
        )
    if state.get("location_id") != "greyhaven_inn" or "door_inn" not in state.get(
        "nearby_object_ids", []
    ):
        raise ValueError("현재 장면에서 해당 은신 대상을 찾을 수 없습니다.")
    if proposal.target_ids != ("door_inn",):
        raise ValueError("은신 대상이 현재 장면과 일치하지 않습니다.")
    if state.get("combat", {}).get("active"):
        raise ValueError("현재 전투에서는 공격 행동을 선택해야 합니다.")
    roll, bonus, dc = roller.roll(20), int(state["player"].get("stealth_bonus", 5)), 14
    total = roll + bonus
    success = total >= dc
    next_state["hidden"] = success
    return TurnOutcome(
        "PLAYER_STEALTH_CHECK",
        {
            "intent": proposal.intent,
            "skill": "stealth",
            "dc": dc,
            "roll": roll,
            "bonus": bonus,
            "success": success,
            "rule_id": "greyhaven-door-stealth-v2",
        },
        next_state,
        (
            "그림자 속으로 몸을 낮추자 젖은 외투 자락이 문틀에 스친다. "
            "경비병은 발소리를 듣지 못한 채 지나간다."
            if success
            else "몸을 숨기려는 순간 바닥의 낡은 판자가 삐걱인다. 경비병이 이쪽을 돌아본다."
        ),
        {
            "roll": roll,
            "bonus": bonus,
            "total": total,
            "dc": dc,
            "outcome": "success" if success else "failure",
        },
    )
