import json
from copy import deepcopy

import pytest

from app import defeat
from app.context import scene_context
from app.dice import Dice
from app.game import ActionProposal, interpret_mock, resolve_action
from app.projection import public_payload, public_state
from app.world import available_actions

from .helpers import request
from .test_game import Rolls
from .test_world import turn


@pytest.fixture
def fallen():
    state = {
        "location_id": "greyhaven_inn",
        "encounter_enemy_id": "goblin_001",
        "player": {"hp": 1, "max_hp": 37, "ac": 17},
        "resources": {"gold": 20, "camp_supplies": 2, "hit_dice": 0, "healing_potions": 0},
        "combat": {"active": True, "enemy_hp": 7, "enemy_x": 2, "enemy_y": 2},
        "quest": {"status": "active", "clues": ["seal_cache"]},
        "inventory": ["royal_seal"],
        "npc_memories": {"npc_harlan": ["previous episode"]},
        "progression": {"level": 3, "xp": 20, "earned": ["prior"], "choices": []},
        "journal": [{"text": "기존 진행"}],
        "elapsed_minutes": 17,
    }
    return resolve_action(state, interpret_mock("턴 종료"), roller=Rolls(19, 1)).state


@pytest.mark.parametrize(
    "method,gold,supplies,minutes",
    [
        ("medic", 10, 0, 60),
        ("supplies", 0, 1, 240),
        ("wait", 0, 0, 480),
    ],
)
def test_actual_defeat_recovery_preserves_progress_and_spends(
    fallen, method, gold, supplies, minutes
):
    assert fallen["defeat"] == {"status": "pending"}
    assert set(available_actions(fallen)) == set(defeat.COMMANDS)
    before = deepcopy(fallen)
    label = next(label for label, (_, target) in defeat.COMMANDS.items() if target == method)
    rolls = Rolls()
    outcome = resolve_action(fallen, interpret_mock(label), roller=rolls)
    state = outcome.state
    assert fallen == before
    assert rolls.used == []
    assert state["player"]["hp"] == 18
    assert state["defeat"] == {
        "status": "recovered",
        "method": method,
        "gold_spent": gold,
        "supplies_spent": supplies,
        "minutes": minutes,
        "healing": 18,
    }
    assert state["elapsed_minutes"] == before["elapsed_minutes"] + minutes
    assert state["resources"] == {
        "gold": 20 - gold,
        "camp_supplies": 2 - supplies,
        "hit_dice": 0,
        "healing_potions": 0,
    }
    for key in ("quest", "inventory", "npc_memories", "combat", "progression"):
        assert state[key] == before[key]
    assert state["journal"][:-1] == before["journal"]
    assert state["hidden"] is False
    assert "xp_gained" not in outcome.event_payload
    assert "시장으로 이동" in available_actions(state)
    assert "전투 시작" not in available_actions(state)
    for retry in (label, "전투 시작", "고블린을 공격한다"):
        with pytest.raises(ValueError):
            resolve_action(state, interpret_mock(retry), roller=rolls)


def test_legacy_zero_resources_can_wait_and_small_hp_is_capped(fallen):
    fallen.pop("defeat")
    fallen["resources"] = dict.fromkeys(fallen["resources"], 0)
    fallen["player"]["max_hp"] = 1
    assert available_actions(fallen) == ["도움을 기다리기 (8시간)"]
    result = resolve_action(fallen, interpret_mock("도움을 기다리기 (8시간)"), roller=Rolls())
    assert result.state["player"]["hp"] == 1
    assert result.state["resources"] == fallen["resources"]


@pytest.mark.parametrize(
    "change",
    [
        {"location_id": "market"},
        {"encounter_enemy_id": "other"},
        {"player": {"hp": 1}},
        {"player": {"hp": -1}},
        {"combat": {"active": True, "result": "defeat"}},
        {"combat": {"active": False, "result": "victory"}},
        {"defeat": {"status": "recovered"}},
    ],
)
def test_invalid_recovery_has_no_mutation_or_rng(fallen, change):
    fallen.update(change)
    before = deepcopy(fallen)
    rolls = Rolls()
    with pytest.raises(ValueError):
        resolve_action(fallen, interpret_mock("도움을 기다리기 (8시간)"), roller=rolls)
    assert fallen == before
    assert rolls.used == []


