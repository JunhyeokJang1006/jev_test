from copy import deepcopy

import pytest

from app.context import scene_context
from app.game import interpret_mock, resolve_action
from app.projection import public_state
from app.resources import DEFAULT, available_actions

from .helpers import request
from .test_game import Rolls
from .test_world import turn


def state():
    return {
        "location_id": "greyhaven_inn",
        "player": {"hp": 1, "max_hp": 37},
        "resources": dict(DEFAULT),
        "npcs": [],
    }


def test_potion_caps_healing_and_does_not_mutate_input():
    original = state()
    original["player"]["hp"] = 35
    before = deepcopy(original)
    outcome = resolve_action(original, interpret_mock("치유 물약 사용"), roller=Rolls(4, 4))
    assert original == before
    assert outcome.state["player"]["hp"] == 37
    assert outcome.state["resources"]["healing_potions"] == 1
    assert outcome.event_payload["healing_rolls"] == [4, 4]
    assert outcome.event_payload["healing"] == 2
    assert outcome.state["elapsed_minutes"] == 1
    with pytest.raises(ValueError):
        resolve_action(outcome.state, interpret_mock("치유 물약 사용"), roller=Rolls())


def test_short_and_long_rest_consume_resources_and_cross_midnight():
    outcome = resolve_action(state(), interpret_mock("여관에서 짧은 휴식"), roller=Rolls(3))
    assert outcome.state["player"]["hp"] == 6
    assert outcome.state["resources"]["hit_dice"] == 1
    outcome = resolve_action(outcome.state, interpret_mock("여관에서 긴 휴식"), roller=Rolls())
    assert outcome.state["player"]["hp"] == 37
    assert outcome.state["resources"]["hit_dice"] == 2
    assert outcome.state["resources"]["camp_supplies"] == 1
    assert outcome.state["day"] == 2 and outcome.state["time"] == "06:36"
    assert outcome.state["elapsed_minutes"] == 540


@pytest.mark.parametrize("mutation", ["dead", "combat", "no_resources", "completed"])
def test_unavailable_recovery_consumes_nothing(mutation):
    original = state()
    if mutation == "dead":
        original["player"]["hp"] = 0
    elif mutation == "combat":
        original["combat"] = {"active": True}
    elif mutation == "completed":
        original["quest"] = {"ending": "law"}
    else:
        original["resources"] = dict.fromkeys(DEFAULT, 0)
    before = deepcopy(original)
    for action in ["치유 물약 사용", "여관에서 짧은 휴식", "여관에서 긴 휴식"]:
        with pytest.raises(ValueError):
            resolve_action(original, interpret_mock(action), roller=Rolls())
    assert original == before
    assert not available_actions(original)


def test_buying_checks_gold_cap_location_and_partial_resources():
    original = state()
    action = interpret_mock("치유 물약 구매 (8골드)")
    with pytest.raises(ValueError):
        resolve_action(original, action, roller=Rolls())
    original["location_id"] = "market"
    original["resources"] = {"gold": 8}
    outcome = resolve_action(original, action, roller=Rolls())
    assert outcome.state["resources"] == {"gold": 0, "healing_potions": 1}
    with pytest.raises(ValueError):
        resolve_action(outcome.state, action, roller=Rolls())
    original["resources"] = {"gold": 100, "healing_potions": 5}
    with pytest.raises(ValueError):
        resolve_action(original, action, roller=Rolls())


def test_legacy_defaults_preserve_zero_and_match_public_context():
    original = state()
    del original["resources"]
    view = public_state(original)
    assert view["resources"] == DEFAULT
    assert "resources" not in original
    assert scene_context(original)["resources"] == DEFAULT
    outcome = resolve_action(original, interpret_mock("치유 물약 사용"), roller=Rolls(1, 1))
    assert outcome.state["resources"]["healing_potions"] == 1
    original["resources"] = {**DEFAULT, "healing_potions": 0, "secret": "SECRET"}
    assert "치유 물약 사용" not in available_actions(original)
    assert "secret" not in public_state(original)["resources"]


def test_full_hp_can_restore_spent_hit_dice_with_long_rest():
    original = state()
    original["player"]["hp"] = 37
    original["resources"]["hit_dice"] = 0
    outcome = resolve_action(original, interpret_mock("여관에서 긴 휴식"), roller=Rolls())
    assert outcome.state["resources"]["hit_dice"] == 2
    assert outcome.state["resources"]["camp_supplies"] == 1


def test_recovery_idempotency_and_saved_resource_branch():
    campaign = request("POST", "/api/campaign", json={}).json()
    saved = request("POST", f"/api/campaign/{campaign['id']}/save").json()
    payload = {
        "campaign_id": campaign["id"],
        "expected_state_version": 0,
        "input": "여관에서 긴 휴식",
        "request_id": "00000000-0000-4000-8000-000000000333",
    }
    first = request("POST", "/api/game/turn", json=payload)
    assert first.status_code == 200
    assert first.json()["state"]["resources"]["camp_supplies"] == 1
    assert request("POST", "/api/game/turn", json=payload).json() == first.json()
    restored = request(
        "POST", f"/api/campaign/{campaign['id']}/load", json={"snapshot_id": saved["snapshot_id"]}
    ).json()
    assert restored["state"]["resources"] == DEFAULT
    assert (
        request("GET", f"/api/campaign/{campaign['id']}").json()["state"]["resources"][
            "camp_supplies"
        ]
        == 1
    )
    assert turn(restored, "여관에서 긴 휴식").status_code == 200
