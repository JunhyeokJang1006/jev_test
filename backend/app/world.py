"""Greyhaven 왕실 봉인 모험: 공개 장면과 서버 검증 명령."""

from copy import deepcopy
from typing import Any

from . import followup
from .dice import Dice, Roller
from .memory import initialize_knowledge, record_episode

LOCATIONS = {
    "greyhaven_inn": {
        "name": "Greyhaven Inn",
        "exits": ["market"],
        "npcs": [("npc_harlan", "Harlan"), ("npc_mira", "Mira")],
    },
    "market": {
        "name": "빗속의 시장",
        "exits": ["greyhaven_inn", "warehouse"],
        "npcs": [("npc_oren", "Oren")],
    },
    "warehouse": {"name": "강변 창고", "exits": ["market"], "npcs": []},
}
COMMANDS = {
    **followup.COMMANDS,
    "하를란에게 시장이 보냈다고 거짓말": ("deceive_mayor", "npc_harlan"),
    "시장님이 직접 저를 보냈습니다.": ("deceive_mayor", "npc_harlan"),
    "여관으로 이동": ("travel", "greyhaven_inn"),
    "시장으로 이동": ("travel", "market"),
    "창고로 이동": ("travel", "warehouse"),
    "주변 조사": ("investigate", "scene"),
    "하를란과 대화": ("talk", "npc_harlan"),
    "미라와 대화": ("talk", "npc_mira"),
    "오렌과 대화": ("talk", "npc_oren"),
    "봉인 회수": ("take_seal", "royal_seal"),
    "하를란에게 봉인 반환": ("finish_quest", "law"),
    "미라에게 봉인 전달": ("finish_quest", "mercy"),
    "봉인을 가지고 도시 떠나기": ("finish_quest", "exile"),
}


def advance_time(state: dict[str, Any], minutes: int) -> None:
    state["elapsed_minutes"] = state.get("elapsed_minutes", 0) + minutes
    total = 21 * 60 + 36 + state["elapsed_minutes"]
    state["day"] = 1 + total // (24 * 60)
    state["time"] = f"{total // 60 % 24:02}:{total % 60:02}"


