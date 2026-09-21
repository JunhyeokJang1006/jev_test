"""봉인 선택의 결과를 이어받는 후속 사건. 상태 변경은 서버에서만 수행한다."""

from typing import Any

COMMANDS = {
    "후속 사건 시작": ("start_followup", "aftermath"),
    "창고의 통행세 장부 확보": ("followup_evidence", "tax_ledger"),
    "오렌의 통행세 증언 기록": ("followup_evidence", "oren_testimony"),
    "창고에서 피난 보급품 확보": ("followup_evidence", "refugee_supplies"),
    "오렌에게 안전한 피난로 확인": ("followup_evidence", "safe_route"),
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
        if intent == "followup_evidence" and target in config["evidence"]:
            if target not in evidence and state.get("location_id") == EVIDENCE[target][0]:
                actions.append(label)
        elif intent == "resolve_followup" and target == branch:
            if (
                set(config["evidence"]) <= set(evidence)
                and state.get("location_id") == config["destination"]
            ):
                actions.append(label)
    return actions


def apply(state: dict[str, Any], intent: str, targets: tuple[str, ...]) -> str:
    """호출자가 복제한 상태만 변경하며 허용된 명령을 다시 검증한다."""
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
