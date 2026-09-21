from copy import deepcopy

import pytest

from app.game import ActionProposal, resolve_action


class Rolls:
    def __init__(self, *values):
        self.values = iter(values)
        self.used = []

    def roll(self, sides):
        value = next(self.values)
        assert 1 <= value <= sides
        self.used.append((sides, value))
        return value


@pytest.fixture
def state():
    return {
        "location_id": "greyhaven_inn",
        "nearby_object_ids": ["door_inn"],
        "encounter_enemy_id": "goblin_001",
        "hidden": True,
        "combat": {
            "active": True,
            "enemy_hp": 7,
            "enemy_ac": 12,
            "player_x": 1,
            "player_y": 2,
            "enemy_x": 2,
            "enemy_y": 2,
        },
        "player": {"hp": 31, "ac": 17, "stealth_bonus": 5, "attack_bonus": 5},
    }


ATTACK = ActionProposal("basic_attack", "attack", ("goblin_001",), None, None)
END_TURN = ActionProposal("combat_end_turn", "exploration", ("player",), None, None)
HIDE = ActionProposal("hide_beside_door", "exploration", ("door_inn",), "stealth", "moderate")


def test_miss_and_enemy_critical_are_recorded_without_mutating_input(state):
    before = deepcopy(state)
    attacked = resolve_action(state, ATTACK, roller=Rolls(1))
    assert attacked.state["player"]["hp"] == 31
    assert attacked.event_payload["enemy_attacks"] == []
    result = resolve_action(attacked.state, END_TURN, roller=Rolls(20, 6, 6))
    assert result.state["player"]["hp"] == 17
    assert result.state["combat"]["enemy_hp"] == 7
    assert result.event_payload["enemy_attack"]["damage_rolls"] == [6, 6]
    assert result.event_payload["enemy_attack"]["critical"]
    assert not result.state["hidden"]
    assert state == before


def test_player_critical_ignores_ac_and_victory_stops_retaliation(state):
    state["combat"]["enemy_ac"] = 99
    rolls = Rolls(20, 4, 4)
    result = resolve_action(state, ATTACK, roller=rolls)
    assert result.state["combat"]["result"] == "victory"
    assert result.state["combat"]["enemy_hp"] == 0
    assert result.event_payload["damage_rolls"] == [4, 4]
    assert result.event_payload["enemy_attack"] is None
    assert rolls.used == [(20, 20), (8, 4), (8, 4)]


def test_defeat_prevents_subsequent_actions(state):
    state["player"]["hp"] = 1
    attacked = resolve_action(state, ATTACK, roller=Rolls(1))
    result = resolve_action(attacked.state, END_TURN, roller=Rolls(19, 1))
    assert result.state["player"]["hp"] == 0
    assert result.state["combat"]["result"] == "defeat"
    assert not result.state["combat"]["active"]
    for action in (ATTACK, HIDE):
        with pytest.raises(ValueError, match="전투 불능"):
            resolve_action(result.state, action, roller=Rolls())


@pytest.mark.parametrize("roll,bonus,success", [(1, 20, True), (20, -10, False), (3, 5, False)])
def test_skill_uses_total_not_attack_critical_rules(state, roll, bonus, success):
    state.pop("combat")
    state["player"]["stealth_bonus"] = bonus
    result = resolve_action(state, HIDE, roller=Rolls(roll))
    assert result.state["hidden"] is success
    assert result.event_payload["bonus"] == bonus
    assert result.event_payload["roll"] == roll


@pytest.mark.parametrize("intent,target", [("basic_attack", "npc_mira"), ("hide_beside_door", "x")])
def test_invalid_targets_consume_no_dice(state, intent, target):
    proposal = ActionProposal(intent, "exploration", (target,), None, None)
    with pytest.raises(ValueError, match="대상"):
        resolve_action(state, proposal, roller=Rolls())


def test_won_encounter_cannot_be_attacked_again(state):
    result = resolve_action(state, ATTACK, roller=Rolls(20, 4, 4))
    with pytest.raises(ValueError):
        resolve_action(result.state, ATTACK, roller=Rolls())


def test_attack_natural_one_misses_even_with_large_bonus(state):
    state["player"]["attack_bonus"] = 100
    result = resolve_action(state, ATTACK, roller=Rolls(1, 1))
    assert not result.event_payload["hit"]
    assert result.event_payload["damage"] == 0
    assert result.state["player"]["hp"] == 31
