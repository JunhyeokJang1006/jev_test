import json

from app.context import scene_context
from app.dice import Dice
from app.game import interpret_mock
from app.projection import public_state
from app.storage import connect

from .helpers import request
from .test_world import turn


def test_second_enemy_target_persists_and_does_not_hit_first(monkeypatch):
    monkeypatch.setattr(Dice, "roll", lambda self, sides: 11 if sides == 20 else 3)
    campaign = request("POST", "/api/campaign", json={}).json()
    assert turn(campaign, "전투 시작").status_code == 200
    combat = campaign["state"]["combat"]
    assert len(combat["enemies"]) == 2
    assert len({(enemy["x"], enemy["y"]) for enemy in combat["enemies"]}) == 2
    combat.update(player_x=2, player_y=2)
    combat["enemies"][1].update(x=3, y=2)
    connection = connect()
    connection.execute(
        "UPDATE campaigns SET state_json=? WHERE id=?",
        (json.dumps(campaign["state"]), campaign["id"]),
    )
    connection.close()
    assert turn(campaign, "두 번째 고블린을 공격한다").status_code == 200
    assert campaign["state"]["combat"]["enemies"][0]["hp"] == 7
    assert campaign["state"]["combat"]["enemies"][1]["hp"] == 1
    assert campaign["event"]["payload"]["target_id"] == "goblin_002"
    assert [entry["enemy_id"] for entry in campaign["event"]["payload"]["enemy_attacks"]] == [
        "goblin_001",
        "goblin_002",
    ]
    snapshot = request("POST", f"/api/campaign/{campaign['id']}/save").json()
    restored = request(
        "POST",
        f"/api/campaign/{campaign['id']}/load",
        json={"snapshot_id": snapshot["snapshot_id"]},
    ).json()
    assert restored["state"]["combat"] == campaign["state"]["combat"]
    state = restored["state"]
    state["combat"]["enemies"][0]["secret"] = "SECRET"
    assert "SECRET" not in json.dumps(public_state(state))
    assert "SECRET" not in json.dumps(scene_context(state))


def test_mock_preserves_explicit_second_target():
    proposal = interpret_mock("두번째 고블린을 검으로 공격할게")
    assert proposal.target_ids == ("goblin_002",)
