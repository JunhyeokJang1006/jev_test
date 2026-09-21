from copy import deepcopy

import pytest

from app import world_effects


def completed(ending="law"):
    return {
        "player": {"hp": 10},
        "quest": {"ending": ending},
        "followup": {"status": "completed", "private_branch_detail": "秘密"},
        "elapsed_minutes": 123,
        "npcs": [{"id": "npc_harlan"}],
        "npc_knowledge": {
            "npc_harlan": {"facts": {}, "claims": {}, "episodes": []},
            "npc_mira": {"facts": {}, "claims": {}, "episodes": []},
        },
    }


def test_existing_completed_state_schedules_from_current_time_and_exact_deadline():
    state = completed()
    assert world_effects.advance(state) is None
    assert state["world_effects"] == {"effective_at": 183, "applied": False, "notice": None}
    assert state["elapsed_minutes"] == 123
    state["elapsed_minutes"] = 182
    assert world_effects.advance(state) is None
    assert "market_policy" not in state
    state["elapsed_minutes"] = 183
    assert world_effects.advance(state) == world_effects.NOTICES["law"]
    assert state["elapsed_minutes"] == 183


def test_long_time_skip_applies_once_without_knowledge_propagation():
    state = completed()
    before_knowledge = deepcopy(state["npc_knowledge"])
    world_effects.advance(state)
    state["elapsed_minutes"] = 10000
    assert world_effects.advance(state)
    before = deepcopy(state)
    assert world_effects.advance(state) is None
    assert state == before
    assert state["npc_knowledge"] == before_knowledge


@pytest.mark.parametrize(
    "ending,policy,potion,supply",
    [("law", "relief", 6, 2), ("mercy", "shortage", 10, 4), ("exile", "caravan", 8, 2)],
)
def test_policy_prices_only_change_after_announcement(ending, policy, potion, supply):
    state = completed(ending)
    world_effects.advance(state)
    assert world_effects.prices(state) == {"healing_potions": 8, "camp_supplies": 3}
    state["elapsed_minutes"] += 60
    world_effects.advance(state)
    assert state["market_policy"] == policy
    assert world_effects.prices(state) == {"healing_potions": potion, "camp_supplies": supply}


def test_only_current_npc_learns_public_notice_after_publication():
    state = completed("mercy")
    world_effects.advance(state)
    before = deepcopy(state)
    assert world_effects.notice_for_npc(state, "npc_harlan") is None
    assert state == before
    state["elapsed_minutes"] += 60
    notice = world_effects.advance(state)
    before = deepcopy(state)
    assert world_effects.notice_for_npc(state, "npc_mira") is None
    assert state == before
    assert world_effects.notice_for_npc(state, "npc_harlan") == notice
    assert state["npc_knowledge"]["npc_harlan"]["facts"] == {
        "public_market_notice": {
            "text": notice,
            "source": "public_notice",
            "certainty": "known",
            "shareable": True,
        }
    }
    assert state["npc_knowledge"]["npc_mira"] == before["npc_knowledge"]["npc_mira"]
    assert "秘密" not in str(state["npc_knowledge"])


@pytest.mark.parametrize("state", [{}, {"quest": {"ending": "law"}}, completed("unknown")])
def test_missing_prerequisites_do_not_mutate(state):
    before = deepcopy(state)
    assert world_effects.advance(state) is None
    assert world_effects.notice_for_npc(state, "npc_harlan") is None
    assert world_effects.prices(state) == {"healing_potions": 8, "camp_supplies": 3}
    assert state == before


def test_wait_available_before_and_during_countdown_only():
    state = completed()
    assert world_effects.available_actions(state) == [world_effects.WAIT_LABEL]
    world_effects.advance(state)
    assert world_effects.available_actions(state) == [world_effects.WAIT_LABEL]
    state["elapsed_minutes"] += 60
    world_effects.advance(state)
    assert world_effects.available_actions(state) == []


@pytest.mark.parametrize("condition", ["dead", "combat", "active_followup", "missing_followup"])
def test_wait_unavailable(condition):
    state = completed()
    if condition == "dead":
        state["player"]["hp"] = 0
    elif condition == "combat":
        state["combat"] = {"active": True}
    elif condition == "active_followup":
        state["followup"]["status"] = "active"
    else:
        del state["followup"]
    before = deepcopy(state)
    assert world_effects.available_actions(state) == []
    assert state == before
