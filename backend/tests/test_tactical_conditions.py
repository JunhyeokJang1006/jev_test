import json
from copy import deepcopy

import pytest

from app.context import scene_context
from app.dice import Dice
from app.projection import public_payload, public_state
from app.tactical import available_actions, resolve

from .helpers import request
from .test_tactical import Rolls, act
from .test_world import turn


@pytest.fixture
def fighting():
    state = {
        "location_id": "greyhaven_inn",
        "encounter_enemy_id": "goblin_001",
        "player": {"hp": 20, "ac": 17},
        "resources": {"healing_potions": 2},
    }
    state = act(state, "start_combat", "goblin_001", 10, 10)["state"]
    state["combat"]["enemies"][0].update(x=2, y=2, hp=40)
    state["combat"]["enemies"][1].update(x=1, y=3, hp=40)
    return state


@pytest.mark.parametrize(
    "intent,condition,budget",
    [
        ("combat_shove", "prone", "action_available"),
        ("combat_feint", "exposed", "bonus_action_available"),
    ],
)
@pytest.mark.parametrize("roll,success", [(1, False), (10, False), (11, True), (20, True)])
def test_check_boundaries_and_spending(fighting, intent, condition, budget, roll, success):
    before = deepcopy(fighting)
    result = act(fighting, intent, "goblin_002", roll)
    assert result["event_payload"]["success"] is success
    assert result["event_payload"]["dc"] == 14
    assert result["event_payload"]["bonus"] == 3
    assert result["event_payload"]["condition"] == condition
    state = result["state"]
    assert state["combat"]["enemies"][1]["conditions"] == ([condition] if success else [])
    assert state["combat"][budget] is False
    assert state["combat"]["elapsed_seconds"] == 0
    assert result["event_payload"]["enemy_attacks"] == []
    with pytest.raises(ValueError):
        act(state, intent, "goblin_001")
    assert fighting == before


@pytest.mark.parametrize(
    "intent,condition", [("combat_shove", "prone"), ("combat_feint", "exposed")]
)
@pytest.mark.parametrize("invalid", ["distant", "dead", "already", "missing", "not_started"])
def test_invalid_actions_do_not_roll_or_mutate(fighting, intent, condition, invalid):
    enemy = fighting["combat"]["enemies"][0]
    if invalid == "distant":
        enemy.update(x=4, y=2)
    elif invalid == "dead":
        enemy["hp"] = 0
    elif invalid == "already":
        enemy["conditions"] = [condition]
    elif invalid == "missing":
        fighting["combat"]["enemies"].pop(0)
    else:
        fighting.pop("combat")
    before = deepcopy(fighting)
    roller = Rolls()
    with pytest.raises(ValueError):
        resolve(fighting, intent, ("goblin_001",), roller=roller)
    assert not roller.used
    assert fighting == before


@pytest.mark.parametrize(
    "rolls,critical,hit",
    [((1, 20, 2, 3), True, True), ((1, 2), False, False), ((12, 1, 2), False, True)],
)
def test_exposed_attack_consumed_on_hit_and_miss(fighting, rolls, critical, hit):
    fighting = act(fighting, "combat_feint", "goblin_002", 11)["state"]
    result = act(fighting, "basic_attack", "goblin_002", *rolls)
    payload = result["event_payload"]
    assert payload["attack_rolls"] == list(rolls[:2])
    assert payload["roll"] == max(rolls[:2])
    assert payload["critical"] is critical and payload["hit"] is hit
    assert payload["condition_consumed"] == "exposed"
    assert result["state"]["combat"]["enemies"][1]["conditions"] == []
    assert public_payload(payload)["attack_rolls"] == list(rolls[:2])


def test_prone_skips_whole_phase_and_exposed_expires_for_all(fighting):
    fighting = act(fighting, "combat_feint", "goblin_001", 11)["state"]
    fighting = act(fighting, "combat_shove", "goblin_001", 11)["state"]
    fighting["combat"]["enemies"][1]["conditions"] = ["exposed"]
    result = act(fighting, "combat_end_turn", "player", 1)
    first, second = result["event_payload"]["enemy_attacks"]
    assert first["stood_up"] and not first["moved"] and not first["attacked"]
    assert first["from"] == first["to"] == [2, 2]
    assert second["attacked"]
    assert all(not e["conditions"] for e in result["state"]["combat"]["enemies"])
    assert result["state"]["combat"]["elapsed_seconds"] == 6
    assert public_payload(first)["stood_up"] is True


def test_exposure_is_target_specific_and_normal_attack_keeps_single_roll(fighting):
    fighting = act(fighting, "combat_feint", "goblin_002", 11)["state"]
    roller = Rolls(1)
    result = resolve(fighting, "basic_attack", ("goblin_001",), roller=roller)
    assert roller.used == [(20, 1)]
    assert result["event_payload"]["attack_rolls"] == [1]
    assert result["state"]["combat"]["enemies"][1]["conditions"] == ["exposed"]
    assert "condition_consumed" not in result["event_payload"]