def test_zero_hp_rejects_other_actions_bad_targets_and_unaffordable_costs(fallen):
    fallen["resources"] = dict.fromkeys(fallen["resources"], 0)
    for label in (
        "시장으로 이동",
        "주변 조사",
        "치유 물약 사용",
        "여관에서 긴 휴식",
        "전투 시작",
        "하를란과 대화",
        "성장: 전투 숙련",
        *list(defeat.COMMANDS)[:2],
    ):
        with pytest.raises(ValueError):
            resolve_action(fallen, interpret_mock(label), roller=Rolls())
    for targets in ((), ("other",), ("wait", "wait")):
        with pytest.raises(ValueError):
            resolve_action(
                fallen,
                ActionProposal("recover_defeat", "exploration", targets, None, None),
                roller=Rolls(),
            )


def test_defeat_projection_whitelists_scalars(fallen):
    fallen["defeat"].update(private="PRIVATE_SECRET", method={"secret": "PRIVATE_SECRET"})
    assert public_state(fallen)["defeat"] == {"status": "pending"}
    assert "PRIVATE_SECRET" not in json.dumps(public_state(fallen))
    assert "PRIVATE_SECRET" not in json.dumps(scene_context(fallen))
    assert public_payload({"gold_spent": 10, "supplies_spent": 1, "private": "secret"}) == {
        "gold_spent": 10,
        "supplies_spent": 1,
    }


@pytest.mark.parametrize("label", list(defeat.COMMANDS))
def test_api_defeat_recovery_save_restore_and_replay(monkeypatch, label):
    monkeypatch.setattr(Dice, "roll", lambda _, sides: sides)
    campaign = request("POST", "/api/campaign", json={}).json()
    assert turn(campaign, "하를란과 대화").status_code == 200
    assert turn(campaign, "전투 시작").status_code == 200
    for _ in range(10):
        if campaign["state"]["player"]["hp"] == 0:
            break
        assert turn(campaign, "턴 종료").status_code == 200
    assert campaign["state"]["player"]["hp"] == 0
    assert campaign["state"]["defeat"] == {"status": "pending"}
    saved = request("POST", f"/api/campaign/{campaign['id']}/save").json()
    restored = request(
        "POST", f"/api/campaign/{campaign['id']}/load", json={"snapshot_id": saved["snapshot_id"]}
    ).json()
    assert restored["state"]["defeat"] == campaign["state"]["defeat"]
    assert restored["actions"] == campaign["actions"]
    before = deepcopy(campaign)
    assert turn(campaign, "시장으로 이동").status_code == 422
    assert campaign == before
    recovery_request = {
        "campaign_id": campaign["id"],
        "expected_state_version": campaign["state_version"],
        "input": label,
        "request_id": "00000000-0000-4000-8000-000000000088",
    }
    recovered_turn = request("POST", "/api/game/turn", json=recovery_request)
    assert recovered_turn.status_code == 200
    campaign.update(recovered_turn.json())
    replay = request("POST", "/api/game/turn", json=recovery_request)
    assert replay.status_code == 200
    assert replay.json() == recovered_turn.json()
    assert turn(restored, label).status_code == 200
    assert restored["state"] == campaign["state"]
    assert campaign["event"]["type"] == "DEFEAT_RECOVERED"
    assert campaign["state"]["player"]["hp"] == 18
    assert turn(campaign, label).status_code == 422
    saved = request("POST", f"/api/campaign/{campaign['id']}/save").json()
    recovered = request(
        "POST", f"/api/campaign/{campaign['id']}/load", json={"snapshot_id": saved["snapshot_id"]}
    ).json()
    assert recovered["state"] == campaign["state"]
    assert turn(recovered, "시장으로 이동").status_code == 200
