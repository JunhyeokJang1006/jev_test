"""꺼진 망루: 서버가 검증하는 준비, 통과, 탐색, 선택, 귀환 규칙."""

from typing import Any

from .dice import Roller

COMMANDS = {
    "꺼진 망루의 전령 의뢰 수락": ("start_expedition", "watchtower"),
    "경비대 통행증 확보": ("expedition_aid", "law"),
    "상인 소개장 확보": ("expedition_aid", "mercy"),
    "피난로 경험으로 길 준비": ("expedition_aid", "exile"),
    "야영 보급품 1개로 구조 로프 준비": ("expedition_prepare", "rope"),
    "경비대 통행증으로 성문 통과": ("expedition_passage", "permit"),
    "성문 경비 설득 (DC 14, 한 번)": ("expedition_passage", "persuasion"),
    "성문으로 잠입 (DC 14, 한 번)": ("expedition_passage", "stealth"),
    "성문 보수 작업을 돕고 통과 (20분)": ("expedition_passage", "repair"),
    "망루에서 전령 위치 조사 (5분)": ("expedition_clue", "messenger_location"),
    "망루에서 문서 위치 조사 (5분)": ("expedition_clue", "document_location"),
    "망루 계단 보강 (10분)": ("expedition_approach", "stairs"),
    "몰래 망루 상층 진입 (DC 14, 한 번)": ("expedition_approach", "stealth"),
    "전령 구조 우선 확정 (문서 포기, 5분)": ("resolve_expedition", "rescue"),
    "문서 확보 우선 확정 (전령 구조 포기, 5분)": ("resolve_expedition", "documents"),
    "로프로 전령과 문서 모두 확보 확정 (5분)": ("resolve_expedition", "both"),
    "오렌에게 망루 결과 보고 (25골드)": ("report_expedition", "oren"),
}
AIDS = {"law": "guard_permit", "mercy": "merchant_introduction", "exile": "refugee_route"}
CLUES = {"messenger_location", "document_location"}
FIELDS = (
    "id",
    "title",
    "branch",
    "status",
    "stage",
    "objective",
    "started_at",
    "deadline_at",
    "aid",
    "clues",
    "passage",
    "approach",
    "choice",
    "resolution",
)
RESOLUTIONS = {
    "rescue": "전령을 구했지만 봉인 문서는 무너진 망루 아래 사라졌다.",
    "documents": "봉인 문서를 확보했지만 전령을 구조할 기회를 놓쳤다.",
    "both": "준비한 로프와 두 위치 단서 덕분에 붕괴 전에 전령과 봉인 문서를 모두 구했다.",
}


def public_expedition(state: dict[str, Any]) -> dict:
    quest = state.get("expedition")
    if not quest:
        return {}
    result = {
        key: quest[key]
        for key in FIELDS
        if key in quest and (quest[key] is None or type(quest[key]) in {str, int, bool})
    }
    result["clues"] = [
        clue
        for clue in quest.get("clues", [])
        if isinstance(clue, str) and clue in CLUES | {"ready_rope"}
    ]
    result["attempts"] = {
        key: {
            field: value
            for field, value in attempt.items()
            if field in {"skill", "roll", "bonus", "dc", "success", "total", "outcome"}
            and type(value) in {str, int, bool}
        }
        for key, attempt in quest.get("attempts", {}).items()
        if key in {"passage_persuasion", "passage_stealth", "approach_stealth"}
        and isinstance(attempt, dict)
    }
    return result


def travel_allowed(state: dict[str, Any], destination: str) -> bool:
    quest = state.get("expedition") or {}
    if destination == "eastern_gate":
        return bool(quest)
    if destination == "watchtower":
        return quest.get("passage") is not None
    return True


