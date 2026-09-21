"""NPC별 사실·주장 장부. 주장에 대한 믿음은 세계의 진실과 별개다."""

from copy import deepcopy
from typing import Any

SEED_KNOWLEDGE = {
    "npc_harlan": {"seal_stolen": "왕실 봉인이 도난당했다. 봉인을 회수해야 한다."},
    "npc_mira": {"tax_abuse": "미라는 봉인이 부당한 통행세에 쓰인다고 주장한다."},
    "npc_oren": {"crate_seen": "Oren은 붉은 천으로 싼 상자가 강변 창고로 옮겨지는 것을 보았다."},
}
CLAIM_TEXT = {"mayor_sent_player": "플레이어가 시장의 지시를 받아 왔다고 주장했다."}


def initialize_knowledge(state: dict[str, Any]) -> None:
    ledgers = state.setdefault("npc_knowledge", {})
    for npc_id, facts in SEED_KNOWLEDGE.items():
        ledger = ledgers.setdefault(npc_id, {"facts": {}, "claims": {}, "episodes": []})
        for fact_id, text in facts.items():
            ledger["facts"].setdefault(
                fact_id,
                {
                    "text": text,
                    "source": "scenario",
                    "certainty": "known",
                    "shareable": True,
                },
            )


def record_episode(state: dict[str, Any], npc_id: str, kind: str) -> None:
    initialize_knowledge(state)
    episodes = state["npc_knowledge"][npc_id]["episodes"]
    episodes.append({"kind": kind, "day": state.get("day", 1), "time": state.get("time", "21:36")})
    # 중요 사실과 주장은 별도 장부에 남는다. 최근 접촉 기록만 제한한다.
    del episodes[:-20]


def actor_context(state: dict[str, Any], npc_id: str) -> dict[str, Any]:
    if npc_id not in SEED_KNOWLEDGE:
        raise ValueError("알 수 없는 NPC입니다.")
    snapshot = deepcopy(state)
    initialize_knowledge(snapshot)
    ledger = snapshot["npc_knowledge"][npc_id]
    facts = [
        {"id": fact_id, "text": item["text"], "source": item["source"], "certainty": "known"}
        for fact_id, item in ledger["facts"].items()
        if item.get("shareable") is True
    ][:12]
    claims = [
        {
            "id": claim_id,
            "text": CLAIM_TEXT[claim_id],
            "source": "player_assertion",
            "certainty": "unverified",
            "reaction": item["reaction"],
        }
        for claim_id, item in ledger["claims"].items()
        if claim_id in CLAIM_TEXT
    ][:12]
    return {
        "speaker_id": npc_id,
        "known_facts": facts,
        "remembered_claims": claims,
        "recent_contacts": [
            {"kind": entry["kind"], "day": entry["day"], "time": entry["time"]}
            for entry in ledger["episodes"][-6:]
        ],
    }
