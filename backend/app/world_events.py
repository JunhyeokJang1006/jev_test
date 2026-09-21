"""망루 이후 두 단계 공개 사건. 고정 템플릿만 실행하는 결정론적 상태 규칙."""

from math import isfinite
from typing import Any

COMMANDS = {
    "보급 수송 호위 요청 (10분)": ("support_convoy", "guards"),
    "보급 수송 자금 지원 (8골드, 10분)": ("support_convoy", "merchants"),
    "보급 수송 자원봉사 (30분)": ("support_convoy", "volunteers"),
    "세계 사건 기다리기 (10분)": ("wait_world_event", "clock"),
}
CHOICES = ("rescue", "documents", "both")
SUPPORTS = (None, "guards", "merchants", "volunteers")
TITLES = {"supply_convoy": "도시 보급 수송", "market_settlement": "시장 보급 정산"}
FACTIONS = {
    "guards": ("도시 경비대", "보급로 안전 확보"),
    "merchants": ("시장 상인회", "도시 물자 공급 회복"),
    "refugees": ("피난민 공동체", "피난민 식량 확보"),
}
PLANS = (
    "보급 수송 준비",
    "보급 수송 지원",
    "보급로 정체",
    "보급 도착 대기",
    "보급 정산 대기",
    "보급 정산 완료",
)
LOCATIONS = ("greyhaven_inn", "market", "warehouse", "eastern_gate", "watchtower")


def _integer(value: Any) -> bool:
    return type(value) is int and value >= 0


def _event_valid(event: Any) -> bool:
    if not isinstance(event, dict):
        return False
    if (
        type(event.get("id")) is not str
        or event["id"] not in TITLES
        or event.get("choice") not in CHOICES
    ):
        return False
    if not _integer(event.get("created_at")) or not _integer(event.get("due_at")):
        return False
    if event["due_at"] != event["created_at"] + 60 or event.get("support") not in SUPPORTS:
        return False
    status, outcome = event.get("status"), event.get("outcome")
    if status == "pending":
        return outcome is None
    if status != "resolved":
        return False
    outcomes = (
        ("arrived", "delayed")
        if event["id"] == "supply_convoy"
        else ("recovered", "stable", "delayed")
    )
    return outcome in outcomes


def _factions_valid(factions: Any) -> bool:
    if not isinstance(factions, dict):
        return False
    for key in FACTIONS:
        item = factions.get(key)
        if not isinstance(item, dict) or not _integer(item.get("stock")):
            return False
        trust = item.get("trust")
        if type(trust) not in (int, float) or not 0 <= trust <= 1 or not isfinite(trust):
            return False
        if item.get("plan") not in PLANS:
            return False
    return True


def _valid(state: dict) -> bool:
    if not isinstance(state, dict):
        return False
    events = state.get("world_events")
    if not isinstance(events, list) or not 1 <= len(events) <= 2:
        return False
    if not all(_event_valid(item) for item in events) or not _factions_valid(state.get("factions")):
        return False
    first = events[0]
    if first["id"] != "supply_convoy":
        return False
    if first["choice"] == "rescue" and first["support"] == "guards":
        return False
    if first["status"] == "resolved":
        expected = "arrived" if first["support"] or first["choice"] == "both" else "delayed"
        if first["outcome"] != expected:
            return False
    if len(events) == 2:
        second = events[1]
        if not (
            first["status"] == "resolved"
            and second["id"] == "market_settlement"
            and second["created_at"] == first["due_at"]
            and second["choice"] == first["choice"]
            and second["support"] == first["support"]
            and second.get("predecessor_outcome", first["outcome"]) == first["outcome"]
        ):
            return False
        if second["status"] == "resolved" and (
            (first["outcome"] == "arrived" and second["outcome"] != "stable")
            or (first["outcome"] == "delayed" and second["outcome"] not in ("delayed", "recovered"))
        ):
            return False
    return True


def _text(event: dict) -> str:
    if event["status"] == "pending":
        if event["id"] == "market_settlement":
            return "보급 수송 결과를 반영한 시장 정산이 한 시간 뒤 예정되어 있다."
        return (
            "망루 보고를 바탕으로 도시 보급 수송이 한 시간 뒤 예정되어 있다. "
            "시장에서 수송을 지원할 수 있다."
        )
    if event["id"] == "market_settlement":
        return {
            "stable": "수송 물자 정산이 끝났다. 시장의 구호 가격이 유지된다.",
            "recovered": (
                "경비대가 비축 자원 1개로 지연된 수송을 복구했다. "
                "시장은 행렬 공급 가격으로 회복된다."
            ),
            "delayed": (
                "경비대 비축 자원이 없어 수송 복구가 지연되었다. 시장의 물자 부족 가격이 유지된다."
            ),
        }[event["outcome"]]
    if event["outcome"] == "delayed":
        return (
            "수송 지원과 공동 협력에 필요한 전령·문서가 함께 확보되지 않아 수송이 지연되었다. "
            "시장은 물자 부족 가격을 적용한다."
        )
    cause = {
        "guards": "회수한 문서의 경로와 경비대 호위",
        "merchants": "플레이어의 8골드와 상인회 비축 물자",
        "volunteers": "플레이어의 자원봉사",
        None: "함께 구한 전령과 문서를 통한 파벌 공동 협력",
    }[event["support"]]
    return f"{cause} 덕분에 보급 수송이 도착했다. 시장은 구호 가격을 적용한다."


