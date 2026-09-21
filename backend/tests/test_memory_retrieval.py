import json
from copy import deepcopy

import pytest

from app.memory import actor_context, initialize_knowledge


def fact(text, **fields):
    return {"text": text, "source": "observation", "shareable": True, **fields}


def populated_state():
    state = {}
    initialize_knowledge(state)
    facts = state["npc_knowledge"]["npc_harlan"]["facts"]
    for index in range(30):
        facts[f"visit_{index}"] = fact(f"방문 기록 {index}")
    return state, facts


@pytest.mark.parametrize("query", ["황금열쇠", "황금열쇠는 어디 있지?", "GOLDENKEY"])
def test_late_relevant_fact_is_retrieved(query):
    state, facts = populated_state()
    facts["visit_25"] = fact("지하실에서 황금열쇠를 발견했다. goldenkey")
    context = actor_context(state, "npc_harlan", query)
    assert context["known_facts"][0]["id"] == "visit_25"
    assert len(context["known_facts"]) == 12


def test_empty_query_balances_seed_and_recent_facts_deterministically():
    state, _ = populated_state()
    before = deepcopy(state)
    context = actor_context(state, "npc_harlan")
    assert [fact["id"] for fact in context["known_facts"]] == [
        "seal_stolen",
        *[f"visit_{i}" for i in range(29, 18, -1)],
    ]
    assert context == actor_context(state, "npc_harlan")
    assert state == before
    assert context["memory_selection"] == {
        "method": "lexical-v1",
        "eligible_facts": 31,
        "selected_facts": 12,
    }


def test_saturated_query_keeps_one_scenario_anchor_and_eleven_relevant_facts():
    state, facts = populated_state()
    for index in range(15):
        facts[f"key_{index}"] = fact(f"황금열쇠 소식 {index}")
    before = deepcopy(state)
    selected = actor_context(state, "npc_harlan", "황금열쇠")["known_facts"]
    assert len(selected) == 12
    assert sum(item["source"] == "scenario" for item in selected) == 1
    assert {item["id"] for item in selected if item["source"] != "scenario"} == {
        f"key_{index}" for index in range(4, 15)
    }
    assert state == before


def test_privacy_and_projection_reject_nested_fields_and_preserve_claim():
    state, facts = populated_state()
    facts["secret"] = fact("PRIVATE_SENTINEL", shareable=False)
    facts["bad_source"] = fact("bad", source={"secret": "NESTED_SENTINEL"})
    facts["bad_text"] = fact({"secret": "NESTED_SENTINEL"})
    state["npc_knowledge"]["npc_mira"]["facts"]["foreign"] = fact("FOREIGN_SENTINEL")
    state["world_truth"] = {"secret": "WORLD_SENTINEL"}
    state["journal"] = ["JOURNAL_SENTINEL"]
    ledger = state["npc_knowledge"]["npc_harlan"]
    ledger["claims"]["mayor_sent_player"] = {"reaction": "believed"}
    ledger["episodes"] = [{"kind": "visit", "day": 1, "time": "21:00"}] * 20
    before = deepcopy(state)
    context = actor_context(state, "npc_harlan", "SENTINEL")
    assert "SENTINEL" not in json.dumps(context)
    assert len(context["recent_contacts"]) == 6
    assert context["remembered_claims"][0]["certainty"] == "unverified"
    assert context["remembered_claims"][0]["reaction"] == "believed"
    assert context["memory_selection"]["eligible_facts"] == 31
    assert state == before


@pytest.mark.parametrize("certainty", [None, "mystery", "reported", "unverified", {"x": 1}])
def test_certainty_never_promoted(certainty):
    state, facts = populated_state()
    facts["report"] = fact("표적 증언", certainty=certainty)
    result = actor_context(state, "npc_harlan", "표적")["known_facts"][0]
    assert result["certainty"] == (certainty if certainty == "reported" else "unverified")


def test_timestamp_and_bounded_text_query():
    state, facts = populated_state()
    facts["dated"] = fact("dated", timestamp="2026-09-21T12:00:00Z")
    facts["long"] = fact("앞" * 2000)
    context = actor_context(state, "npc_harlan", "앞앞")
    assert len(context["known_facts"][0]["text"]) == 1000
    assert actor_context(state, "npc_harlan", " " * 4096 + "앞" * 100_000) == actor_context(
        state, "npc_harlan", ""
    )
    assert actor_context(state, "npc_harlan")["known_facts"][1]["id"] == "dated"


def test_legacy_report_is_normalized_without_mutation_or_duplicate_prefix():
    state, facts = populated_state()
    facts["expedition_report"] = fact(
        "창고 조사 완료", source="witnessed_report", certainty="known"
    )
    facts["other"] = fact("직접 목격", source="witnessed_report", certainty="known")
    before = deepcopy(state)
    report = actor_context(state, "npc_harlan", "창고")["known_facts"][0]
    assert report["source"] == "player_report"
    assert report["certainty"] == "reported"
    assert report["text"] == "플레이어가 '창고 조사 완료'라고 보고했다. 현장을 직접 보지는 않았다."
    assert state == before
    initialize_knowledge(state)
    normalized = deepcopy(state)
    initialize_knowledge(state)
    assert state == normalized
    assert facts["other"]["certainty"] == "known"


def test_actor_context_does_not_read_other_state_branches():
    class Unreadable(dict):
        def __deepcopy__(self, memo):
            raise AssertionError("unrelated state read")

    state = {"world_truth": Unreadable(), "journal": Unreadable()}
    context = actor_context(state, "npc_harlan")
    assert context["known_facts"][0]["id"] == "seal_stolen"
    assert "npc_knowledge" not in state


def test_malformed_claim_episode_fields_do_not_escape_projection():
    state = {}
    initialize_knowledge(state)
    ledger = state["npc_knowledge"]["npc_harlan"]
    ledger["claims"] = {"mayor_sent_player": {"reaction": {"secret": "SENTINEL"}}}
    ledger["episodes"] = [{"kind": "visit", "day": 1, "time": {"secret": "SENTINEL"}}]
    context = actor_context(state, "npc_harlan")
    assert context["remembered_claims"] == []
    assert context["recent_contacts"] == []
