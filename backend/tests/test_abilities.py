import json
from copy import deepcopy

import pytest

from app.abilities import initialize, public_abilities
from app.context import scene_context
from app.dice import Dice
from app.game import ActionProposal, interpret_mock, noncommitting_input, resolve_action
from app.projection import public_state
from app.tactical import available_actions, resolve

from .helpers import request
from .test_tactical import Rolls, act
from .test_world import turn


@pytest.fixture
def fighting():
    return act(
        {
            "location_id": "greyhaven_inn",
            "encounter_enemy_id": "goblin_001",
            "player": {"hp": 10, "max_hp": 37, "ac": 17},
        },
        "start_combat",
        "goblin_001",
        10,
        10,
    )["state"]


@pytest.mark.parametrize(
    "hp,level,roll,expected", [(10, 3, 1, 14), (10, 4, 10, 24), (36, 3, 10, 37)]
)
def test_server_healing_bonus_budget_cap_and_no_enemy_response(fighting, hp, level, roll, expected):
    fighting["player"]["hp"] = hp
    fighting["progression"] = {"level": level}
    fighting["abilities"] = {"second_wind": {"remaining": 1, "healing_bonus": 999}}
    before = deepcopy(fighting)
    roller = Rolls(roll)
    result = resolve(fighting, "combat_second_wind", ("player",), roller=roller)
    state = result["state"]
    assert roller.used == [(10, roll)]
    assert state["player"]["hp"] == expected
    assert state["abilities"]["second_wind"]["remaining"] == 0
    assert state["combat"]["bonus_action_available"] is False
    assert state["combat"]["action_available"] is True
    assert state["combat"]["elapsed_seconds"] == 0
    assert result["event_payload"]["bonus"] == level
    assert result["event_payload"]["enemy_attacks"] == []
    assert fighting == before


@pytest.mark.parametrize("invalid", ["dead", "full", "no_bonus", "spent", "outside", "target"])
def test_rejected_use_has_no_rng_or_mutation(fighting, invalid):
    target = "player"
    if invalid == "dead":
        fighting["player"]["hp"] = 0
    elif invalid == "full":
        fighting["player"]["hp"] = 37
    elif invalid == "no_bonus":
        fighting["combat"]["bonus_action_available"] = False
    elif invalid == "spent":
        fighting["abilities"] = {"second_wind": {"remaining": 0}}
    elif invalid == "outside":
        fighting.pop("combat")
    else:
        target = "goblin_001"
    before, roller = deepcopy(fighting), Rolls()
    with pytest.raises(ValueError):
        resolve(fighting, "combat_second_wind", (target,), roller=roller)
    assert fighting == before and roller.used == []


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        {},
        {"second_wind": None},
        {"second_wind": {}},
        *[{"second_wind": {"remaining": v}} for v in (True, False, -1, 2, "1", 1.0)],
    ],
)
def test_malformed_present_field_fails_closed(fighting, value):
    fighting["abilities"] = value
    before = deepcopy(fighting)
    initialize(fighting)
    assert fighting == before
    assert public_abilities(fighting)["second_wind"]["remaining"] == 0
    assert "전투 회복력 사용" not in available_actions(fighting)


def test_legacy_projection_is_strict_and_nonmutating(fighting):
    assert public_abilities(fighting)["second_wind"]["remaining"] == 1
    assert "abilities" not in fighting
    initialize(fighting)
    fighting["abilities"]["SECRET"] = "SECRET"
    fighting["abilities"]["second_wind"]["SECRET"] = "SECRET"
    for view in (public_state(fighting), scene_context(fighting)):
        assert "SECRET" not in json.dumps(view)
        assert view["abilities"]["second_wind"] == {
            "remaining": 1,
            "maximum": 1,
            "healing_die": 10,
            "healing_bonus": 3,
            "recharge": "short_or_long_rest",
        }
    assert interpret_mock("전투 회복력 사용").intent == "combat_second_wind"
    assert any(
        c["intent"] == "combat_second_wind" for c in scene_context(fighting)["available_commands"]
    )