def prepare(state: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(state)
    initialize_knowledge(result)
    result.setdefault(
        "quest",
        {
            "id": "royal_seal",
            "title": "도난당한 왕실 봉인",
            "status": "active",
            "clues": [],
            "ending": None,
        },
    )
    result.setdefault("inventory", [])
    result.setdefault("journal", [])
    result.setdefault("npc_memories", {})
    relationships = result.setdefault("npc_relationships", {})
    for npc in result.get("npcs", []):
        relationships[npc["id"]] = npc.get("disposition", "neutral")
    result.setdefault("elapsed_minutes", 0)
    return result


def available_actions(state: dict[str, Any]) -> list[str]:
    if state.get("player", {}).get("hp", 0) <= 0:
        return []
    if state.get("quest", {}).get("ending"):
        actions = followup.available_actions(state)
        if state.get("followup", {}).get("status") == "active":
            location = LOCATIONS.get(state.get("location_id"), {})
            for label, (intent, target) in COMMANDS.items():
                if intent == "travel" and target in location.get("exits", []):
                    actions.append(label)
                if intent == "talk" and target in {npc[0] for npc in location.get("npcs", [])}:
                    actions.append(label)
        return actions
    if state.get("combat", {}).get("active"):
        return ["고블린을 공격한다"]
    location = LOCATIONS.get(state.get("location_id"))
    if location is None:
        return []
    actions = ["주변 조사"]
    for label, (intent, target) in COMMANDS.items():
        if intent == "travel" and target in location["exits"]:
            actions.append(label)
        if intent == "talk" and target in {npc[0] for npc in location["npcs"]}:
            actions.append(label)
        if intent == "deceive_mayor" and label.startswith("하를란") and location.get("npcs"):
            if target in {npc[0] for npc in location["npcs"]}:
                actions.append(label)
    quest = state.get("quest", {})
    if state.get("location_id") == "warehouse" and "seal_cache" in quest.get("clues", []):
        if "royal_seal" not in state.get("inventory", []):
            actions.append("봉인 회수")
    if "royal_seal" in state.get("inventory", []):
        if state.get("location_id") == "greyhaven_inn":
            actions.extend(["하를란에게 봉인 반환", "미라에게 봉인 전달"])
        if state.get("location_id") == "market":
            actions.append("봉인을 가지고 도시 떠나기")
    return actions


def resolve_world(
    state: dict[str, Any], intent: str, targets: tuple[str, ...], *, roller: Roller | None = None
) -> dict | None:
    followup_intents = {command[0] for command in followup.COMMANDS.values()}
    if (
        intent
        not in {"travel", "talk", "investigate", "take_seal", "finish_quest"} | followup_intents
    ):
        return None
    if len(targets) != 1:
        raise ValueError("행동 대상은 하나여야 합니다.")
    if state.get("combat", {}).get("active"):
        raise ValueError("전투를 마친 뒤 이동하거나 대화할 수 있습니다.")
    result = prepare(state)
    quest = result["quest"]
    if quest["ending"] and (intent, targets[0]) not in {
        COMMANDS[label] for label in available_actions(state) if label in COMMANDS
    }:
        raise ValueError("이전 사건은 끝났습니다. 현재 후속 사건의 행동을 선택해 주세요.")
    location_id = result["location_id"]
    location = LOCATIONS.get(location_id)
    if location is None:
        raise ValueError("알 수 없는 현재 위치입니다.")
    target = targets[0]
    minutes = 1
    clue = None
    check_result = None
    if intent == "followup_check":
        narrative, minutes, check_result = followup.check(
            result, target, roller if roller is not None else Dice()
        )
    elif intent in followup_intents:
        if intent == "followup_evidence":
            minutes = followup.evidence_minutes(result, target)
        narrative = followup.apply(result, intent, targets)
    elif intent == "travel":
        if target not in location["exits"]:
            raise ValueError("현재 위치에서 바로 이동할 수 없는 장소입니다.")
        destination = LOCATIONS[target]
        result.update(
            location_id=target,
            location_name=destination["name"],
            hidden=False,
            nearby_object_ids=["door_inn"] if target == "greyhaven_inn" else [],
            encounter_enemy_id=None,
            npcs=[
                {
                    "id": key,
                    "name": name,
                    "disposition": result["npc_relationships"].get(key, "neutral"),
                }
                for key, name in destination["npcs"]
            ],
        )
        result.pop("combat", None)
        minutes = 5
        narrative = f"{destination['name']}에 도착했다. " + (
            "후속 사건의 목표와 가능한 행동을 확인하자."
            if quest["ending"]
            else "주변을 조사하거나 사람들에게 물어볼 수 있다."
        )
    elif intent == "talk":
        if target not in {npc[0] for npc in location["npcs"]}:
            raise ValueError("그 인물은 현재 장소에 없습니다.")
        if quest["ending"]:
            narrative = (
                f"{dict(location['npcs'])[target]}: 다음 일을 의논하러 왔군요. "
                "제가 직접 아는 일부터 이야기하겠습니다."
            )
            advance_time(result, minutes)
            record_episode(result, target, "aftermath_discussion")
            result["journal"].append(
                {
                    "action": intent,
                    "target": target,
                    "text": narrative,
                    "day": result["day"],
                    "time": result["time"],
                }
            )
            return {
                "event_type": "WORLD_ACTION_RESOLVED",
                "event_payload": {
                    "intent": intent,
                    "target_id": target,
                    "minutes": minutes,
                    "rule_id": "greyhaven-aftermath-v1",
                },
                "state": result,
                "narrative": narrative,
                "dice": {"outcome": "no_check_required"},
            }
        memories = result["npc_memories"].setdefault(target, [])
        repeated = "seal_discussed" in memories
        if not repeated:
            memories.append("seal_discussed")
        if target == "npc_harlan":
            narrative = "Harlan: 왕실 봉인이 사라졌소. 시장에서 목격자를 찾아 봉인을 돌려주시오."
        elif target == "npc_mira":
            clue = "mira_appeal"
            narrative = "Mira: 그 봉인으로 부당한 통행세가 걷히고 있어요. 찾으면 제게 가져다주세요."
        else:
            clue = "warehouse_trail"
            narrative = "Oren: 붉은 천으로 싼 상자를 강변 창고로 옮기는 걸 봤소."
        if repeated:
            narrative = "이전에 봉인 이야기를 나눴던 것을 기억하며 고개를 끄덕인다. " + narrative
        claim = result["npc_knowledge"][target]["claims"].get("mayor_sent_player")
        if claim:
            narrative = (
                "당신이 시장의 사절이라는 주장을 믿고 있지만 아직 확인하지 못했다. "
                if claim["reaction"] == "believed"
                else "당신이 시장의 사절이라는 주장을 여전히 의심한다. "
            ) + narrative
    elif intent == "investigate":
        if target != "scene":
            raise ValueError("조사 대상이 현재 장면과 일치하지 않습니다.")
        if location_id == "greyhaven_inn":
            clue = "red_cloth"
            narrative = "여관 문턱에서 붉은 천 조각과 시장 쪽으로 이어진 진흙 발자국을 찾았다."
        elif location_id == "market":
            clue = "warehouse_trail"
            narrative = "수레 자국이 강변 창고까지 이어진다. 상인 Oren도 그 방향을 가리킨다."
        elif "warehouse_trail" in quest["clues"]:
            clue = "seal_cache"
            narrative = "수레 자국 끝의 상자에서 왕실 문장이 찍힌 봉인을 발견했다. 회수할 수 있다."
        else:
            narrative = "창고에는 상자가 너무 많다. 시장에서 운반 경로를 확인하면 도움이 될 것이다."
    elif intent == "take_seal":
        if (
            target != "royal_seal"
            or location_id != "warehouse"
            or "seal_cache" not in quest["clues"]
        ):
            raise ValueError("먼저 창고에서 봉인의 위치를 찾아야 합니다.")
        if "royal_seal" in result["inventory"]:
            raise ValueError("봉인은 이미 소지하고 있습니다.")
        result["inventory"].append("royal_seal")
        quest["status"] = "recovered"
        narrative = "왕실 봉인을 회수했다. 하를란에게 반환하거나 미라에게 전달할 수 있다."
    else:
        endings = {
            "law": (
                "greyhaven_inn",
                "왕실의 신뢰",
                "하를란에게 봉인을 반환했다. 경비대는 당신의 도움을 기록했다.",
            ),
            "mercy": (
                "greyhaven_inn",
                "새로운 약속",
                "미라에게 봉인을 맡겼다. 그녀는 부당한 통행세를 끝내겠다고 약속했다.",
            ),
            "exile": (
                "market",
                "봉인의 방랑자",
                "봉인을 품고 도시를 떠났다. 그 힘을 어떻게 쓸지는 당신의 몫이다.",
            ),
        }
        if target not in endings or "royal_seal" not in result["inventory"]:
            raise ValueError("봉인을 회수한 뒤 결말을 선택할 수 있습니다.")
        required_location, title, narrative = endings[target]
        if location_id != required_location:
            raise ValueError("이 결말은 해당 인물 또는 출구가 있는 장소에서 선택해야 합니다.")
        if target != "exile":
            result["inventory"].remove("royal_seal")
        quest.update(status="completed", ending=target, ending_title=title)
    if clue and clue not in quest["clues"]:
        quest["clues"].append(clue)
    advance_time(result, minutes)
    if intent == "talk":
        record_episode(result, target, "seal_discussion")
    if intent == "followup_check" and target in {"oren_testimony", "safe_route"}:
        record_episode(result, "npc_oren", "aftermath_persuasion")
    result["journal"].append(
        {
            "action": intent,
            "target": target,
            "text": narrative,
            "day": result["day"],
            "time": result["time"],
        }
    )
    return {
        "event_type": "WORLD_ACTION_RESOLVED",
        "event_payload": {
            **(check_result or {}),
            "intent": intent,
            "target_id": target,
            "clue": clue,
            "minutes": minutes,
            "ending": quest["ending"],
            "rule_id": "greyhaven-aftermath-v1"
            if state.get("quest", {}).get("ending")
            else "greyhaven-seal-v1",
        },
        "state": result,
        "narrative": narrative,
        "dice": (
            {
                "roll": check_result["roll"],
                "bonus": check_result["bonus"],
                "total": check_result["roll"] + check_result["bonus"],
                "dc": check_result["dc"],
                "outcome": "success" if check_result["success"] else "failure",
            }
            if check_result
            else {"outcome": "no_check_required"}
        ),
    }