def _new(event_id: str, now: int, choice: str, support=None, predecessor=None) -> dict:
    event = dict(
        id=event_id,
        title=TITLES[event_id],
        status="pending",
        created_at=now,
        due_at=now + 60,
        choice=choice,
        support=support,
        outcome=None,
        resolution=None,
    )
    if predecessor is not None:
        event["predecessor_outcome"] = predecessor
    return event


def advance(state: dict[str, Any]) -> list[dict]:
    """호출자가 소유한 복사본에 예약/만기 사건을 시간순으로 한 번씩 적용한다."""
    if not isinstance(state, dict):
        return []
    now = state.get("elapsed_minutes", 0)
    if not _integer(now):
        return []
    summaries = []
    if "world_events" not in state:
        expedition = state.get("expedition")
        if (
            not isinstance(expedition, dict)
            or expedition.get("status") != "completed"
            or expedition.get("choice") not in CHOICES
        ):
            return []
        if "factions" in state:
            return []
        quest = state.get("quest")
        ending = quest.get("ending") if isinstance(quest, dict) else None
        favored = (
            {"law": "guards", "mercy": "merchants", "exile": "refugees"}.get(ending)
            if type(ending) is str
            else None
        )
        state["factions"] = {
            key: dict(
                name=name,
                goal=goal,
                stock=2 + (key == favored),
                trust=0.7 if key == favored else 0.5,
                plan=PLANS[0],
            )
            for key, (name, goal) in FACTIONS.items()
        }
        event = _new("supply_convoy", now, expedition["choice"])
        state["world_events"] = [event]
        summaries.append(dict(id=event["id"], phase="scheduled", text=_text(event)))
    if not _valid(state):
        return []
    events, factions = state["world_events"], state["factions"]
    first = events[0]
    if first["status"] == "pending" and now >= first["due_at"]:
        success = bool(first["support"]) or first["choice"] == "both"
        first.update(status="resolved", outcome="arrived" if success else "delayed")
        state["market_policy"] = "relief" if success else "shortage"
        factions["merchants"]["stock"] = max(
            0, factions["merchants"]["stock"] + (1 if success else -1)
        )
        if success:
            factions["refugees"]["stock"] += 1
            supporter = {"volunteers": "refugees"}.get(first["support"], first["support"])
            if supporter:
                factions[supporter]["trust"] = min(
                    1.0, round(factions[supporter]["trust"] + 0.1, 10)
                )
        for key in factions:
            if key in FACTIONS:
                factions[key]["plan"] = "보급 정산 대기"
        if not success:
            factions["guards"]["plan"] = "보급로 정체"
            factions["refugees"]["plan"] = "보급 도착 대기"
        first["resolution"] = _text(first)
        summaries.append(dict(id=first["id"], phase="resolved", text=_text(first)))
    if first["status"] == "resolved" and len(events) == 1:
        second = _new(
            "market_settlement",
            first["due_at"],
            first["choice"],
            first["support"],
            first["outcome"],
        )
        events.append(second)
        summaries.append(dict(id=second["id"], phase="scheduled", text=_text(second)))
    if len(events) == 2:
        second = events[1]
        if second["status"] == "pending" and now >= second["due_at"]:
            outcome = "stable"
            if first["outcome"] == "delayed":
                outcome = "delayed"
                if factions["guards"]["stock"] >= 1:
                    factions["guards"]["stock"] -= 1
                    outcome = "recovered"
            state["market_policy"] = {
                "stable": "relief",
                "recovered": "caravan",
                "delayed": "shortage",
            }[outcome]
            second.update(status="resolved", outcome=outcome)
            second["resolution"] = _text(second)
            for key in FACTIONS:
                factions[key]["plan"] = "보급 정산 완료"
            summaries.append(dict(id=second["id"], phase="resolved", text=_text(second)))
    return summaries


