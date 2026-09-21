"""단궁의 경제·격자·자원·공개 경계 및 저장 계약."""

import json
from copy import deepcopy

import pytest

from app import ai, equipment, resources, tactical
from app.context import scene_context
from app.game import interpret_mock, resolve_action
from app.projection import public_payload, public_state
from app.ranged import clear_line, ranged_stats
from app.storage import connect

from .helpers import request
from .test_equipment_contract import wear
from .test_tactical import Rolls, active

SHOT = "고블린에게 사격"


def ready():
    state = active(
        {
            "location_id": "greyhaven_inn",
            "encounter_enemy_id": "goblin_001",
            "player": {"hp": 31, "max_hp": 37},
            "resources": {"gold": 20, "arrows": 10},
        }
    )
    wear(state, "shortbow")
    return state


def act(state, label, *values):
    return resolve_action(state, interpret_mock(label), roller=Rolls(*values))


@pytest.mark.parametrize(
    "start,end,clear",
    [
        ((1, 2), (4, 2), True),
        ((1, 1), (4, 1), False),
        ((1, 2), (3, 0), False),  # exact corner touching (1.5, 1.5)
        ((0, 0), (5, 0), True),
        ((2, 0), (2, 4), False),
        ((0, 1), (1, 0), True),
        ((2, 1), (2, 1), False),
    ],
)
def test_line_is_exact_symmetric_and_corner_blocking(start, end, clear):
    assert clear_line(start, end, tactical.WALLS) is clear
    assert clear_line(end, start, tactical.WALLS) is clear