@pytest.mark.parametrize(
    "hp,hit_dice,rolls,healing", [(37, 2, (), 0), (37, 0, (), 0), (10, 0, (), 0), (10, 2, (4,), 6)]
)
def test_short_rest_recharges_with_only_needed_healing_rng(fighting, hp, hit_dice, rolls, healing):
    fighting.pop("combat")
    fighting["player"]["hp"] = hp
    fighting["resources"] = {"hit_dice": hit_dice, "camp_supplies": 1}
    fighting["abilities"] = {"second_wind": {"remaining": 0}}
    roller = Rolls(*rolls)
    result = resolve_action(fighting, interpret_mock("여관에서 짧은 휴식"), roller=roller)
    assert result.state["abilities"]["second_wind"]["remaining"] == 1
    assert result.state["player"]["hp"] == hp + healing
    assert result.state["resources"]["hit_dice"] == hit_dice - bool(rolls)
    assert result.state["elapsed_minutes"] == 60
    assert result.event_payload["healing_rolls"] == list(rolls)


def test_long_rest_recharges_full_hp_without_other_need(fighting):
    fighting.pop("combat")
    fighting["player"]["hp"] = 37
    fighting["resources"] = {"hit_dice": 2, "camp_supplies": 1}
    fighting["abilities"] = {"second_wind": {"remaining": 0}}
    result = resolve_action(fighting, interpret_mock("여관에서 긴 휴식"), roller=Rolls())
    assert result.state["abilities"]["second_wind"]["remaining"] == 1
    assert result.state["elapsed_minutes"] == 480
    assert result.state["resources"]["camp_supplies"] == 0


def test_round_and_encounter_start_do_not_recharge(fighting):
    spent = act(fighting, "combat_second_wind", "player", 1)["state"]
    after = act(spent, "combat_end_turn", "player")["state"]
    assert after["abilities"]["second_wind"]["remaining"] == 0
    assert after["combat"]["bonus_action_available"] is True
    after.pop("combat")
    after = act(after, "start_combat", "goblin_001", 10, 10)["state"]
    assert after["abilities"]["second_wind"]["remaining"] == 0


def test_api_persistence_replay_save_load_rejection_and_rest(monkeypatch):
    monkeypatch.setattr(Dice, "roll", lambda *_: 1)
    campaign = request("POST", "/api/campaign", json={}).json()
    assert turn(campaign, "전투 시작").status_code == 200
    body = {
        "campaign_id": campaign["id"],
        "expected_state_version": campaign["state_version"],
        "request_id": "00000000-0000-4000-8000-000000000799",
        "input": "전투 회복력 사용",
    }
    first = request("POST", "/api/game/turn", json=body)
    assert first.status_code == 200
    campaign.update(first.json())
    assert request("POST", "/api/game/turn", json=body).json() == first.json()
    state = deepcopy(campaign["state"])
    assert state["abilities"]["second_wind"]["remaining"] == 0
    assert request("GET", f"/api/campaign/{campaign['id']}").json()["state"] == state
    assert turn(campaign, "전투 회복력 사용").status_code == 422
    assert request("GET", f"/api/campaign/{campaign['id']}").json()["state"] == state
    saved = request("POST", f"/api/campaign/{campaign['id']}/save").json()
    restored = request(
        "POST", f"/api/campaign/{campaign['id']}/load", json={"snapshot_id": saved["snapshot_id"]}
    ).json()
    assert restored["state"]["abilities"] == state["abilities"]
    campaign.update(restored)
    for action in ("전투 이동: 왼쪽", "전투에서 후퇴", "여관에서 짧은 휴식"):
        assert turn(campaign, action).status_code == 200
    assert campaign["state"]["abilities"]["second_wind"]["remaining"] == 1


