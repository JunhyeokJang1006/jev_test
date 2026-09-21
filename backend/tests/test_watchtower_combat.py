import json
from copy import deepcopy

import pytest

from app import ai, defeat, expedition, progression, tactical
from app.context import scene_context
from app.dice import Dice
from app.game import interpret_mock, resolve_action
from app.projection import public_state
from app.world import available_actions

from .helpers import request
from .test_expedition_contract import at_tower
from .test_world import turn


class Rolls:
    def __init__(self, *values):
        self.values = iter(values)

    def roll(self, sides):
        value = next(self.values)
        assert 1 <= value <= sides
        return value


def ready():
    return {
        "location_id": "watchtower",
        "quest": {"ending": "law"},
        "followup": {"status": "completed"},
        "player": {"hp": 37, "max_hp": 37, "ac": 17},
        "resources": {"gold": 20, "camp_supplies": 1},
        "expedition": {
            "status": "active",
            "branch": "law",
            "passage": "repair",
            "approach": None,
            "clues": ["messenger_location", "document_location"],
            "attempts": {},
            "deadline_at": 90,
        },
    }


def act(state, label, *rolls):
    return resolve_action(state, interpret_mock(label), roller=Rolls(*rolls)).state


@pytest.mark.parametrize("previous", [None, "victory", "fled", "defeat"])
def test_new_encounter_after_legacy_terminal_combat_and_time_reset(previous):
    state = ready()
    if previous:
        state["combat"] = {"active": False, "result": previous, "elapsed_seconds": 120}
        state["defeat"] = {"status": "recovered"}
    state["combat_seconds"] = 54
    state = act(state, "망루 매복자와 전투", 1, 20)
    assert state["combat"]["encounter_id"] == "watchtower_ambush"
    assert state["combat"]["title"] == "망루 매복 전투"
    assert state["combat_seconds"] == 60
    assert state["elapsed_minutes"] == 1
    assert [e["id"] for e in state["combat"]["enemies"]] == ["bandit_001", "bandit_002"]
    if previous:
        assert state["encounter_history"]["greyhaven_goblins"] == previous
    assert set(available_actions(state)) == set(tactical.available_actions(state))
    for label in [
        "망루 계단 보강 (10분)",
        "동쪽 성문으로 이동",
        "망루 매복자와 전투",
        "고블린을 공격한다",
    ]:
        before = deepcopy(state)
        with pytest.raises(ValueError):
            act(state, label)
        assert state == before


def test_victory_opens_original_decision_and_awards_once():
    state = act(ready(), "망루 매복자와 전투", 20, 1)
    state["combat"]["player_x"] = 3
    state = act(state, "매복자를 공격한다", 19, 8)
    state["combat"].update(action_available=True, player_x=3, player_y=4)
    before = deepcopy(state)
    state = act(state, "두 번째 매복자를 공격한다", 19, 8)
    assert state["combat"]["result"] == "victory"
    assert state["expedition"]["approach"] == "combat"
    assert state["expedition"]["status"] == "active"
    assert state["progression"]["xp"] == 25
    assert state["progression"]["earned"] == ["watchtower_victory"]
    assert progression.reward(before, state) == 0
    assert "전령 구조 우선 확정 (문서 포기, 5분)" in available_actions(state)
    assert "망루 매복자와 전투" not in available_actions(state)
    assert state["encounter_history"] == {"watchtower_ambush": "victory"}


@pytest.mark.parametrize("method", ["medic", "supplies", "wait"])
def test_second_defeat_recovers_at_tower_and_keeps_noncombat_routes(method):
    state = ready()
    state["defeat"] = {"status": "recovered", "method": "wait"}
    state = act(state, "망루 매복자와 전투", 20, 1)
    state["player"]["hp"] = 1
    state["combat"]["player_x"] = 3
    state = act(state, "턴 종료", 20, 6, 6)
    assert state["defeat"] == {"status": "pending"}
    original_quest = deepcopy(state["expedition"])
    label = next(label for label, (_, target) in defeat.COMMANDS.items() if target == method)
    state = act(state, label)
    assert state["player"]["hp"] == 18
    assert state["location_id"] == "watchtower"
    assert state["expedition"] == original_quest
    assert "망루 계단 보강 (10분)" in available_actions(state)
    assert "망루 매복자와 전투" not in available_actions(state)
    assert state["encounter_history"]["watchtower_ambush"] == "defeat"


