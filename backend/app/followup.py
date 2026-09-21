"""봉인 선택의 결과를 이어받는 후속 사건. 상태 변경은 서버에서만 수행한다."""

from typing import Any

from .dice import Roller

COMMANDS = {
    "후속 사건 시작": ("start_followup", "aftermath"),
    "창고의 통행세 장부 확보": ("followup_evidence", "tax_ledger"),
    "오렌의 통행세 증언 기록": ("followup_evidence", "oren_testimony"),
    "창고에서 피난 보급품 확보": ("followup_evidence", "refugee_supplies"),
    "오렌에게 안전한 피난로 확인": ("followup_evidence", "safe_route"),
    "몰래 통행세 장부 복사": ("followup_check", "tax_ledger"),
    "오렌 설득해 증언 확보": ("followup_check", "oren_testimony"),
    "몰래 피난 보급품 확보": ("followup_check", "refugee_supplies"),
    "오렌 설득해 피난로 확인": ("followup_check", "safe_route"),
    "하를란에게 감사 증거 제출": ("resolve_followup", "law"),
    "시장에서 통행세 증거 공개": ("resolve_followup", "mercy"),
    "피난민과 함께 성문 통과": ("resolve_followup", "exile"),
}
BRANCHES = {
    "law": {
        "title": "경비대의 감사",
        "objective": "창고 장부와 시장의 오렌 증언을 모아 하를란에게 제출하세요.",
        "evidence": ("tax_ledger", "oren_testimony"),
        "destination": "greyhaven_inn",
        "opening": "Harlan: 봉인은 돌아왔지만 통행세 장부에 의문이 남았소. 증거를 모아 주시오.",
        "resolution": "장부와 증언이 일치했다. 하를란은 징수를 잠정 중단하고 감사를 열었다.",
        "tax_collection": "suspended",
        "refugees": "waiting",
        "ally": "npc_harlan",
    },
    "mercy": {
        "title": "광장의 목소리",
        "objective": "창고 장부와 오렌의 증언을 모아 시장에서 부당한 통행세를 공개하세요.",
        "evidence": ("tax_ledger", "oren_testimony"),
        "destination": "market",
        "opening": "Mira: 봉인만 바꿔서는 부족해요. 장부와 증인을 모아 사람들 앞에 진실을 밝혀요.",
        "resolution": "장부와 증언을 공개하자 상인들이 항의했다. 통행세 공개 분쟁이 시작됐다.",
        "tax_collection": "contested",
        "refugees": "waiting",
        "ally": "npc_oren",
    },
    "exile": {
        "title": "성문 밖의 사람들",
        "objective": "창고에서 보급품을 확보하고 오렌에게 안전한 길을 물은 뒤 피난민을 인도하세요.",
        "evidence": ("refugee_supplies", "safe_route"),
        "destination": "market",
        "opening": "성문 밖 피난민들이 도움을 청했다. 함께 떠날 준비를 위해 시장으로 돌아왔다.",
        "resolution": "보급품과 안전한 길을 확보해 피난민을 인도했다. 도시의 징수 문제는 남았다.",
        "tax_collection": "unchanged",
        "refugees": "evacuated",
        "ally": "npc_oren",
    },
}
EVIDENCE = {
    "tax_ledger": (
        "warehouse",
        "통행세 장부",
        "창고 장부에서 신고된 금액보다 많은 징수 기록을 찾았다.",
    ),
    "oren_testimony": (
        "market",
        "오렌의 증언",
        "Oren은 장부 날짜에 이중으로 통행세를 냈다고 증언했다.",
    ),
    "refugee_supplies": (
        "warehouse",
        "피난 보급품",
        "창고의 구호 물품 담당자에게 피난민용 식량과 담요를 받았다.",
    ),
    "safe_route": (
        "market",
        "안전한 피난로",
        "Oren이 침수되지 않은 동쪽 길과 피난 행렬의 합류 지점을 알려 주었다.",
    ),
}


def available_actions(state: dict[str, Any]) -> list[str]:
    branch = state.get("quest", {}).get("ending")
    if branch not in BRANCHES:
        return []
    quest = state.get("followup")
    if quest is None:
        return ["후속 사건 시작"]
    if quest.get("status") != "active" or quest.get("branch") != branch:
        return []
    config = BRANCHES[branch]
    evidence = quest.get("evidence", [])
    actions = []
    for label, (intent, target) in COMMANDS.items():
        if intent in {"followup_evidence", "followup_check"} and target in config["evidence"]:
            if target not in evidence and state.get("location_id") == EVIDENCE[target][0]:
                if intent != "followup_check" or target not in quest.get("attempts", {}):
                    actions.append(label)
        elif intent == "resolve_followup" and target == branch:
            if (
                set(config["evidence"]) <= set(evidence)
                and state.get("location_id") == config["destination"]
            ):
                actions.append(label)
    return actions