def test_prone_enemy_cannot_move_when_player_steps_away(fighting):
    fighting = act(fighting, "combat_shove", "goblin_001", 11)["state"]
    fighting = act(fighting, "combat_move", "left")["state"]
    result = act(fighting, "combat_end_turn", "player", 1)
    first, second = result["event_payload"]["enemy_attacks"]
    assert first["stood_up"] and first["to"] == [2, 2]
    assert not first["moved"] and not first["attacked"]
    assert second["moved"] and second["attacked"]


@pytest.mark.parametrize("first", ["combat_dash", "combat_shove", "combat_defend", "basic_attack"])
@pytest.mark.parametrize("second", ["combat_dash", "combat_shove", "combat_defend", "basic_attack"])
def test_all_main_actions_share_budget(fighting, first, second):
    target = "goblin_001" if first in {"combat_shove", "basic_attack"} else "player"
    state = act(fighting, first, target, *([1] if target == "goblin_001" else []))["state"]
    target = "goblin_001" if second in {"combat_shove", "basic_attack"} else "player"
    with pytest.raises(ValueError):
        act(state, second, target)


@pytest.mark.parametrize(
    "first,second", [("combat_feint", "combat_potion"), ("combat_potion", "combat_feint")]
)
def test_bonus_actions_share_budget(fighting, first, second):
    target = "goblin_001" if first == "combat_feint" else "player"
    state = act(fighting, first, target, *([1] if first == "combat_feint" else [1, 1]))["state"]
    with pytest.raises(ValueError):
        act(state, second, "goblin_001" if second == "combat_feint" else "player")


def test_dash_extends_spent_movement_without_time_or_response(fighting):
    fighting["combat"]["movement_remaining"] = 0
    result = act(fighting, "combat_dash", "player")
    assert result["state"]["combat"]["movement_remaining"] == 3
    assert result["state"]["combat"]["elapsed_seconds"] == 0
    assert result["event_payload"]["enemy_attacks"] == []
    assert "전력 질주" not in available_actions(result["state"])


@pytest.mark.parametrize("ending", ["victory", "fled", "defeat"])
def test_all_ending_conditions_are_cleared(fighting, ending):
    for enemy in fighting["combat"]["enemies"]:
        enemy["conditions"] = ["exposed"]
    if ending == "victory":
        fighting["combat"]["enemies"][0]["hp"] = 0
        fighting["combat"]["enemies"][1]["hp"] = 1
        result = act(fighting, "basic_attack", "goblin_002", 20, 1, 1, 1)
    elif ending == "fled":
        fighting["combat"]["player_x"] = 0
        result = act(fighting, "combat_flee", "exit")
    else:
        fighting["player"]["hp"] = 1
        fighting["combat"]["enemies"][1]["conditions"].append("prone")
        result = act(fighting, "combat_end_turn", "player", 20, 1, 1)
    assert result["state"]["combat"]["result"] == ending
    assert all(not e["conditions"] for e in result["state"]["combat"]["enemies"])
    assert result["state"]["combat"]["elapsed_seconds"] == 6


def test_unknown_conditions_hidden_from_public_and_context(fighting):
    fighting["combat"]["enemies"][0]["conditions"] = ["prone", "SECRET", {"secret": True}]
    before = deepcopy(fighting)
    for view in (public_state(fighting), scene_context(fighting)):
        assert "SECRET" not in json.dumps(view)
        assert '"secret"' not in json.dumps(view)
    assert public_state(fighting)["combat"]["enemies"][0]["conditions"] == ["prone"]
    assert public_payload({"condition": "SECRET", "condition_consumed": "SECRET"}) == {}
    assert fighting == before


def test_api_condition_save_load_replay_context_and_zero_budgets(monkeypatch):
    monkeypatch.setattr(Dice, "roll", lambda *_: 11)
    campaign = request("POST", "/api/campaign", json={}).json()
    for action in ("전투 시작", "전투 이동: 오른쪽", "전투 이동: 오른쪽"):
        assert turn(campaign, action).status_code == 200
    body = {
        "campaign_id": campaign["id"],
        "expected_state_version": campaign["state_version"],
        "request_id": "00000000-0000-4000-8000-000000000777",
        "input": "고블린 교란하기",
    }
    response = request("POST", "/api/game/turn", json=body)
    assert response.status_code == 200
    campaign.update(response.json())
    assert request("POST", "/api/game/turn", json=body).json() == response.json()
    for action in ("고블린 밀쳐 넘어뜨리기", "전투 이동: 위"):
        assert turn(campaign, action).status_code == 200
    state = campaign["state"]
    assert state["combat"]["movement_remaining"] == 0
    assert state["combat"]["action_available"] is False
    assert state["combat"]["bonus_action_available"] is False
    assert state["combat"]["enemies"][0]["conditions"] == ["exposed", "prone"]
    assert {c["label"] for c in scene_context(state)["available_commands"]} == {"턴 종료"}
    saved = request("POST", f"/api/campaign/{campaign['id']}/save").json()
    restored = request(
        "POST", f"/api/campaign/{campaign['id']}/load", json={"snapshot_id": saved["snapshot_id"]}
    ).json()
    assert restored["state"]["combat"] == state["combat"]
    campaign.update(restored)
    assert turn(campaign, "턴 종료").status_code == 200
    assert campaign["event"]["payload"]["enemy_attacks"][0]["stood_up"] is True
    assert campaign["state"]["combat"]["elapsed_seconds"] == 6
