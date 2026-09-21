import json
from copy import deepcopy

import pytest

from app import world_events as engine


def state(choice="rescue", branch="law"):
    return {
        "expedition": {"status": "completed", "choice": choice},
        "quest": {"ending": branch},
        "elapsed_minutes": 20,
        "location_id": "market",
        "player": {"hp": 10},
        "resources": {"gold": 8},
        "npcs": [{"id": "npc_oren"}],
        "npc_knowledge": {"npc_mira": {"facts": {"private": "CANARY"}}},
    }


def started(choice="rescue", branch="law"):
    s = state(choice, branch)
    assert engine.advance(s)[0]["phase"] == "scheduled"
    return s


@pytest.mark.parametrize("choice", engine.CHOICES)
@pytest.mark.parametrize(
    "branch,favored", [("law", "guards"), ("mercy", "merchants"), ("exile", "refugees")]
)
def test_initial_factions_and_only_completed_reports(choice, branch, favored):
    s = state(choice, branch)
    s["expedition"]["status"] = "resolved"
    before = deepcopy(s)
    assert engine.advance(s) == [] and s == before
    s["expedition"]["status"] = "completed"
    engine.advance(s)
    assert s["factions"][favored]["stock"] == 3
    assert s["factions"][favored]["trust"] == 0.7
    assert s["world_events"][0]["due_at"] == 80
    assert s["world_events"][0]["choice"] == choice


@pytest.mark.parametrize("choice", engine.CHOICES)
def test_unsponsored_large_jump_snapshots_and_idempotence(choice):
    s = started(choice)
    prior = deepcopy({key: s[key] for key in ("quest", "resources", "npc_knowledge")})
    s["expedition"]["choice"] = "documents" if choice == "both" else "both"
    s["elapsed_minutes"] = 200
    summaries = engine.advance(s)
    assert [(event["id"], event["phase"]) for event in summaries] == [
        ("supply_convoy", "resolved"),
        ("market_settlement", "scheduled"),
        ("market_settlement", "resolved"),
    ]
    assert s["world_events"][1]["due_at"] == 140
    assert s["world_events"][1]["choice"] == choice
    assert s["market_policy"] == ("relief" if choice == "both" else "caravan")
    assert {key: s[key] for key in prior} == prior
    before = deepcopy(s)
    assert engine.advance(s) == [] and s == before


@pytest.mark.parametrize("choice", engine.CHOICES)
@pytest.mark.parametrize("support", ["guards", "merchants", "volunteers"])
def test_support_costs_resolution_and_real_choice_benefit(choice, support):
    s = started(choice)
    before = deepcopy(s)
    if choice == "rescue" and support == "guards":
        with pytest.raises(ValueError):
            engine.apply(s, "support_convoy", (support,))
        assert s == before
        return
    result = engine.apply(s, "support_convoy", (support,))
    assert result["minutes"] == (30 if support == "volunteers" else 10)
    assert s["resources"]["gold"] == (0 if support == "merchants" else 8)
    assert s["world_events"][0]["status"] == "pending"
    assert s["elapsed_minutes"] == 20
    with pytest.raises(ValueError):
        engine.apply(s, "support_convoy", (support,))
    s["elapsed_minutes"] = 80
    engine.advance(s)
    assert s["world_events"][0]["outcome"] == "arrived"
    assert s["market_policy"] == "relief"
    faction = "refugees" if support == "volunteers" else support
    assert s["factions"][faction]["trust"] == pytest.approx(
        before["factions"][faction]["trust"] + 0.1
    )


@pytest.mark.parametrize(
    "support,duration", [("guards", 10), ("merchants", 10), ("volunteers", 30)]
)
def test_deadline_inclusive_support_and_rejected_late_no_mutation(support, duration):
    s = started("documents")
    s["elapsed_minutes"] = 80 - duration
    assert ("support_convoy", support) in [
        engine.COMMANDS[label] for label in engine.available_actions(s)
    ]
    s["elapsed_minutes"] += 1
    before = deepcopy(s)
    with pytest.raises(ValueError):
        engine.apply(s, "support_convoy", (support,))
    assert s == before


@pytest.mark.parametrize("condition", ["hp", "combat", "location", "gold", "stock"])
def test_support_preconditions_and_no_mutation(condition):
    s = started("documents")
    if condition == "hp":
        s["player"]["hp"] = 0
    elif condition == "combat":
        s["combat"] = {"active": True}
    elif condition == "location":
        s["location_id"] = "watchtower"
    elif condition == "gold":
        s["resources"]["gold"] = 7
    else:
        s["factions"]["merchants"]["stock"] = 0
    before = deepcopy(s)
    with pytest.raises(ValueError):
        engine.apply(s, "support_convoy", ("merchants",))
    assert s == before


def test_volunteer_no_stocks_and_wait_known_location():
    s = started()
    for faction in s["factions"].values():
        faction["stock"] = 0
    s["resources"]["gold"] = 0
    assert engine.apply(s, "support_convoy", ("volunteers",))["minutes"] == 30
    for location in engine.LOCATIONS:
        s["location_id"] = location
        before = deepcopy(s)
        assert engine.apply(s, "wait_world_event", ("clock",))["minutes"] == 10
        assert s == before
    s["location_id"] = "unknown"
    assert engine.available_actions(s) == []