def available_actions(state: dict[str, Any]) -> list[str]:
    if state.get("player", {}).get("hp", 1) <= 0 or state.get("combat", {}).get("active"):
        return []
    if state.get("followup", {}).get("status") != "completed":
        return []
    branch = state.get("quest", {}).get("ending")
    if branch not in AIDS:
        return []
    location = state.get("location_id")
    quest = state.get("expedition")
    if quest is None:
        return [next(iter(COMMANDS))] if location == "market" else []
    if quest.get("branch") != branch or quest.get("status") == "completed":
        return []
    allowed = set()
    if quest.get("status") == "resolved":
        if location == "market":
            allowed.add(("report_expedition", "oren"))
    elif quest.get("status") == "active":
        if location == "market":
            if quest.get("aid") is None:
                allowed.add(("expedition_aid", branch))
            if (
                "ready_rope" not in quest["clues"]
                and state.get("resources", {}).get("camp_supplies", 0) > 0
            ):
                allowed.add(("expedition_prepare", "rope"))
        if location == "eastern_gate" and quest.get("passage") is None:
            allowed.add(("expedition_passage", "repair"))
            if quest.get("aid") == "guard_permit":
                allowed.add(("expedition_passage", "permit"))
            for skill in ("persuasion", "stealth"):
                if f"passage_{skill}" not in quest["attempts"]:
                    allowed.add(("expedition_passage", skill))
        if location == "watchtower" and quest.get("passage") is not None:
            for clue in CLUES - set(quest["clues"]):
                allowed.add(("expedition_clue", clue))
            if quest.get("approach") is None:
                allowed.add(("expedition_approach", "stairs"))
                if "approach_stealth" not in quest["attempts"]:
                    allowed.add(("expedition_approach", "stealth"))
            else:
                if "messenger_location" in quest["clues"]:
                    allowed.add(("resolve_expedition", "rescue"))
                if "document_location" in quest["clues"]:
                    allowed.add(("resolve_expedition", "documents"))
                if (
                    CLUES | {"ready_rope"} <= set(quest["clues"])
                    and state.get("elapsed_minutes", 0) + 5 <= quest["deadline_at"]
                ):
                    allowed.add(("resolve_expedition", "both"))
    return [label for label, command in COMMANDS.items() if command in allowed]


