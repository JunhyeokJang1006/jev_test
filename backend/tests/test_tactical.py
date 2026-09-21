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
    """저장된 기존 단일 적 전투 fixture."""
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


def test_end_turn_after_move_triggers_enemy_step_and_melee_attack(state):
    active(state)
    moved = act(state, "combat_move", "right")
    assert moved["state"]["combat"]["enemy_x"] == 4
    assert moved["event_payload"]["enemy_attacks"] == []
    result = act(moved["state"], "combat_end_turn", "player", 13, 2)
    assert result["state"]["combat"]["player_x"] == 2
    assert result["state"]["combat"]["enemy_x"] == 3
    assert result["state"]["player"]["hp"] == 27
    assert result["state"]["combat"]["round"] == 2
    assert result["state"]["combat"]["elapsed_seconds"] == 6


def test_defend_bonus_expires_after_response(state):
    active(state, adjacent=True)
    defended = act(state, "combat_defend", "player")
    first = act(defended["state"], "combat_end_turn", "player", 13)
    assert first["event_payload"]["enemy_attack"]["ac"] == 19
    assert first["state"]["player"]["hp"] == 31
    attacked = act(first["state"], "basic_attack", "goblin_001", 1)
    second = act(attacked["state"], "combat_end_turn", "player", 13, 2)
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
    defended = act(state, "combat_defend", "player")
    result = act(defended["state"], "combat_end_turn", "player", 20, 6, 6)
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
    rolls = (2, 1)
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
    assert result["state"]["combat"]["enemy_x"] == 4
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
    result = act(state, "combat_end_turn", "player")
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


def multi_active(state, *, adjacent=False):
    result = act(state, "start_combat", "goblin_001", 10, 10)["state"]
    if adjacent:
        result["combat"]["enemies"][0].update(x=2, y=2)
        result["combat"]["enemies"][1].update(x=1, y=3)
    return result


def test_new_encounter_has_two_enemies_and_versioned_events(state):
    result = act(state, "start_combat", "goblin_001", 10, 10)
    assert result["state"]["combat"]["enemies"] == [
        {"id": "goblin_001", "name": "Goblin", "hp": 7, "ac": 12, "x": 4, "y": 2, "conditions": []},
        {
            "id": "goblin_002",
            "name": "Goblin Scout",
            "hp": 7,
            "ac": 12,
            "x": 4,
            "y": 4,
            "conditions": [],
        },
    ]
    assert result["event_payload"]["rule_id"] == "greyhaven-tactical-v4"
    assert result["event_payload"]["enemy_attacks"] == []


def test_enemy_side_initiative_moves_both_and_counts_six_seconds(state):
    roller = Rolls(1, 20)
    result = resolve(state, "start_combat", ("goblin_001",), roller=roller)
    assert roller.used == [(20, 1), (20, 20)]
    attacks = result["event_payload"]["enemy_attacks"]
    assert [attack["enemy_id"] for attack in attacks] == ["goblin_001", "goblin_002"]
    assert all(attack["moved"] and not attack["attacked"] for attack in attacks)
    assert result["event_payload"]["enemy_attack"] == attacks[0]
    assert result["state"]["combat"]["elapsed_seconds"] == 6


def test_second_target_uses_its_own_hp_and_ac_and_preserves_source(state):
    state = multi_active(state, adjacent=True)
    state["combat"]["enemies"][1]["ac"] = 99
    before = deepcopy(state)
    assert "두 번째 고블린을 공격한다" in available_actions(state)
    result = act(state, "basic_attack", "goblin_002", 20, 2, 2)
    combat = result["state"]["combat"]
    assert [enemy["hp"] for enemy in combat["enemies"]] == [7, 0]
    assert combat["enemy_hp"] == 7
    assert combat["active"] and combat["result"] == "ongoing"
    assert result["event_payload"]["ac"] == 99
    assert result["event_payload"]["enemy_attacks"] == []
    ended = act(result["state"], "combat_end_turn", "player", 1)
    assert [attack["enemy_id"] for attack in ended["event_payload"]["enemy_attacks"]] == [
        "goblin_001"
    ]
    assert state == before


def test_first_death_does_not_win_and_final_death_has_no_response(state):
    state = multi_active(state, adjacent=True)
    first = act(state, "basic_attack", "goblin_001", 12, 4)
    combat = first["state"]["combat"]
    assert combat["enemy_hp"] == 0
    assert combat["active"] and combat["result"] == "ongoing"
    ended = act(first["state"], "combat_end_turn", "player", 1)
    assert [attack["enemy_id"] for attack in ended["event_payload"]["enemy_attacks"]] == [
        "goblin_002"
    ]
    last = act(ended["state"], "basic_attack", "goblin_002", 12, 4)
    assert last["state"]["combat"]["result"] == "victory"
    assert not last["state"]["combat"]["active"]
    assert last["event_payload"]["enemy_attacks"] == []
    assert last["event_payload"]["enemy_attack"] is None