def test_recovery_without_stock_and_existing_notice_untouched():
    s = started()
    s["factions"]["guards"]["stock"] = 0
    s["world_effects"] = {"applied": True, "notice": "independent"}
    s["elapsed_minutes"] = 140
    engine.advance(s)
    assert s["world_events"][1]["outcome"] == "delayed"
    assert s["market_policy"] == "shortage"
    assert s["world_effects"] == {"applied": True, "notice": "independent"}


def test_public_projection_canaries_and_npc_local_knowledge():
    s = started("both")
    s["world_events"][0].update(title="CANARY", resolution="CANARY", secret="CANARY")
    s["factions"]["guards"].update(name="CANARY", goal="CANARY", secret="CANARY")
    s["factions"]["secret"] = {"goal": "CANARY"}
    assert "CANARY" not in json.dumps(engine.public_world(s))
    before = deepcopy(s)
    assert engine.notice_for_npc(s, "npc_mira") is None
    assert before == s
    s["elapsed_minutes"] = 80
    engine.advance(s)
    assert engine.notice_for_npc(s, "npc_oren")
    assert s["npc_knowledge"]["npc_mira"] == before["npc_knowledge"]["npc_mira"]
    fact = s["npc_knowledge"]["npc_oren"]["facts"]["public_world_event"]
    assert fact["source"] == "public_notice" and fact["certainty"] == "known"
    assert "CANARY" not in fact["text"]


def test_public_state_can_be_projected_again_and_retains_pending_wait():
    s = started("both")
    s["elapsed_minutes"] = 80
    engine.advance(s)
    public = engine.public_world(s)
    projected_state = {**s, **public}
    assert engine.public_world(projected_state) == public
    assert "세계 사건 기다리기 (10분)" in engine.available_actions(projected_state)


def test_support_trust_caps_and_no_policy_reapplication():
    s = started("documents")
    s["factions"]["guards"]["trust"] = 0.98
    engine.apply(s, "support_convoy", ("guards",))
    s["elapsed_minutes"] = 140
    engine.advance(s)
    assert s["factions"]["guards"]["trust"] == 1.0
    s["market_policy"] = "caravan"
    before = deepcopy(s)
    assert engine.advance(s) == []
    assert s == before


def test_impossible_guard_support_without_documents_fails_closed():
    s = started("rescue")
    s["world_events"][0]["support"] = "guards"
    s["elapsed_minutes"] = 140
    before = deepcopy(s)
    assert engine.advance(s) == [] and engine.available_actions(s) == []
    assert s == before


@pytest.mark.parametrize("field", ["player", "combat", "resources"])
@pytest.mark.parametrize("value", [None, [], "CANARY", 1])
def test_malformed_action_containers_fail_closed(field, value):
    s = started("documents")
    s[field] = value
    before = deepcopy(s)
    assert engine.available_actions(s) == []
    with pytest.raises(ValueError):
        engine.apply(s, "support_convoy", ("guards",))
    assert s == before


@pytest.mark.parametrize("hp", [None, [], "10", True, -1, 1.5])
def test_malformed_hp_fails_closed(hp):
    s = started()
    s["player"]["hp"] = hp
    before = deepcopy(s)
    assert engine.available_actions(s) == []
    assert s == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("npcs", None),
        ("npcs", {}),
        ("npcs", [{"id": []}]),
        ("npc_knowledge", None),
        ("npc_knowledge", []),
        ("npc_knowledge", {"npc_oren": None}),
        ("npc_knowledge", {"npc_oren": {"facts": []}}),
    ],
)
def test_malformed_npc_knowledge_no_partial_mutation(field, value):
    s = started()
    s[field] = value
    before = deepcopy(s)
    assert engine.notice_for_npc(s, "npc_oren") is None
    assert s == before


@pytest.mark.parametrize("value", [None, [], "bad", 5])
def test_malformed_root_state_fails_closed(value):
    assert engine.advance(value) == []
    assert engine.available_actions(value) == []
    assert engine.public_world(value) == {"world_events": [], "factions": {}}
    assert engine.notice_for_npc(value, "npc_oren") is None


@pytest.mark.parametrize("targets", [None, "guards", [[]], [None], []])
def test_malformed_command_targets_raise_domain_error(targets):
    s = started("documents")
    before = deepcopy(s)
    with pytest.raises(ValueError):
        engine.apply(s, "support_convoy", targets)
    assert s == before


@pytest.mark.parametrize(
    "malformation", ["unknown", "duplicate", "id_type", "due", "trust", "plan", "container"]
)
def test_malformed_event_fail_closed_without_mutation(malformation):
    s = started()
    if malformation == "unknown":
        s["world_events"][0]["id"] = "arbitrary_plan"
    elif malformation == "duplicate":
        s["world_events"].append(deepcopy(s["world_events"][0]))
    elif malformation == "id_type":
        s["world_events"][0]["id"] = []
    elif malformation == "due":
        s["world_events"][0]["due_at"] = -1
    elif malformation == "trust":
        s["factions"]["guards"]["trust"] = "CANARY"
    elif malformation == "plan":
        s["factions"]["guards"]["plan"] = "CANARY"
    else:
        s["world_events"] = {}
    s["elapsed_minutes"] = 300
    before = deepcopy(s)
    assert engine.advance(s) == []
    assert engine.available_actions(s) == []
    assert engine.public_world(s) == {"world_events": [], "factions": {}}
    assert before == s
