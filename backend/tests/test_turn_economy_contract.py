"""명시 전투 턴의 저장, 재송신, 공개 context와 자원 소비 통합 검사."""

from app.context import scene_context
from app.dice import Dice

from .helpers import request
from .test_world import turn


def test_spent_turn_budget_survives_save_and_replay_without_extra_enemy_response(monkeypatch):
    rolls = []

    def roll(self, sides):
        rolls.append(sides)
        return 11 if sides == 20 else 3

    monkeypatch.setattr(Dice, "roll", roll)
    campaign = request("POST", "/api/campaign", json={}).json()
    assert turn(campaign, "전투 시작").status_code == 200
    assert rolls == [20, 20]
    for label in ["전투 이동: 오른쪽", "전투 이동: 오른쪽", "고블린을 공격한다", "전투 이동: 아래"]:
        assert turn(campaign, label).status_code == 200
        assert campaign["event"]["payload"]["enemy_attacks"] == []
    assert campaign["state"]["combat"]["elapsed_seconds"] == 0
    envelope = {
        "campaign_id": campaign["id"],
        "expected_state_version": campaign["state_version"],
        "request_id": "00000000-0000-4000-8000-000000000666",
        "input": "전투 중 치유 물약",
    }
    healed = request("POST", "/api/game/turn", json=envelope)
    assert healed.status_code == 200
    campaign.update(healed.json())
    count = len(rolls)
    assert request("POST", "/api/game/turn", json=envelope).json() == healed.json()
    assert len(rolls) == count
    assert campaign["state"]["resources"]["healing_potions"] == 1
    assert campaign["state"]["player"]["hp"] == 37
    budget = campaign["state"]["combat"]
    assert budget["movement_remaining"] == 0
    assert budget["action_available"] is False
    assert budget["bonus_action_available"] is False
    assert campaign["actions"] == ["턴 종료"]
    context = scene_context(campaign["state"])
    assert [item["label"] for item in context["available_commands"]] == ["턴 종료"]
    for label in ["전투 이동: 왼쪽", "방어 태세", "전투 중 치유 물약"]:
        assert turn(campaign, label).status_code == 422
    assert len(rolls) == count
    snapshot = request("POST", f"/api/campaign/{campaign['id']}/save").json()
    restored = request(
        "POST",
        f"/api/campaign/{campaign['id']}/load",
        json={"snapshot_id": snapshot["snapshot_id"]},
    ).json()
    assert restored["state"]["combat"] == budget
    assert restored["actions"] == ["턴 종료"]
    assert restored["state"]["resources"]["healing_potions"] == 1
    ending = {
        "campaign_id": campaign["id"],
        "expected_state_version": campaign["state_version"],
        "request_id": "00000000-0000-4000-8000-000000000667",
        "input": "턴 종료",
    }
    result = request("POST", "/api/game/turn", json=ending)
    assert result.status_code == 200
    data = result.json()
    assert len(data["event"]["payload"]["enemy_attacks"]) == 2
    assert data["state"]["combat"]["round"] == 2
    assert data["state"]["combat"]["elapsed_seconds"] == 6
    assert data["state"]["combat"]["movement_remaining"] == 3
    assert data["state"]["combat"]["action_available"] is True
    assert data["state"]["combat"]["bonus_action_available"] is True
    count = len(rolls)
    assert request("POST", "/api/game/turn", json=ending).json() == data
    assert len(rolls) == count
    untouched = request("GET", f"/api/campaign/{restored['id']}").json()
    assert untouched["state"]["combat"] == budget


def test_complete_fight_with_turn_budgets_then_resume_exploration(monkeypatch):
    monkeypatch.setattr(Dice, "roll", lambda self, sides: 11 if sides == 20 else 4)
    campaign = request("POST", "/api/campaign", json={}).json()
    # 1회 피해 7로 한 적씩 제압한다. 주요 행동은 턴당 한 번이므로 적 차례를 건너뛸 수 없다.
    for label in ["전투 시작", "전투 이동: 오른쪽", "전투 이동: 오른쪽", "고블린을 공격한다"]:
        assert turn(campaign, label).status_code == 200
    assert campaign["state"]["combat"]["enemies"][0]["hp"] == 0
    assert campaign["state"]["combat"]["active"] is True
    assert campaign["state"]["progression"]["xp"] == 0
    assert turn(campaign, "턴 종료").status_code == 200
    assert turn(campaign, "전투 이동: 아래").status_code == 200
    assert turn(campaign, "두 번째 고블린을 공격한다").status_code == 200
    assert campaign["state"]["combat"]["result"] == "victory"
    assert campaign["event"]["payload"]["enemy_attacks"] == []
    assert campaign["state"]["progression"]["xp"] == 25
    assert "턴 종료" not in campaign["actions"]
    assert turn(campaign, "시장으로 이동").status_code == 200
    assert campaign["state"]["location_id"] == "market"
    assert campaign["state"]["progression"]["xp"] == 25
    assert "combat" not in campaign["state"]