@pytest.mark.parametrize(
    "target,dead", [("goblin_002", False), ("goblin_002", True), ("unknown", False)]
)
def test_invalid_multi_target_rejects_before_rng(state, target, dead):
    state = multi_active(state)
    if dead:
        state["combat"]["enemies"][1].update(hp=0, x=1, y=3)
    before = deepcopy(state)
    roller = Rolls()
    with pytest.raises(ValueError):
        resolve(state, "basic_attack", (target,), roller=roller)
    assert roller.used == []
    assert state == before


def test_second_target_absent_in_legacy_rejected_before_rng(state):
    active(state, adjacent=True)
    with pytest.raises(ValueError):
        act(state, "basic_attack", "goblin_002")


def test_defend_applies_to_every_enemy_then_expires(state):
    state = multi_active(state, adjacent=True)
    defense = act(state, "combat_defend", "player")
    defended = act(defense["state"], "combat_end_turn", "player", 13, 13)
    assert [attack["ac"] for attack in defended["event_payload"]["enemy_attacks"]] == [19, 19]
    assert defended["state"]["player"]["hp"] == 31
    attack = act(defended["state"], "basic_attack", "goblin_001", 1)
    following = act(attack["state"], "combat_end_turn", "player", 13, 2, 13, 2)
    assert [attack["ac"] for attack in following["event_payload"]["enemy_attacks"]] == [17, 17]
    assert following["state"]["player"]["hp"] == 23
    assert following["state"]["combat"]["elapsed_seconds"] == 12


def test_player_death_stops_remaining_enemy_responses(state):
    state = multi_active(state, adjacent=True)
    state["player"]["hp"] = 1
    roller = Rolls(20, 6, 6)
    result = resolve(state, "combat_end_turn", ("player",), roller=roller)
    assert result["state"]["combat"]["result"] == "defeat"
    assert len(result["event_payload"]["enemy_attacks"]) == 1
    assert len(roller.used) == 3


def test_player_cannot_enter_second_enemy_tile_but_can_enter_dead_tile(state):
    state = multi_active(state, adjacent=True)
    with pytest.raises(ValueError):
        act(state, "combat_move", "down")
    state["combat"]["enemies"][1]["hp"] = 0
    result = act(state, "combat_move", "down")
    assert result["state"]["combat"]["player_y"] == 3


@pytest.mark.parametrize("blocking_hp,expected", [(7, (4, 1)), (0, (3, 2))])
def test_enemy_path_respects_other_living_enemies_and_crosses_dead_tiles(
    state, blocking_hp, expected
):
    state = multi_active(state)
    state["combat"]["enemies"][1].update(x=3, y=2, hp=blocking_hp)
    result = act(state, "combat_end_turn", "player", *([1] if blocking_hp else []))
    enemies = result["state"]["combat"]["enemies"]
    assert (enemies[0]["x"], enemies[0]["y"]) == expected
    living_positions = [(enemy["x"], enemy["y"]) for enemy in enemies if enemy["hp"] > 0]
    assert len(set(living_positions)) == len(living_positions)


def test_legacy_normalization_preserves_only_original_enemy_and_input(state):
    state["combat"] = {"active": False, "result": "victory", "enemy_hp": 0, "enemy_ac": 15}
    before = deepcopy(state)
    combat = normalized_combat(state)
    assert combat["enemies"] == [
        {"id": "goblin_001", "name": "Goblin", "hp": 0, "ac": 15, "x": 4, "y": 2, "conditions": []}
    ]
    assert not combat["active"]
    assert state == before


def test_authoritative_enemies_override_stale_legacy_aliases(state):
    state = multi_active(state)
    state["combat"].update(enemy_hp=99, enemy_x=0)
    combat = normalized_combat(state)
    assert combat["enemy_hp"] == 7
    assert combat["enemy_x"] == 4


def test_flee_ends_whole_multi_encounter(state):
    state = multi_active(state)
    state["combat"]["player_x"] = 0
    result = act(state, "combat_flee", "exit")
    assert result["state"]["combat"]["result"] == "fled"
    assert result["state"]["encounter_enemy_id"] is None
    assert result["event_payload"]["enemy_attacks"] == []


def test_three_moves_then_fourth_rejected_until_explicit_end_turn(state):
    state = multi_active(state)
    for direction in ("left", "up", "up"):
        state = act(state, "combat_move", direction)["state"]
    assert state["combat"]["movement_remaining"] == 0
    assert state["combat"]["round"] == 1
    assert state["combat"]["elapsed_seconds"] == 0
    assert not any(label.startswith("전투 이동:") for label in available_actions(state))
    before = deepcopy(state)
    roller = Rolls()
    with pytest.raises(ValueError):
        resolve(state, "combat_move", ("down",), roller=roller)
    assert roller.used == [] and state == before
    state = act(state, "combat_end_turn", "player")["state"]
    assert state["combat"]["movement_remaining"] == 3
    assert state["combat"]["round"] == 2
    assert state["combat"]["elapsed_seconds"] == 6


