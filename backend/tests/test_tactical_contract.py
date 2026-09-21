import json

from app.context import scene_context
from app.dice import Dice
from app.game import interpret_mock, resolve_action
from app.projection import public_state

from .helpers import request
from .test_game import Rolls
from .test_world import turn


def test_tactical_save_projection_and_context(monkeypatch):
    monkeypatch.setattr(Dice, "roll", lambda *_: 11)
    campaign = request("POST", "/api/campaign", json={}).json()
    assert turn(campaign, "전투 시작").status_code == 200
    assert campaign["event"]["payload"]["initiative"]["player_roll"] == 11
    state = campaign["state"]
    before = json.dumps(state, sort_keys=True)
    saved = request("POST", f"/api/campaign/{campaign['id']}/save").json()
    restored = request(
        "POST", f"/api/campaign/{campaign['id']}/load", json={"snapshot_id": saved["snapshot_id"]}
    ).json()
    assert restored["state"]["combat"] == state["combat"]
    assert json.dumps(state, sort_keys=True) == before
    context = scene_context(state)
    assert {item["label"] for item in context["available_commands"]} == set(campaign["actions"])
    assert "전투에서 후퇴" not in campaign["actions"]
    assert "여관에서 긴 휴식" not in campaign["actions"]
    state["combat"]["private"] = "SECRET"
    state["combat"]["initiative"]["private"] = "SECRET"
    state["combat"]["walls"].append(["SECRET", 1])
    assert "SECRET" not in json.dumps(public_state(state))
    assert "SECRET" not in json.dumps(scene_context(state))


def test_legacy_combat_projection_does_not_restart_initiative():
    state = {
        "location_id": "greyhaven_inn",
        "encounter_enemy_id": "goblin_001",
        "player": {"hp": 31, "ac": 17},
        "combat": {"active": True, "enemy_hp": 3},
    }
    public = public_state(state)
    assert public["combat"]["player_x"] == 1
    assert "player_x" not in state["combat"]
    outcome = resolve_action(state, interpret_mock("전투 이동: 왼쪽"), roller=Rolls())
    assert outcome.state["combat"]["enemy_hp"] == 3
    assert outcome.state["combat"]["player_x"] == 0
    assert outcome.state["combat_seconds"] == 0
    assert outcome.state["combat"]["movement_remaining"] == 2


def test_combat_seconds_accumulate_into_world_clock():
    state = {
        "location_id": "greyhaven_inn",
        "encounter_enemy_id": "goblin_001",
        "player": {"hp": 31, "ac": 17},
        "combat_seconds": 54,
        "elapsed_minutes": 0,
        "combat": {"active": True, "enemy_hp": 3, "elapsed_seconds": 54},
    }
    outcome = resolve_action(state, interpret_mock("전투 이동: 왼쪽"), roller=Rolls())
    assert outcome.state["combat_seconds"] == 54
    outcome = resolve_action(outcome.state, interpret_mock("턴 종료"), roller=Rolls())
    assert outcome.state["combat_seconds"] == 60
    assert outcome.state["elapsed_minutes"] == 1
    assert outcome.state["time"] == "21:37"