def available_actions(state: dict[str, Any]) -> list[str]:
    if not _valid(state) or not _integer(state.get("elapsed_minutes", 0)):
        return []
    player = state.get("player", {})
    combat = state.get("combat", {})
    resources = state.get("resources", {})
    if not all(isinstance(item, dict) for item in (player, combat, resources)):
        return []
    hp = player.get("hp", 0)
    if (
        not _integer(hp)
        or hp <= 0
        or type(combat.get("active", False)) is not bool
        or combat.get("active", False)
        or state.get("location_id") not in LOCATIONS
    ):
        return []
    now, first = state.get("elapsed_minutes", 0), state["world_events"][0]
    allowed = set()
    if any(event["status"] == "pending" for event in state["world_events"]):
        allowed.add(("wait_world_event", "clock"))
    if (
        state["location_id"] == "market"
        and first["status"] == "pending"
        and first["support"] is None
        and now < first["due_at"]
    ):
        for support, minutes in (("guards", 10), ("merchants", 10), ("volunteers", 30)):
            if now + minutes > first["due_at"]:
                continue
            if support == "guards" and (
                first["choice"] == "rescue" or state["factions"]["guards"]["stock"] < 1
            ):
                continue
            if support == "merchants":
                gold = resources.get("gold", 0)
                if not _integer(gold) or gold < 8 or state["factions"]["merchants"]["stock"] < 1:
                    continue
            allowed.add(("support_convoy", support))
    return [label for label, command in COMMANDS.items() if command in allowed]


def apply(state: dict[str, Any], intent: str, targets: tuple[str, ...]) -> dict:
    if (
        type(intent) is not str
        or not isinstance(targets, (tuple, list))
        or len(targets) != 1
        or type(targets[0]) is not str
        or (intent, targets[0]) not in {COMMANDS[label] for label in available_actions(state)}
    ):
        raise ValueError("현재 세계 사건에서 실행할 수 없는 행동입니다.")
    target = targets[0]
    minutes, narrative = 10, "공개 세계 사건의 진행을 기다린다."
    payload = {"rule_id": "public-world-events-v1", "target": target}
    if intent == "support_convoy":
        state["world_events"][0]["support"] = target
        if target in ("guards", "merchants"):
            state["factions"][target]["stock"] -= 1
            state["factions"][target]["plan"] = "보급 수송 지원"
        if target == "merchants":
            state["resources"]["gold"] -= 8
            payload["gold_spent"] = 8
        if target == "volunteers":
            minutes = 30
            state["factions"]["refugees"]["plan"] = "보급 수송 지원"
        narrative = "보급 수송 지원을 마쳤다. 예정 시각에 수송 결과가 공개된다."
    return dict(
        narrative=narrative, minutes=minutes, payload=payload, dice={"outcome": "no_check_required"}
    )


def public_world(state: dict[str, Any]) -> dict:
    """자유 문자열을 복사하지 않고 검증된 규칙 값으로 공개 자료를 재구성한다."""
    if not _valid(state):
        return {"world_events": [], "factions": {}}
    events = []
    for event in state["world_events"]:
        item = {
            key: event[key]
            for key in ("id", "status", "created_at", "due_at", "choice", "support", "outcome")
        }
        item.update(
            title=TITLES[event["id"]],
            resolution=_text(event) if event["status"] == "resolved" else None,
        )
        events.append(item)
    factions = {
        key: dict(
            name=name,
            goal=goal,
            stock=state["factions"][key]["stock"],
            trust=state["factions"][key]["trust"],
            plan=state["factions"][key]["plan"],
        )
        for key, (name, goal) in FACTIONS.items()
    }
    return {"world_events": events, "factions": factions}


def notice_for_npc(state: dict[str, Any], npc_id: str) -> str | None:
    if not _valid(state) or type(npc_id) is not str:
        return None
    npcs = state.get("npcs", [])
    if not isinstance(npcs, list):
        return None
    present = {
        item["id"] for item in npcs if isinstance(item, dict) and type(item.get("id")) is str
    }
    if npc_id not in present or npc_id not in ("npc_harlan", "npc_mira", "npc_oren"):
        return None
    knowledge = state.get("npc_knowledge", {})
    if not isinstance(knowledge, dict):
        return None
    existing = knowledge.get(npc_id, {})
    if not isinstance(existing, dict) or not isinstance(existing.get("facts", {}), dict):
        return None
    event = state["world_events"][-1]
    if event["status"] == "pending" and len(state["world_events"]) == 2:
        event = state["world_events"][0]
    notice = _text(event)
    ledger = state.setdefault("npc_knowledge", {}).setdefault(
        npc_id, {"facts": {}, "claims": {}, "episodes": []}
    )
    ledger.setdefault("facts", {})["public_world_event"] = dict(
        text=notice, source="public_notice", certainty="known", shareable=True
    )
    return notice
