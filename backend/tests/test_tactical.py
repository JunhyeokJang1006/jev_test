from copy import deepcopy

import pytest

from app.tactical import available_actions, normalized_combat, resolve


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
        "encounter_enemy_id": "goblin_001",
        "hidden": True,
        "player": {"hp": 31, "ac": 17},
    }


def act(state, intent, target, *rolls):
    return resolve(state, intent, (target,), roller=Rolls(*rolls))


def active(state, *, adjacent=False):
    state["combat"] = {
        "active": True,
        "enemy_hp": 7,
        "enemy_ac": 12,
        "player_x": 1,
        "player_y": 2,
        "enemy_x": 2 if adjacent else 4,
        "enemy_y": 2,
    }
    return state


@pytest.mark.parametrize("intent", ["start_combat", "basic_attack"])
def test_start_rolls_initiative_only_and_tie_goes_to_player(state, intent):
    before = deepcopy(state)
    result = act(state, intent, "goblin_001", 10, 10)
    combat = result["state"]["combat"]
    assert result["event_type"] == "COMBAT_STARTED"
    assert combat["initiative"]["first"] == "player"
    assert combat["enemy_hp"] == 7
    assert combat["enemy_x"] == 4
    assert combat["elapsed_seconds"] == 0
    assert state == before


def test_enemy_first_approaches_without_out_of_range_attack(state):
    result = act(state, "start_combat", "goblin_001", 1, 20)
    assert result["state"]["combat"]["enemy_x"] == 3
    assert result["state"]["combat"]["elapsed_seconds"] == 6
    assert result["event_payload"]["enemy_attack"]["attacked"] is False


def test_out_of_range_attack_rejected_without_rng_or_mutation(state):
    active(state)
    before = deepcopy(state)
    with pytest.raises(ValueError):
        act(state, "basic_attack", "goblin_001")
    assert state == before
    assert "고블린을 공격한다" not in available_actions(state)


@pytest.mark.parametrize(
    "position,direction", [((1, 1), "right"), ((0, 0), "up"), ((3, 2), "right")]
)
def test_movement_rejects_walls_edges_and_enemy(state, position, direction):
    active(state)
    state["combat"].update(player_x=position[0], player_y=position[1])
    before = deepcopy(state)
    with pytest.raises(ValueError):
        act(state, "combat_move", direction)
    assert state == before


def test_move_triggers_enemy_step_and_melee_attack(state):
    active(state)
    result = act(state, "combat_move", "right", 13, 2)
    assert result["state"]["combat"]["player_x"] == 2
    assert result["state"]["combat"]["enemy_x"] == 3
    assert result["state"]["player"]["hp"] == 27
    assert result["state"]["combat"]["round"] == 1
    assert result["state"]["combat"]["elapsed_seconds"] == 6


def test_defend_bonus_expires_after_response(state):
    active(state, adjacent=True)
    first = act(state, "combat_defend", "player", 13)
    assert first["event_payload"]["enemy_attack"]["ac"] == 19
    assert first["state"]["player"]["hp"] == 31
    second = act(first["state"], "basic_attack", "goblin_001", 1, 13, 2)
    assert second["event_payload"]["enemy_attack"]["ac"] == 17
    assert second["state"]["player"]["hp"] == 27


def test_flee_requires_exit_and_disables_reencounter(state):
    active(state)
    with pytest.raises(ValueError):
        act(state, "combat_flee", "exit")
    state["combat"]["player_x"] = 0
    result = act(state, "combat_flee", "exit")
    assert result["state"]["combat"]["result"] == "fled"
    assert result["state"]["encounter_enemy_id"] is None
    assert result["event_payload"]["enemy_attack"] is None
    assert available_actions(result["state"]) == []
    with pytest.raises(ValueError):
        act(result["state"], "start_combat", "goblin_001")


def test_critical_victory_has_no_retaliation_and_preserves_input(state):
    active(state, adjacent=True)
    state["combat"]["enemy_ac"] = 99
    before = deepcopy(state)
    result = act(state, "basic_attack", "goblin_001", 20, 4, 4)
    assert result["event_payload"]["damage_rolls"] == [4, 4]
    assert result["state"]["combat"]["result"] == "victory"
    assert result["state"]["combat"]["active"] is False
    assert result["event_payload"]["enemy_attack"] is None
    assert state == before


def test_enemy_critical_defeat_blocks_future_actions(state):
    active(state, adjacent=True)
    state["player"]["hp"] = 1
    result = act(state, "combat_defend", "player", 20, 6, 6)
    assert result["event_payload"]["enemy_attack"]["damage_rolls"] == [6, 6]
    assert result["state"]["player"]["hp"] == 0
    assert result["state"]["combat"]["result"] == "defeat"
    assert available_actions(result["state"]) == []
    with pytest.raises(ValueError):
        act(result["state"], "combat_defend", "player")


@pytest.mark.parametrize("damage_bonus,damage", [(7, 8), (-10, 0)])
def test_player_bonuses_are_preserved_and_negative_damage_is_clamped(state, damage_bonus, damage):
    active(state, adjacent=True)
    state["player"].update(attack_bonus=10, damage_bonus=damage_bonus)
    rolls = (2, 1) if damage >= 7 else (2, 1, 1)
    result = act(state, "basic_attack", "goblin_001", *rolls)
    assert result["event_payload"]["hit"]
    assert result["event_payload"]["bonus"] == 10
    assert result["event_payload"]["damage_bonus"] == damage_bonus
    assert result["event_payload"]["damage"] == damage
    assert result["dice"]["total"] == 12


def test_legacy_combat_keeps_hp_and_does_not_reroll_initiative(state):
    state["combat"] = {"active": True, "enemy_hp": 3, "enemy_ac": 12}
    result = act(state, "combat_defend", "player")
    assert result["state"]["combat"]["enemy_hp"] == 3
    assert result["state"]["combat"]["enemy_x"] == 3
    assert "initiative" not in result["state"]["combat"]


def test_legacy_projection_is_a_copy_and_does_not_create_inactive_combat(state):
    assert normalized_combat(state) == {}
    state["combat"] = {"active": True, "enemy_hp": 3}
    projected = normalized_combat(state)
    assert projected["player_x"] == 1
    assert projected["enemy_hp"] == 3
    projected["enemy_hp"] = 1
    assert state["combat"] == {"active": True, "enemy_hp": 3}


@pytest.mark.parametrize("targets", [(), ("wrong",), ("goblin_001", "goblin_001")])
def test_invalid_targets_are_rejected_before_rng(state, targets):
    with pytest.raises(ValueError):
        resolve(state, "start_combat", targets, roller=Rolls())


def test_enemy_bfs_routes_around_wall(state):
    active(state)
    state["combat"].update(player_x=1, player_y=1, enemy_x=3, enemy_y=1)
    result = act(state, "combat_defend", "player")
    combat = result["state"]["combat"]
    assert (combat["enemy_x"], combat["enemy_y"]) == (3, 0)


@pytest.mark.parametrize(
    "patch",
    [
        {"location_id": "elsewhere"},
        {"encounter_enemy_id": None},
        {"quest": {"ending": "peace"}},
        {"followup": {"status": "active"}},
        {"scene_status": "ended"},
    ],
)
def test_unavailable_scene_rejected_without_rng(state, patch):
    state.update(patch)
    assert available_actions(state) == []
    with pytest.raises(ValueError):
        act(state, "start_combat", "goblin_001")