@pytest.mark.parametrize("first", ["basic_attack", "combat_defend"])
@pytest.mark.parametrize("second", ["basic_attack", "combat_defend"])
def test_attack_and_defense_share_one_action(state, first, second):
    active(state, adjacent=True)
    target = "goblin_001" if first == "basic_attack" else "player"
    state = act(state, first, target, *([1] if first == "basic_attack" else []))["state"]
    assert not state["combat"]["action_available"]
    assert state["combat"]["defending"] == (first == "combat_defend")
    assert "방어 태세" not in available_actions(state)
    assert "고블린을 공격한다" not in available_actions(state)
    before = deepcopy(state)
    roller = Rolls()
    with pytest.raises(ValueError):
        resolve(
            state, second, ("goblin_001" if second == "basic_attack" else "player",), roller=roller
        )
    assert roller.used == [] and state == before


def test_move_attack_move_potion_preserves_independent_budgets_and_no_response(state):
    active(state)
    state["combat"].update(enemy_x=3, enemy_y=2)
    state["resources"] = {"healing_potions": 2}
    state["player"]["hp"] = 20
    for intent, target, rolls in (
        ("combat_move", "right", ()),
        ("basic_attack", "goblin_001", (1,)),
        ("combat_move", "left", ()),
        ("combat_potion", "player", (3, 4)),
    ):
        result = act(state, intent, target, *rolls)
        assert result["event_payload"]["enemy_attacks"] == []
        state = result["state"]
    assert state["combat"]["movement_remaining"] == 1
    assert state["combat"]["action_available"] is False
    assert state["combat"]["bonus_action_available"] is False
    assert state["combat"]["elapsed_seconds"] == 0
    assert state["combat"]["enemy_x"] == 3
    assert state["player"]["hp"] == 29
    assert state["resources"] == {"healing_potions": 1}
    assert result["event_payload"]["healing_rolls"] == [3, 4]
    assert result["event_payload"]["healing"] == 9
    assert "전투 중 치유 물약" not in available_actions(state)
    with pytest.raises(ValueError):
        act(state, "combat_potion", "player")
    ended = act(state, "combat_end_turn", "player", 1)["state"]
    assert ended["combat"]["movement_remaining"] == 3
    assert ended["combat"]["action_available"] is True
    assert ended["combat"]["bonus_action_available"] is True


@pytest.mark.parametrize(
    "resources,hp", [({"healing_potions": 0}, 20), ({}, 20), ({"healing_potions": 1}, 37)]
)
def test_potion_unavailable_rejects_without_rng_or_mutation(state, resources, hp):
    active(state)
    state["resources"] = resources
    state["player"]["hp"] = hp
    assert "전투 중 치유 물약" not in available_actions(state)
    before = deepcopy(state)
    roller = Rolls()
    with pytest.raises(ValueError):
        resolve(state, "combat_potion", ("player",), roller=roller)
    assert roller.used == [] and state == before


def test_legacy_missing_resources_potion_caps_healing_and_initializes_only_copy(state):
    active(state)
    state["player"].update(hp=30, max_hp=32)
    before = deepcopy(state)
    result = act(state, "combat_potion", "player", 4, 4)
    assert result["event_payload"]["healing"] == 2
    assert result["state"]["player"]["hp"] == 32
    assert result["state"]["resources"]["healing_potions"] == 1
    assert state == before


def test_legacy_normalization_preserves_spent_budgets(state):
    active(state)
    state["combat"].update(
        movement_remaining=0, action_available=False, bonus_action_available=False, defending=True
    )
    before = deepcopy(state)
    projected = normalized_combat(state)
    for key in ("movement_remaining", "action_available", "bonus_action_available", "defending"):
        assert projected[key] == state["combat"][key]
    assert available_actions(state) == ["턴 종료"]
    assert state == before


def test_victory_and_flee_end_turn_time_without_enemy_response(state):
    active(state, adjacent=True)
    result = act(state, "basic_attack", "goblin_001", 12, 4)
    assert result["state"]["combat"]["elapsed_seconds"] == 6
    assert result["state"]["combat"]["action_available"] is False
    assert result["event_payload"]["enemy_attacks"] == []
    state["combat"].update(player_x=0, movement_remaining=0, action_available=False)
    result = act(state, "combat_flee", "exit")
    assert result["state"]["combat"]["elapsed_seconds"] == 6
    assert result["state"]["combat"]["movement_remaining"] == 0
    assert result["event_payload"]["enemy_attacks"] == []
    assert available_actions(result["state"]) == []