def test_proposal_cannot_inject_healing(fighting):
    proposal = ActionProposal("combat_second_wind", "spell", ("player",), "999", "999")
    result = resolve_action(fighting, proposal, roller=Rolls(1))
    assert result.state["player"]["hp"] == 14


@pytest.mark.parametrize("text", ["전투 회복력 안 쓴다", "전투 회복력을 사용하지 않는다"])
def test_explicit_recovery_negation(text):
    assert noncommitting_input(text, "combat_second_wind")
    assert interpret_mock(text).intent == "describe_action"


def test_growth_increases_bonus_without_recharge(fighting):
    fighting.pop("combat")
    fighting["abilities"] = {"second_wind": {"remaining": 0}}
    fighting["progression"] = {"level": 3, "xp": 100, "choices": [], "earned": []}
    result = resolve_action(fighting, interpret_mock("성장: 전투 숙련"), roller=Rolls())
    assert public_abilities(result.state)["second_wind"]["healing_bonus"] == 4
    assert public_abilities(result.state)["second_wind"]["remaining"] == 0


@pytest.mark.parametrize("ending", ["victory", "defeat"])
def test_encounter_end_and_defeat_care_do_not_recharge(fighting, ending):
    fighting = act(fighting, "combat_second_wind", "player", 1)["state"]
    enemy = fighting["combat"]["enemies"][0]
    enemy.update(x=2, y=2, hp=1)
    fighting["combat"]["enemies"][1]["hp"] = 0
    if ending == "victory":
        result = act(fighting, "basic_attack", "goblin_001", 20, 1, 1)
    else:
        fighting["player"]["hp"] = 1
        result = act(fighting, "combat_end_turn", "player", 20, 1, 1)
    assert result["state"]["combat"]["result"] == ending
    assert public_abilities(result["state"])["second_wind"]["remaining"] == 0
    if ending == "defeat":
        recovered = resolve_action(
            result["state"], interpret_mock("도움을 기다리기 (8시간)"), roller=Rolls()
        )
        assert recovered.state["player"]["hp"] > 0
        assert public_abilities(recovered.state)["second_wind"]["remaining"] == 0


@pytest.mark.parametrize(
    "first,second",
    [
        ("combat_second_wind", "combat_potion"),
        ("combat_potion", "combat_second_wind"),
        ("combat_second_wind", "combat_feint"),
        ("combat_feint", "combat_second_wind"),
    ],
)
def test_recovery_shares_bonus_budget(fighting, first, second):
    fighting["combat"]["enemies"][0].update(x=2, y=2)
    fighting["resources"] = {"healing_potions": 2}
    target = "goblin_001" if first == "combat_feint" else "player"
    result = act(fighting, first, target, *([1, 1] if first == "combat_potion" else [1]))
    with pytest.raises(ValueError):
        act(result["state"], second, "goblin_001" if second == "combat_feint" else "player")


@pytest.mark.parametrize("label,minutes", [("여관에서 짧은 휴식", 60), ("여관에서 긴 휴식", 480)])
def test_rest_api_snapshot_preserves_charges_and_clock(monkeypatch, label, minutes):
    monkeypatch.setattr(Dice, "roll", lambda *_: 1)
    campaign = request("POST", "/api/campaign", json={}).json()
    for action in ("전투 시작", "전투 회복력 사용", "전투 이동: 왼쪽", "전투에서 후퇴"):
        assert turn(campaign, action).status_code == 200
    before = campaign["state"]["elapsed_minutes"]
    assert turn(campaign, label).status_code == 200
    assert campaign["state"]["elapsed_minutes"] == before + minutes
    assert campaign["event"]["payload"]["rule_id"] == "greyhaven-recovery-v2"
    saved = request("POST", f"/api/campaign/{campaign['id']}/save").json()
    restored = request(
        "POST", f"/api/campaign/{campaign['id']}/load", json={"snapshot_id": saved["snapshot_id"]}
    ).json()
    assert restored["state"]["abilities"]["second_wind"]["remaining"] == 1
    assert restored["state"]["elapsed_minutes"] == before + minutes
