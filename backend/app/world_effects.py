"""후속 사건 종결 뒤 지연되는 공개 공고와 시장 정책."""

from typing import Any

WAIT_LABEL = "공고 기다리기 (10분)"
COMMANDS = {WAIT_LABEL: ("wait_notice", "notice")}
POLICIES = {"law": "relief", "mercy": "shortage", "exile": "caravan"}
NOTICES = {
    "law": "감사 공고: 시장 지원으로 치유 물약은 6골드, 야영 보급은 2골드에 판매합니다.",
    "mercy": "분쟁 공고: 물자 부족으로 치유 물약은 10골드, 야영 보급은 4골드에 판매합니다.",
    "exile": "피난 행렬 감사 공고: 치유 물약은 8골드, 야영 보급은 2골드에 판매합니다.",
}
PRICE_TABLE = {"relief": (6, 2), "shortage": (10, 4), "caravan": (8, 2)}


def advance(state: dict[str, Any]) -> str | None:
    """호출자가 복사한 상태에 공고를 예약하거나 기한 도달 시 한 번 적용한다."""
    ending = state.get("quest", {}).get("ending")
    if state.get("followup", {}).get("status") != "completed" or ending not in POLICIES:
        return None
    now = state.get("elapsed_minutes", 0)
    effects = state.setdefault(
        "world_effects", {"effective_at": now + 60, "applied": False, "notice": None}
    )
    if effects["applied"] or now < effects["effective_at"]:
        return None
    notice = NOTICES[ending]
    effects.update(applied=True, notice=notice)
    state["market_policy"] = POLICIES[ending]
    return notice


def available_actions(state: dict[str, Any]) -> list[str]:
    if (
        state.get("player", {}).get("hp", 0) <= 0
        or state.get("combat", {}).get("active")
        or state.get("followup", {}).get("status") != "completed"
        or state.get("world_effects", {}).get("applied")
    ):
        return []
    return [WAIT_LABEL]


def prices(state: dict[str, Any]) -> dict[str, int]:
    potion, supply = PRICE_TABLE.get(state.get("market_policy"), (8, 3))
    return {"healing_potions": potion, "camp_supplies": supply}


def notice_for_npc(state: dict[str, Any], npc_id: str) -> str | None:
    """현재 장면에서 접촉한 NPC 한 명에게만 이미 공개된 공고를 기록한다."""
    effects = state.get("world_effects", {})
    if not effects.get("applied") or not effects.get("notice"):
        return None
    if npc_id not in {npc["id"] for npc in state.get("npcs", [])}:
        return None
    notice = effects["notice"]
    state["npc_knowledge"][npc_id]["facts"]["public_market_notice"] = {
        "text": notice,
        "source": "public_notice",
        "certainty": "known",
        "shareable": True,
    }
    return notice