def test_flee_prevents_reentry_after_travel_and_context_keeps_history():
    state = act(ready(), "망루 매복자와 전투", 20, 1)
    state = act(state, "전투 이동: 왼쪽")
    state = act(state, "전투에서 후퇴")
    assert state["expedition"]["approach"] is None
    state = act(state, "동쪽 성문으로 이동")
    state = act(state, "망루로 이동")
    assert "망루 매복자와 전투" not in available_actions(state)
    assert all(c["intent"] != "start_combat" for c in scene_context(state)["available_commands"])
    state["encounter_history"]["secret"] = "PRIVATE"
    assert public_state(state)["encounter_history"] == {"watchtower_ambush": "fled"}


@pytest.mark.parametrize(
    "change",
    [
        {"status": "resolved"},
        {"passage": None},
        {"approach": "stairs"},
    ],
)
def test_start_rejects_unavailable_expedition(change):
    state = ready()
    state["expedition"].update(change)
    with pytest.raises(ValueError):
        act(state, "망루 매복자와 전투")


def test_active_bandit_commands_keep_enemy_identity():
    state = act(ready(), "망루 매복자와 전투", 20, 1)
    state["combat"]["player_x"] = 3
    commands = scene_context(state)["available_commands"]
    assert any(c["intent"] == "basic_attack" and c["target_id"] == "bandit_001" for c in commands)
    assert not any(c["target_id"].startswith("goblin") for c in commands)
    assert expedition.available_actions(state) == []


@pytest.mark.parametrize("target", ["bandit_001", "bandit_002", "goblin_001"])
def test_stub_provider_cannot_retarget_or_attack_out_of_range(monkeypatch, target):
    state = act(ready(), "망루 매복자와 전투", 20, 1)
    state["combat"]["player_x"] = 3
    monkeypatch.setattr(ai, "_provider_config", lambda: [("stub", "", "", "")])

    def chat(provider, messages, **kwargs):
        commands = json.loads(messages[-1]["content"])["scene"]["available_commands"]
        assert any(c["target_id"] == "bandit_001" for c in commands)
        assert not any(c["target_id"].startswith("goblin") for c in commands)
        return "stub", json.dumps(
            {
                "intent": "basic_attack",
                "action_type": "attack",
                "target_ids": [target],
            }
        )

    monkeypatch.setattr(ai, "_chat", chat)
    proposal, provider = ai.interpret_action("눈앞 매복자에게 검을 휘두를게", state)
    assert provider == ("stub" if target == "bandit_001" else "mock")
    assert proposal.intent == ("basic_attack" if target == "bandit_001" else "describe_action")


def test_tower_requires_start_label_before_attack_but_active_attack_is_allowed():
    state = ready()
    with pytest.raises(ValueError):
        act(state, "매복자를 공격한다")
    state = act(state, "망루 매복자와 전투", 20, 1)
    state["combat"]["player_x"] = 3
    assert act(state, "매복자를 공격한다", 19, 8)["combat"]["enemies"][0]["hp"] == 0


