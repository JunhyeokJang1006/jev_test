from copy import deepcopy

import pytest

from app import expedition as engine


class FixedRoller:
    def __init__(self, result=20):
        self.result = result
        self.calls = 0

    def roll(self, sides):
        assert sides == 20
        self.calls += 1
        return self.result


def state(branch="law", supplies=1):
    return {
        "quest": {"ending": branch},
        "followup": {"status": "completed"},
        "world_consequences": {"tax_collection": "suspended"},
        "location_id": "market",
        "elapsed_minutes": 12,
        "player": {"hp": 10, "persuasion_bonus": 3, "stealth_bonus": 5},
        "resources": {"gold": 0, "camp_supplies": supplies},
        "npc_knowledge": {"npc_harlan": {"facts": {"private": "untouched"}}},
    }


def act(s, intent, target, roller=None):
    result = engine.apply(s, intent, (target,), roller or FixedRoller())
    s["elapsed_minutes"] += result["minutes"]
    return result


def started(branch="law", supplies=1):
    s = state(branch, supplies)
    act(s, "start_expedition", "watchtower")
    return s


def ready(s):
    s["location_id"] = "eastern_gate"
    act(s, "expedition_passage", "repair")
    s["location_id"] = "watchtower"
    for clue in sorted(engine.CLUES):
        act(s, "expedition_clue", clue)
    act(s, "expedition_approach", "stairs")


def test_full_completion_once_preserves_prior_chapters_and_information_boundary():
    s = started()
    prior = deepcopy({key: s[key] for key in ("quest", "followup", "world_consequences")})
    act(s, "expedition_prepare", "rope")
    ready(s)
    act(s, "resolve_expedition", "both")
    assert s["expedition"]["status"] == "resolved"
    assert s["resources"]["gold"] == 0
    assert "npc_oren" not in s["npc_knowledge"]
    s["location_id"] = "market"
    act(s, "report_expedition", "oren")
    assert s["expedition"]["status"] == "completed"
    assert s["resources"]["gold"] == 25
    assert s["npc_knowledge"]["npc_harlan"] == {"facts": {"private": "untouched"}}
    assert (
        s["npc_knowledge"]["npc_oren"]["facts"]["expedition_report"]["source"] == "witnessed_report"
    )
    assert prior == {key: s[key] for key in prior}
    before = deepcopy(s)
    with pytest.raises(ValueError):
        act(s, "report_expedition", "oren")
    assert s == before


@pytest.mark.parametrize("branch,skill,roll", [("mercy", "persuasion", 9), ("exile", "stealth", 7)])
def test_inherited_aid_changes_roll_outcome(branch, skill, roll):
    s = started(branch)
    act(s, "expedition_aid", branch)
    s["location_id"] = "eastern_gate"
    result = act(s, "expedition_passage", skill, FixedRoller(roll))
    assert result["dice"]["success"]
    assert result["dice"]["roll"] + result["dice"]["bonus"] == 14
    assert result["minutes"] == 3


def test_law_permit_guarantees_passage_without_roll():
    s = started()
    act(s, "expedition_aid", "law")
    s["location_id"] = "eastern_gate"
    roller = FixedRoller(1)
    assert act(s, "expedition_passage", "permit", roller)["minutes"] == 5
    assert roller.calls == 0
    assert engine.travel_allowed(s, "watchtower")


def test_failures_are_once_and_have_resource_free_recovery():
    s = started(supplies=0)
    s["location_id"] = "eastern_gate"
    roller = FixedRoller(1)
    for target in ("persuasion", "stealth"):
        assert act(s, "expedition_passage", target, roller)["minutes"] == 10
        before = deepcopy(s)
        with pytest.raises(ValueError):
            act(s, "expedition_passage", target, roller)
        assert s == before
    assert roller.calls == 2
    act(s, "expedition_passage", "repair")
    s["location_id"] = "watchtower"
    assert act(s, "expedition_approach", "stealth", roller)["minutes"] == 10
    with pytest.raises(ValueError):
        act(s, "expedition_approach", "stealth", roller)
    act(s, "expedition_approach", "stairs")
    act(s, "expedition_clue", "messenger_location")
    act(s, "resolve_expedition", "rescue")
    assert s["expedition"]["choice"] == "rescue"
    assert s["resources"] == {"gold": 0, "camp_supplies": 0}


@pytest.mark.parametrize("offset,allowed", [(5, True), (4, False), (0, False)])
def test_deadline_is_inclusive_of_completion_time(offset, allowed):
    s = started()
    act(s, "expedition_prepare", "rope")
    ready(s)
    s["elapsed_minutes"] = s["expedition"]["deadline_at"] - offset
    if allowed:
        act(s, "resolve_expedition", "both")
        assert s["elapsed_minutes"] == s["expedition"]["deadline_at"]
    else:
        before = deepcopy(s)
        with pytest.raises(ValueError):
            act(s, "resolve_expedition", "both")
        assert s == before
        act(s, "resolve_expedition", "documents")
        assert s["expedition"]["choice"] == "documents"


@pytest.mark.parametrize("missing", ["ready_rope", "messenger_location", "document_location"])
def test_both_requires_each_preparation(missing):
    s = started()
    act(s, "expedition_prepare", "rope")
    ready(s)
    s["expedition"]["clues"].remove(missing)
    with pytest.raises(ValueError):
        act(s, "resolve_expedition", "both")


def test_start_and_stage_gates_reject_without_mutation_or_roll():
    s = state()
    assert not engine.travel_allowed(s, "eastern_gate")
    assert not engine.travel_allowed(s, "watchtower")
    s["followup"]["status"] = "active"
    assert engine.available_actions(s) == []
    s = started(supplies=0)
    roller = FixedRoller()
    for intent, targets in [
        ("start_expedition", ("watchtower",)),
        ("expedition_prepare", ("rope",)),
        ("expedition_aid", ("mercy",)),
        ("resolve_expedition", ("rescue",)),
        ("expedition_clue", ("document_location",)),
        ("report_expedition", ("oren",)),
        ("expedition_aid", ()),
        ("expedition_aid", ("law", "law")),
    ]:
        before = deepcopy(s)
        with pytest.raises(ValueError):
            engine.apply(s, intent, targets, roller)
        assert before == s
    assert roller.calls == 0
    assert engine.travel_allowed(s, "market")
    assert engine.travel_allowed(s, "eastern_gate")
    assert not engine.travel_allowed(s, "watchtower")


def test_public_whitelist_and_deep_copy():
    s = started()
    s["expedition"]["secret"] = "hidden"
    s["expedition"]["resolution"] = {"secret": "hidden"}
    s["expedition"]["clues"] = [{"secret": "hidden"}]
    s["expedition"]["attempts"] = {
        "secret": {"roll": 10},
        "passage_stealth": {"roll": 2, "secret": "hidden"},
    }
    public = engine.public_expedition(s)
    assert "secret" not in repr(public)
    public["clues"].append("mutated")
    assert s["expedition"]["clues"] == [{"secret": "hidden"}]
    assert engine.public_expedition({}) == {}
