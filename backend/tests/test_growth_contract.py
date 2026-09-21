import json

from app.game import interpret_mock, resolve_action
from app.projection import public_state
from app.storage import connect

from .helpers import request
from .test_game import Rolls


def test_growth_projection_rejects_nested_private_fields():
    state = {
        "progression": {
            "level": 3,
            "xp": 100,
            "earned": ["SECRET"],
            "choices": ["combat", {"secret": "SECRET"}, "SECRET"],
        }
    }
    assert public_state(state)["progression"]["choices"] == ["combat"]
    assert "SECRET" not in json.dumps(public_state(state))


def test_training_is_idempotent_and_restore_preserves_unspent_choice():
    campaign = request("POST", "/api/campaign", json={}).json()
    # 격리 fixture DB에 성장 경계 상태를 구성한다. 실제 플레이 DB는 접근하지 않는다.
    state = campaign["state"]
    state["progression"].update(xp=100, earned=["test_milestone"])
    connection = connect()
    connection.execute(
        "UPDATE campaigns SET state_json=? WHERE id=?", (json.dumps(state), campaign["id"])
    )
    connection.close()
    snapshot = request("POST", f"/api/campaign/{campaign['id']}/save").json()
    payload = {
        "campaign_id": campaign["id"],
        "input": "성장: 전투 숙련",
        "expected_state_version": 0,
        "request_id": "00000000-0000-4000-8000-000000000444",
    }
    first = request("POST", "/api/game/turn", json=payload)
    assert first.status_code == 200
    assert first.json()["state"]["player"]["attack_bonus"] == 6
    assert first.json()["state"]["progression"]["level"] == 4
    assert request("POST", "/api/game/turn", json=payload).json() == first.json()
    restored = request(
        "POST",
        f"/api/campaign/{campaign['id']}/load",
        json={"snapshot_id": snapshot["snapshot_id"]},
    ).json()
    assert restored["state"]["progression"]["level"] == 3
    assert "성장: 설득의 기술" in restored["actions"]
    original = request("GET", f"/api/campaign/{campaign['id']}").json()
    assert original["state"]["progression"]["level"] == 4


def test_combat_victory_awards_xp_only_once_without_mutating_input():
    state = {
        "location_id": "greyhaven_inn",
        "encounter_enemy_id": "goblin_001",
        "player": {"hp": 31},
        "combat": {
            "active": True,
            "enemy_id": "goblin_001",
            "enemy_hp": 1,
            "player_x": 1,
            "player_y": 2,
            "enemy_x": 2,
            "enemy_y": 2,
        },
    }
    outcome = resolve_action(state, interpret_mock("고블린을 공격한다"), roller=Rolls(19, 1))
    assert outcome.event_payload["xp_gained"] == 25
    assert outcome.state["progression"]["xp"] == 25
    assert "progression" not in state