@pytest.mark.parametrize("result", ["victory", "fled"])
def test_api_combat_save_restore_replay_and_terminal_history(monkeypatch, result):
    monkeypatch.setattr(Dice, "roll", lambda _, sides: sides)
    campaign = at_tower(approach=False)
    assert turn(campaign, "망루 매복자와 전투").status_code == 200
    saved = request("POST", f"/api/campaign/{campaign['id']}/save").json()
    restored = request(
        "POST",
        f"/api/campaign/{campaign['id']}/load",
        json={"snapshot_id": saved["snapshot_id"]},
    ).json()
    assert restored["state"]["combat"] == campaign["state"]["combat"]
    campaign = restored
    labels = (
        [
            "전투 이동: 오른쪽",
            "전투 이동: 오른쪽",
            "매복자를 공격한다",
            "턴 종료",
            "전투 이동: 아래",
            "두 번째 매복자를 공격한다",
        ]
        if result == "victory"
        else ["전투 이동: 왼쪽", "전투에서 후퇴"]
    )
    for label in labels[:-1]:
        assert turn(campaign, label).status_code == 200
    envelope = {
        "campaign_id": campaign["id"],
        "expected_state_version": campaign["state_version"],
        "input": labels[-1],
        "request_id": "00000000-0000-4000-8000-000000000083",
    }
    response = request("POST", "/api/game/turn", json=envelope)
    assert response.status_code == 200, response.text
    assert request("POST", "/api/game/turn", json=envelope).json() == response.json()
    campaign.update(response.json())
    assert campaign["state"]["combat"]["result"] == result
    assert campaign["state"]["expedition"]["status"] == "active"
    for label in ["동쪽 성문으로 이동", "망루로 이동"]:
        assert turn(campaign, label).status_code == 200
    saved = request("POST", f"/api/campaign/{campaign['id']}/save").json()
    restored = request(
        "POST",
        f"/api/campaign/{campaign['id']}/load",
        json={"snapshot_id": saved["snapshot_id"]},
    ).json()
    assert restored["state"]["encounter_history"]["watchtower_ambush"] == result
    assert "망루 매복자와 전투" not in restored["actions"]
    assert all(
        c["intent"] != "start_combat"
        for c in scene_context(restored["state"])["available_commands"]
    )
    assert turn(restored, "망루 매복자와 전투").status_code == 422
    if result == "victory":
        assert restored["state"]["progression"]["xp"] == 150
        assert turn(restored, "전령 구조 우선 확정 (문서 포기, 5분)").status_code == 200
        for label in ["동쪽 성문으로 이동", "시장으로 이동"]:
            assert turn(restored, label).status_code == 200
        gold = restored["state"]["resources"]["gold"]
        report = {
            "campaign_id": restored["id"],
            "expected_state_version": restored["state_version"],
            "input": "오렌에게 망루 결과 보고 (25골드)",
            "request_id": "00000000-0000-4000-8000-000000000084",
        }
        response = request("POST", "/api/game/turn", json=report)
        assert response.status_code == 200, response.text
        assert response.json()["state"]["progression"]["xp"] == 275
        assert response.json()["state"]["resources"]["gold"] == gold + 25
        assert response.json()["state"]["expedition"]["status"] == "completed"
        assert request("POST", "/api/game/turn", json=report).json() == response.json()
        fetched = request("GET", f"/api/campaign/{restored['id']}").json()
        assert fetched["state"] == response.json()["state"]


def test_api_watchtower_defeat_recovery_save_restore_and_replay(monkeypatch):
    monkeypatch.setattr(Dice, "roll", lambda _, sides: sides)
    campaign = at_tower(approach=False)
    quest = deepcopy(campaign["state"]["expedition"])
    assert turn(campaign, "망루 매복자와 전투").status_code == 200
    for _ in range(20):
        if campaign["state"]["player"]["hp"] == 0:
            break
        assert turn(campaign, "턴 종료").status_code == 200
    assert campaign["state"]["player"]["hp"] == 0
    assert campaign["state"]["combat"]["result"] == "defeat"
    saved = request("POST", f"/api/campaign/{campaign['id']}/save").json()
    restored = request(
        "POST",
        f"/api/campaign/{campaign['id']}/load",
        json={"snapshot_id": saved["snapshot_id"]},
    ).json()
    assert restored["state"] == campaign["state"]
    envelope = {
        "campaign_id": restored["id"],
        "expected_state_version": restored["state_version"],
        "input": "도움을 기다리기 (8시간)",
        "request_id": "00000000-0000-4000-8000-000000000085",
    }
    response = request("POST", "/api/game/turn", json=envelope)
    assert response.status_code == 200, response.text
    assert request("POST", "/api/game/turn", json=envelope).json() == response.json()
    state = response.json()["state"]
    assert state["location_id"] == "watchtower"
    assert state["player"]["hp"] == state["player"]["max_hp"] // 2
    assert state["expedition"] == quest
    assert state["defeat"]["status"] == "recovered"
    assert state["encounter_history"]["watchtower_ambush"] == "defeat"
    saved = request("POST", f"/api/campaign/{restored['id']}/save").json()
    recovered = request(
        "POST",
        f"/api/campaign/{restored['id']}/load",
        json={"snapshot_id": saved["snapshot_id"]},
    ).json()
    assert recovered["state"] == state
    assert "망루 매복자와 전투" not in recovered["actions"]
    assert "망루 계단 보강 (10분)" in recovered["actions"]
    assert turn(recovered, "망루 계단 보강 (10분)").status_code == 200
