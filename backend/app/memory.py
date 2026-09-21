"""NPC별 사실·주장 장부. 주장에 대한 믿음은 세계의 진실과 별개다."""

import re
from datetime import UTC, datetime
from math import isfinite
from typing import Any

SEED_KNOWLEDGE = {
    "npc_harlan": {"seal_stolen": "왕실 봉인이 도난당했다. 봉인을 회수해야 한다."},
    "npc_mira": {"tax_abuse": "미라는 봉인이 부당한 통행세에 쓰인다고 주장한다."},
    "npc_oren": {"crate_seen": "Oren은 붉은 천으로 싼 상자가 강변 창고로 옮겨지는 것을 보았다."},
}
CLAIM_TEXT = {"mayor_sent_player": "플레이어가 시장의 지시를 받아 왔다고 주장했다."}


def _normalize_report(fact_id: str, item: dict[str, Any]) -> dict[str, Any]:
    if fact_id != "expedition_report" or item.get("source") != "witnessed_report":
        return item
    result = dict(item)
    result.update(source="player_report", certainty="reported")
    text = result.get("text")
    if isinstance(text, str) and not text.startswith("플레이어가 '"):
        result["text"] = f"플레이어가 '{text}'라고 보고했다. 현장을 직접 보지는 않았다."
    return result


def initialize_knowledge(state: dict[str, Any]) -> None:
    ledgers = state.setdefault("npc_knowledge", {})
    for npc_id, facts in SEED_KNOWLEDGE.items():
        ledger = ledgers.setdefault(npc_id, {"facts": {}, "claims": {}, "episodes": []})
        report = ledger["facts"].get("expedition_report")
        if isinstance(report, dict):
            ledger["facts"]["expedition_report"] = _normalize_report("expedition_report", report)
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


MAX_QUERY_CHARS = 4096
MAX_MEMORY_TEXT_CHARS = 1000
MAX_FACTS = 12


def _terms(text: str) -> set[str]:
    return set(re.findall(r"[^\W_]+", text.casefold()))


def _relevance(text: str, terms: set[str]) -> int:
    normalized = text.casefold()
    words = _terms(text)
    score = 0
    for term in terms:
        if term in words:
            score += 10
        elif len(term) >= 2 and term in normalized:
            score += 6
        elif len(term) >= 2 and any("가" <= char <= "힣" for char in term):
            # 한국어 조사/어미가 달라도 두 글자 이상 겹친 내용을 찾는다.
            score += min(3, sum(term[i : i + 2] in normalized for i in range(len(term) - 1)))
    return score


def _timestamp(item: dict[str, Any]) -> float:
    value = item.get("timestamp")
    if type(value) in (int, float):
        try:
            return float(value) if isfinite(value) else 0.0
        except OverflowError:
            return 0.0
    if isinstance(value, str) and len(value) <= 64:
        try:
            parsed = datetime.fromisoformat(value)
            return parsed.replace(tzinfo=parsed.tzinfo or UTC).timestamp()
        except (ValueError, OverflowError, OSError):
            pass
    return 0.0


def actor_context(state: dict[str, Any], npc_id: str, query: str = "") -> dict[str, Any]:
    """대상 NPC의 공유 가능한 장부만 검색한다. 원본 장부는 변경하지 않는다.

    검색 입력 4096자/앞 64어휘/어휘당 64자, 사실 본문 1000자/12개, 접촉 6개 제한.
    최신성은 timestamp(숫자/ISO 문자열), 삽입 순서로 판단하고 시나리오를 보존한다.
    """
    if npc_id not in SEED_KNOWLEDGE:
        raise ValueError("알 수 없는 NPC입니다.")
    ledgers = state.get("npc_knowledge", {})
    ledger = ledgers.get(npc_id, {}) if isinstance(ledgers, dict) else {}
    if not isinstance(ledger, dict):
        ledger = {}
    stored_facts = ledger.get("facts", {})
    local_facts = dict(stored_facts) if isinstance(stored_facts, dict) else {}
    for fact_id, text in SEED_KNOWLEDGE[npc_id].items():
        local_facts.setdefault(
            fact_id,
            {"text": text, "source": "scenario", "certainty": "known", "shareable": True},
        )
    query_words = re.findall(r"[^\W_]+", query[:MAX_QUERY_CHARS]) if isinstance(query, str) else []
    terms = {word[:64].casefold() for word in query_words[:64]}
    candidates = []
    for order, (fact_id, item) in enumerate(local_facts.items()):
        if not isinstance(fact_id, str) or not isinstance(item, dict):
            continue
        if item.get("shareable") is not True:
            continue
        item = _normalize_report(fact_id, item)
        text, source = item.get("text"), item.get("source", "unknown")
        if not isinstance(text, str) or not isinstance(source, str):
            continue
        certainty = item.get("certainty")
        if certainty not in ("known", "reported", "unverified"):
            certainty = "unverified"
        fact = {
            "id": fact_id[:200],
            "text": text[:MAX_MEMORY_TEXT_CHARS],
            "source": source[:200],
            "certainty": certainty,
        }
        candidates.append((_relevance(fact["text"], terms), (_timestamp(item), order), fact))
    ranked = sorted(candidates, key=lambda candidate: (candidate[0], candidate[1]), reverse=True)
    selected = [candidate for candidate in ranked if candidate[0] > 0][:MAX_FACTS]
    # 관련 사실이 슬롯을 모두 채워도 핵심 시나리오 하나는 남긴다.
    anchors = [candidate for candidate in ranked if candidate[2]["source"] == "scenario"]
    if anchors and anchors[0] not in selected:
        if len(selected) == MAX_FACTS:
            selected[-1] = anchors[0]
        else:
            selected.append(anchors[0])
    for candidate in ranked:
        if len(selected) >= MAX_FACTS:
            break
        if candidate not in selected:
            selected.append(candidate)
    facts = [candidate[2] for candidate in selected]
    stored_claims = ledger.get("claims", {})
    if not isinstance(stored_claims, dict):
        stored_claims = {}
    claims = [
        {
            "id": claim_id,
            "text": CLAIM_TEXT[claim_id],
            "source": "player_assertion",
            "certainty": "unverified",
            "reaction": item["reaction"],
        }
        for claim_id, item in stored_claims.items()
        if claim_id in CLAIM_TEXT
        and isinstance(item, dict)
        and item.get("reaction") in ("believed", "doubted")
    ][:12]
    episodes = ledger.get("episodes", [])
    if not isinstance(episodes, list):
        episodes = []
    return {
        "speaker_id": npc_id,
        "known_facts": facts,
        "remembered_claims": claims,
        "recent_contacts": [
            {"kind": entry["kind"][:200], "day": entry["day"], "time": entry["time"][:200]}
            for entry in episodes[-6:]
            if isinstance(entry, dict)
            and isinstance(entry.get("kind"), str)
            and type(entry.get("day")) is int
            and isinstance(entry.get("time"), str)
        ],
        "memory_selection": {
            "method": "lexical-v1",
            "eligible_facts": len(candidates),
            "selected_facts": len(facts),
        },
    }