def evidence_minutes(state: dict[str, Any], target: str) -> int:
    attempt = state.get("followup", {}).get("attempts", {}).get(target)
    return 25 if attempt and not attempt["success"] else 15


def check(state: dict[str, Any], target: str, roller: Roller) -> tuple[str, int, dict]:
    """빠르지만 실패 가능한 경로. 검사 후에만 주사위를 한 번 굴린다."""
    if ("followup_check", target) not in {COMMANDS[label] for label in available_actions(state)}:
        raise ValueError("이미 시도했거나 현재 선택할 수 없는 판정입니다.")
    social = EVIDENCE[target][0] == "market"
    skill = "persuasion" if social else "stealth"
    bonus = int(state["player"].get(f"{skill}_bonus", 3 if social else 5))
    roll = roller.roll(20)
    success = roll + bonus >= 14
    attempt = {"skill": skill, "roll": roll, "bonus": bonus, "dc": 14, "success": success}
    quest = state["followup"]
    quest.setdefault("attempts", {})[target] = attempt
    if success:
        quest["evidence"].append(target)
        narrative = ("설득에 성공했다. " if social else "눈에 띄지 않고 접근했다. ") + EVIDENCE[
            target
        ][2]
    else:
        complication = "oren_reluctant" if social else "warehouse_alerted"
        quest.setdefault("complications", []).append(complication)
        narrative = (
            "Oren이 경계하며 대화를 멈췄다. "
            if social
            else "발소리를 들킨 뒤 창고 경계가 강화됐다. "
        ) + "같은 시도는 반복할 수 없다. 정식 절차로 25분을 들이면 필요한 것을 확보할 수 있다."
        if social:
            state["npc_relationships"]["npc_oren"] = "wary"
            for npc in state["npcs"]:
                if npc["id"] == "npc_oren":
                    npc["disposition"] = "wary"
    if social:
        state["npc_knowledge"]["npc_oren"]["facts"][f"persuasion_{target}"] = {
            "text": "플레이어가 도움을 설득했고 나는 협조했다."
            if success
            else "플레이어의 설득을 거절했다.",
            "source": "witnessed_event",
            "certainty": "known",
            "shareable": True,
        }
    return narrative, 2 if success else 5, attempt


def apply(state: dict[str, Any], intent: str, targets: tuple[str, ...]) -> str:
    """호출자가 복제한 상태만 변경하며 허용된 명령을 다시 검증한다."""
    if intent == "followup_check":
        raise ValueError("판정 행동은 주사위 검증 경로로 처리해야 합니다.")
    allowed = {COMMANDS[label] for label in available_actions(state)}
    if len(targets) != 1 or (intent, targets[0]) not in allowed:
        raise ValueError("현재 후속 사건에서 실행할 수 없는 행동입니다.")
    branch = state["quest"]["ending"]
    config = BRANCHES[branch]
    if intent == "start_followup":
        state["followup"] = {
            "id": "seal_aftermath",
            "branch": branch,
            "title": config["title"],
            "objective": config["objective"],
            "status": "active",
            "evidence": [],
            "resolution": None,
            "attempts": {},
            "complications": [],
        }
        state["encounter_enemy_id"] = None
        return config["opening"]
    quest = state["followup"]
    if intent == "followup_evidence":
        quest["evidence"].append(targets[0])
        return EVIDENCE[targets[0]][2]
    quest.update(
        status="completed", resolution=config["resolution"], objective="후속 사건을 해결했습니다."
    )
    state["world_consequences"] = {
        "tax_collection": config["tax_collection"],
        "refugees": config["refugees"],
    }
    ally = config["ally"]
    state["npc_relationships"][ally] = "trusting"
    for npc in state.get("npcs", []):
        if npc["id"] == ally:
            npc["disposition"] = "trusting"
    # 결과를 직접 함께한 인물에게만 지식을 기록한다. 부재 NPC에게 전파하지 않는다.
    state["npc_knowledge"][ally]["facts"]["seal_aftermath"] = {
        "text": config["resolution"],
        "source": "witnessed_event",
        "certainty": "known",
        "shareable": True,
    }
    return config["resolution"]