@pytest.mark.parametrize("distance,allowed", [(1, False), (2, True), (5, True), (6, False)])
def test_range_boundaries(distance, allowed):
    state = ready()
    state["combat"].update(player_x=0, player_y=0, enemy_x=min(distance, 5), enemy_y=distance // 6)
    assert (SHOT in tactical.available_actions(state)) is allowed


@pytest.mark.parametrize(
    "change",
    [
        {"equipment": {}},
        {"equipment": {"owned": [], "equipped": {"ranged": "shortbow"}}},
        {"equipment": {"owned": ["shortbow"], "equipped": {}}},
        {"resources": {"arrows": 0}},
        {"resources": {}},
        {"resources": {"arrows": True}},
        {"resources": {"arrows": -1}},
        {"resources": {"arrows": 31}},
        {"resources": {"arrows": "10"}},
        {"resources": {"arrows": None}},
        {"player": {"hp": 0}},
    ],
)
def test_invalid_shot_has_no_mutation_or_rng(change):
    state = ready() | change
    before, roller = deepcopy(state), Rolls()
    with pytest.raises(ValueError):
        resolve_action(state, interpret_mock(SHOT), roller=roller)
    assert before == state and roller.used == []
    assert SHOT not in tactical.available_actions(state)


def test_main_budget_wall_override_and_dead_target_reject_before_rng():
    for changes in (
        {"action_available": False},
        {"enemy_hp": 0},
        {"player_y": 1, "enemy_y": 1, "walls": []},
    ):
        state = ready()
        state["combat"].update(changes)
        before, roller = deepcopy(state), Rolls()
        with pytest.raises(ValueError):
            resolve_action(state, interpret_mock(SHOT), roller=roller)
        assert state == before and roller.used == []


@pytest.mark.parametrize("hp,allowed", [(7, False), (0, True)])
def test_adjacent_live_enemy_threatens_shot_but_dead_enemy_does_not(hp, allowed):
    state = ready()
    state["combat"] = tactical.normalized_combat(state)
    state["combat"]["enemies"].append(
        {
            "id": "goblin_002",
            "name": "Scout",
            "hp": hp,
            "ac": 12,
            "x": 1,
            "y": 1,
            "conditions": [],
        }
    )
    assert (SHOT in tactical.available_actions(state)) is allowed


@pytest.mark.parametrize(
    "values,damage,critical", [((1,), 0, False), ((12, 2), 5, False), ((20, 2, 3), 8, True)]
)
def test_shot_roll_costs_damage_and_no_automatic_enemy_phase(values, damage, critical):
    state = ready()
    state["combat"]["enemy_hp"] = 30
    wear(state, "heavy_blade")
    before, roller = deepcopy(state), Rolls(*values)
    result = resolve_action(state, interpret_mock(SHOT), roller=roller)
    assert state == before
    assert result.state["resources"]["arrows"] == 9
    assert not result.state["combat"]["action_available"]
    assert result.state["combat"]["bonus_action_available"]
    assert result.state["combat"]["movement_remaining"] == 3
    assert result.state["combat"]["elapsed_seconds"] == 0
    assert result.event_payload["enemy_attacks"] == []
    assert result.event_payload["damage"] == damage
    assert result.event_payload["critical"] is critical
    assert result.event_payload["bonus"] == 5
    assert result.event_payload["damage_die"] == 6
    assert roller.used == [(20, values[0]), *[(6, value) for value in values[1:]]]
    with pytest.raises(ValueError):
        act(result.state, SHOT)


@pytest.mark.parametrize("values,hit", [((1, 1), False), ((1, 12, 1), True)])
def test_exposed_consumed_on_hit_and_miss(values, hit):
    state = ready()
    state["combat"] = tactical.normalized_combat(state)
    state["combat"]["enemies"][0]["conditions"] = ["exposed"]
    result = act(state, SHOT, *values)
    assert result.event_payload["attack_rolls"] == list(values[:2])
    assert result.event_payload["hit"] is hit
    assert result.event_payload["condition_consumed"] == "exposed"
    assert result.state["combat"]["enemies"][0]["conditions"] == []


def test_victory_records_history_and_watchtower_progression():
    state = ready()
    state.update(location_id="watchtower", expedition={"status": "active", "passage": "paid"})
    state["combat"] = tactical.normalized_combat(state)
    state["combat"]["encounter_id"] = "watchtower_ambush"
    state["combat"]["enemies"][0]["id"] = "bandit_001"
    result = act(state, "매복자에게 사격", 20, 6, 6)
    assert result.state["combat"]["result"] == "victory"
    assert result.state["combat"]["elapsed_seconds"] == 6
    assert result.state["encounter_history"]["watchtower_ambush"] == "victory"
    assert result.state["expedition"]["approach"] == "combat"
    assert result.state["expedition"]["stage"] == "decision"


def test_purchase_equip_and_ammunition_are_independent():
    state = ready()
    state.pop("combat")
    state.pop("equipment")
    state.update(location_id="market", resources={"gold": 20}, inventory=["royal_seal"])
    bought = act(state, "단궁 구매 (10골드)")
    assert ranged_stats(bought.state)["equipped"] is False
    assert bought.state["resources"]["arrows"] == 0
    equipped = act(bought.state, "장비 장착: 단궁")
    assert ranged_stats(equipped.state)["equipped"] is True
    assert equipped.state["resources"]["arrows"] == 0
    supplied = act(equipped.state, "화살 10개 구매 (2골드)")
    assert supplied.state["resources"] == {"gold": 8, "arrows": 10}
    assert supplied.state["inventory"] == ["royal_seal"]
    assert supplied.state["elapsed_minutes"] == 3
    assert equipment.effective_stats(supplied.state) == equipment.effective_stats(state)


@pytest.mark.parametrize("count", [-1, 21, 30, 31, True, "10", None])
def test_ammunition_purchase_cap_and_malformed_values(count):
    state = ready()
    state.pop("combat")
    state["location_id"] = "market"
    state["resources"]["arrows"] = count
    before = deepcopy(state)
    assert "화살 10개 구매 (2골드)" not in resources.available_actions(state)
    with pytest.raises(ValueError):
        act(state, "화살 10개 구매 (2골드)")
    assert state == before


def test_public_derived_bow_stats_growth_and_private_boundary():
    state = ready()
    wear(state, "heavy_blade")
    state["player"].update(attack_bonus=6, damage_bonus=4)
    state["ranged_stats"] = {"attack_bonus": 999, "secret": "PRIVATE_CANARY"}
    public = public_state(state)
    assert public["ranged_stats"] == {
        "equipped": True,
        "attack_bonus": 6,
        "damage_die": 6,
        "damage_bonus": 4,
        "minimum_range": 2,
        "maximum_range": 5,
        "ammunition": 10,
    }
    assert public_state(public) == public
    assert scene_context(public)["ranged_stats"] == public["ranged_stats"]
    payload = act(state, SHOT, 1).event_payload | {"secret": "PRIVATE_CANARY"}
    assert public_payload(payload)["distance"] == 3
    assert "PRIVATE_CANARY" not in json.dumps(scene_context(public))
    assert "secret" not in public_payload(payload)


def test_api_shot_replay_and_save_load_preserve_finite_arrows():
    campaign = request("POST", "/api/campaign", json={}).json()
    state = campaign["state"] | ready()
    connection = connect()
    connection.execute(
        "UPDATE campaigns SET state_json=? WHERE id=?", (json.dumps(state), campaign["id"])
    )
    connection.close()
    payload = {
        "campaign_id": campaign["id"],
        "input": SHOT,
        "expected_state_version": 0,
        "request_id": "00000000-0000-4000-8000-000000000991",
    }
    first = request("POST", "/api/game/turn", json=payload)
    assert first.status_code == 200, first.text
    assert first.json()["state"]["resources"]["arrows"] == 9
    assert request("POST", "/api/game/turn", json=payload).json() == first.json()
    saved = request("POST", f"/api/campaign/{campaign['id']}/save").json()
    restored = request(
        "POST", f"/api/campaign/{campaign['id']}/load", json={"snapshot_id": saved["snapshot_id"]}
    ).json()
    assert restored["state"]["resources"]["arrows"] == 9
    assert restored["state"]["ranged_stats"]["equipped"] is True


def test_maximum_ammo_purchase_and_rests_do_not_refill():
    state = ready()
    state.pop("combat")
    state.update(location_id="market")
    state["resources"].update(arrows=20, camp_supplies=1, hit_dice=0)
    supplied = act(state, "화살 10개 구매 (2골드)")
    assert supplied.state["resources"]["arrows"] == 30
    assert supplied.event_payload["rule_id"] == "greyhaven-arrows-custom-v1"
    supplied.state["resources"]["arrows"] = 0
    supplied.state["location_id"] = "greyhaven_inn"
    rested = act(supplied.state, "여관에서 긴 휴식")
    assert rested.state["resources"]["arrows"] == 0
    started = act(rested.state, "전투 시작", 20, 1)
    assert started.state["resources"]["arrows"] == 0
    assert SHOT not in tactical.available_actions(started.state)


@pytest.mark.parametrize("watchtower", [False, True])
def test_second_target_and_wrong_encounter_target(watchtower):
    state = ready()
    state["combat"] = tactical.normalized_combat(state)
    prefix, label = ("bandit", "매복자") if watchtower else ("goblin", "고블린")
    if watchtower:
        state.update(location_id="watchtower", expedition={"status": "active", "passage": "paid"})
        state["combat"]["encounter_id"] = "watchtower_ambush"
    state["combat"]["enemies"][0]["id"] = f"{prefix}_002"
    result = act(state, f"두 번째 {label}에게 사격", 12, 1)
    assert result.event_payload["target_id"] == f"{prefix}_002"
    assert result.state["combat"]["enemies"][0]["hp"] == 3
    wrong = "고블린에게 사격" if watchtower else "매복자에게 사격"
    with pytest.raises(ValueError):
        act(state, wrong)


@pytest.mark.parametrize("value", [None, False, "2", -1, 31])
def test_public_malformed_ammunition_is_zero(value):
    state = ready()
    state["resources"]["arrows"] = value
    public = public_state(state)
    assert public["resources"]["arrows"] == 0
    assert public["ranged_stats"]["ammunition"] == 0


@pytest.mark.parametrize(
    "text", ["사격하지 않는다", "화살을 안 쏜다", "쏘지 않는다", "사격하지 않고 방어한다"]
)
def test_model_proposal_cannot_override_shooting_refusal(monkeypatch, text):
    monkeypatch.setattr(ai, "_provider_config", lambda: [("luna", "", "", "")])
    monkeypatch.setattr(
        ai,
        "_chat",
        lambda *a, **k: (
            "luna",
            json.dumps(
                {
                    "intent": "combat_ranged_attack",
                    "target_ids": ["goblin_001"],
                    "action_type": "exploration",
                }
            ),
        ),
    )
    state = ready()
    proposal, provider = ai.interpret_action(text, state)
    assert proposal.intent == "describe_action" and provider == "mock"
    before, roller = deepcopy(state), Rolls()
    with pytest.raises(ValueError):
        resolve_action(state, proposal, roller=roller)
    assert state == before and roller.used == []


def test_interpreter_receives_ranged_contract_without_external_call(monkeypatch):
    monkeypatch.setattr(ai, "_provider_config", lambda: [("luna", "", "", "")])

    def chat(provider, messages, **kwargs):
        scene = json.loads(messages[1]["content"])["scene"]
        assert scene["ranged_stats"]["damage_die"] == 6
        assert scene["ranged_stats"]["ammunition"] == 10
        assert any(c["intent"] == "combat_ranged_attack" for c in scene["available_commands"])
        return "luna", json.dumps(
            {
                "intent": "combat_ranged_attack",
                "target_ids": ["goblin_001"],
                "action_type": "attack",
            }
        )

    monkeypatch.setattr(ai, "_chat", chat)
    proposal, provider = ai.interpret_action("저 고블린에게 단궁으로 쏠게", ready())
    assert provider == "luna" and proposal.intent == "combat_ranged_attack"