def apply(state: dict[str, Any], intent: str, targets: tuple[str, ...], roller: Roller) -> dict:
    allowed = {COMMANDS[label] for label in available_actions(state)}
    if len(targets) != 1 or (intent, targets[0]) not in allowed:
        raise ValueError("현재 망루 사건에서 실행할 수 없는 행동입니다.")
    target = targets[0]
    minutes, dice = 5, {"outcome": "no_check_required"}
    payload = {"rule_id": "watchtower-expedition-v1", "target": target}
    if intent == "start_expedition":
        now = state.get("elapsed_minutes", 0)
        state["expedition"] = {
            "id": "watchtower_messenger",
            "title": "꺼진 망루의 전령",
            "branch": state["quest"]["ending"],
            "status": "active",
            "stage": "preparation",
            "objective": (
                "동쪽 성문을 넘어 망루로 가세요. 의뢰 수락 후 90분 이내 행동을 끝내면 "
                "전령과 문서를 모두 구할 수 있습니다. 두 위치 단서와 로프가 필요합니다."
            ),
            "started_at": now,
            "deadline_at": now + 90,
            "aid": None,
            "clues": [],
            "attempts": {},
            "passage": None,
            "approach": None,
            "choice": None,
            "resolution": None,
        }
        minutes = 0
        lead = {
            "law": "감사에 필요한 봉인 운송 기록을 가져오던 전령이 돌아오지 않았어요.",
            "mercy": "상인들의 공개 증언을 뒷받침할 봉인 운송 기록이 망루에 있어요.",
            "exile": "피난 행렬 뒤에 남은 전령이 봉인 운송 기록을 지키고 있어요.",
        }[state["quest"]["ending"]]
        narrative = (
            f"Oren: {lead} 동쪽 망루의 불이 꺼졌고 강물이 차오르고 있어요. "
            "이 장에서는 90분 안에 구조를 끝내야 전령과 문서를 모두 구할 수 있어요. "
            "두 위치를 조사하고 로프를 준비해 주세요. 늦으면 하나만 구할 수 있어요."
        )
    else:
        quest = state["expedition"]
        if intent == "expedition_aid":
            quest["aid"] = AIDS[target]
            narrative = {
                "law": "경비대가 지난 감사 협력을 인정해 통행증을 발급했다.",
                "mercy": (
                    "시장의 상인들이 지난 공개 증언을 기억하고 소개장을 써 주었다. 성문 설득에 +2."
                ),
                "exile": "피난민을 이끌었던 경험으로 성문의 사각을 떠올렸다. 성문 잠입에 +2.",
            }[target]
        elif intent == "expedition_prepare":
            state["resources"]["camp_supplies"] -= 1
            quest["clues"].append("ready_rope")
            narrative = "야영 보급품 1개로 구조용 로프를 준비했다."
        elif intent in {"expedition_passage", "expedition_approach"}:
            passage = intent == "expedition_passage"
            field = "passage" if passage else "approach"
            success = True
            if target in {"persuasion", "stealth"}:
                bonus = int(
                    state.get("player", {}).get(
                        f"{target}_bonus", 3 if target == "persuasion" else 5
                    )
                )
                if passage and (target, quest["aid"]) in {
                    ("persuasion", "merchant_introduction"),
                    ("stealth", "refugee_route"),
                }:
                    bonus += 2
                roll = roller.roll(20)
                success = roll + bonus >= 14
                dice = {
                    "skill": target,
                    "roll": roll,
                    "bonus": bonus,
                    "dc": 14,
                    "success": success,
                    "total": roll + bonus,
                    "outcome": "success" if success else "failure",
                }
                quest["attempts"][f"{field}_{target}"] = dict(dice)
                minutes = 3 if success else 10
                if passage:
                    narrative = (
                        "경비가 구조의 필요성을 받아들이고 길을 열었다."
                        if target == "persuasion" and success
                        else "교대 경비의 시선을 피해 성문의 통제선을 넘었다."
                        if success
                        else "경비에게 막혀 10분을 잃었다. 같은 시도는 반복할 수 없지만 "
                        "보수 작업을 도우면 정식으로 통과할 수 있다."
                    )
                else:
                    narrative = (
                        "흔들리는 발판을 피해 조용히 상층에 올랐다."
                        if success
                        else "발판이 무너져 접근을 중단하고 10분을 잃었다. "
                        "같은 잠입은 반복할 수 없지만 계단을 보강하면 안전하게 오를 수 있다."
                    )
            else:
                minutes = {"permit": 5, "repair": 20, "stairs": 10}[target]
                narrative = {
                    "permit": "통행증을 확인한 경비가 성문을 열었다.",
                    "repair": "보수 작업을 도운 뒤 경비의 허락으로 성문을 통과했다.",
                    "stairs": "무너진 계단을 보강해 상층으로 향할 안전한 길을 만들었다.",
                }[target]
            if success:
                quest[field] = target
                quest["stage"] = "investigation" if passage else "decision"
                quest["objective"] = (
                    "망루에서 두 위치를 조사하고 상층 접근로를 확보하세요."
                    if passage
                    else (
                        "구조 또는 문서 확보를 확정하세요. "
                        "모두 확보하려면 두 위치 단서·로프·기한 충족이 필요합니다."
                    )
                )
        elif intent == "expedition_clue":
            quest["clues"].append(target)
            narrative = (
                "부러진 들보 아래 전령의 위치를 확인했다."
                if target == "messenger_location"
                else "상층 기록함에서 봉인 문서의 위치를 확인했다."
            )
        elif intent == "resolve_expedition":
            narrative = RESOLUTIONS[target]
            quest.update(
                status="resolved",
                stage="return",
                choice=target,
                resolution=narrative,
                objective="시장으로 돌아가 오렌에게 결과를 보고하세요.",
            )
            payload["choice"] = target
        else:
            narrative = (
                f"Oren에게 보고했다. {quest['resolution']} 오렌이 약속한 보상 25골드를 건넸다."
            )
            state.setdefault("resources", {}).setdefault("gold", 0)
            state["resources"]["gold"] += 25
            state.setdefault("npc_knowledge", {}).setdefault("npc_oren", {}).setdefault(
                "facts", {}
            )["expedition_report"] = {
                "text": (
                    f"플레이어가 '{quest['resolution']}'라고 보고했다. 현장을 직접 보지는 않았다."
                ),
                "source": "player_report",
                "certainty": "reported",
                "shareable": True,
            }
            quest.update(
                status="completed",
                stage="completed",
                objective="망루 사건을 해결하고 오렌에게 보고했습니다.",
            )
            payload["reward_gold"] = 25
    return {"narrative": narrative, "minutes": minutes, "dice": dice, "payload": payload}
