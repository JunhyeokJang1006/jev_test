from copy import deepcopy

import pytest

from app import progression


def ready(**progress):
    return {
        "player": {"hp": 10, "max_hp": 20},
        "progression": {**deepcopy(progression.DEFAULT), "xp": 125, **progress},
    }


def test_initialization_preserves_zero_and_does_not_share_lists():
    first, second = {"progression": {"xp": 0, "level": 0}}, {}
    progression.initialize(first)
    progression.initialize(second)
    first["progression"]["choices"].append("combat")
    assert first["progression"]["level"] == 0
    assert first["progression"]["xp"] == 0
    assert second["progression"] == progression.DEFAULT


def test_public_projection_is_allowlist_and_does_not_mutate_input():
    state = ready(earned=["secret"], internal="private")
    original = deepcopy(state)
    public = progression.public_progression(state)
    assert set(public) == {"level", "xp", "next_level_xp", "choices"}
    assert public["next_level_xp"] == 100
    assert progression.available_actions({**state, "progression": public}) == list(
        progression.COMMANDS
    )
    public["choices"].append("combat")
    assert state == original
    empty = {}
    assert progression.public_progression(empty)["level"] == 3
    assert empty == {}


@pytest.mark.parametrize(
    ("trait", "stat", "expected"),
    [
        ("combat", "attack_bonus", 6),
        ("stealth", "stealth_bonus", 7),
        ("persuasion", "persuasion_bonus", 5),
    ],
)
def test_each_growth_choice(trait, stat, expected):
    state = ready()
    result = progression.apply(state, "train", (trait,))
    assert state["player"] == {"hp": 15, "max_hp": 25, stat: expected}
    assert state["progression"]["level"] == 4
    assert state["progression"]["xp"] == 125
    assert state["progression"]["choices"] == [trait]
    assert result["minutes"] == 60
    assert result["dice"]["outcome"] == "trained"
    assert result["payload"]["rule_id"] == "greyhaven-growth-v1"
    assert progression.available_actions(state) == []


@pytest.mark.parametrize("level,xp", [(3, 99), (4, 249), (5, 449), (6, 9999)])
def test_xp_gates_and_cap_reject_without_mutating(level, xp):
    state = ready(level=level, xp=xp)
    original = deepcopy(state)
    with pytest.raises(ValueError):
        progression.apply(state, "train", ("combat",))
    assert state == original


def test_growth_after_ending_and_max_level():
    state = ready(level=5, xp=450)
    state.update(quest={"ending": "exile"}, followup={"status": "completed"})
    state["player"].update(hp=20, attack_bonus=0)
    progression.apply(state, "train", ("combat",))
    assert state["player"]["hp"] == state["player"]["max_hp"] == 25
    assert state["player"]["attack_bonus"] == 1
    assert progression.public_progression(state)["next_level_xp"] is None
    assert progression.available_actions(state) == []


@pytest.mark.parametrize("blocked", [{"player": {"hp": 0}}, {"combat": {"active": True}}])
def test_dead_or_fighting_cannot_grow(blocked):
    state = ready()
    state.update(blocked)
    assert progression.available_actions(state) == []


@pytest.mark.parametrize("branch", ["law", "mercy", "exile"])
def test_noncombat_path_awards_125_once(branch):
    before = {"quest": {"ending": None}}
    original = deepcopy(before)
    after = {"quest": {"ending": branch}}
    assert progression.reward(before, after) == 50
    assert progression.reward(before, after) == 0
    assert before == original
    next_state = deepcopy(after)
    next_state["followup"] = {"status": "completed"}
    assert progression.reward(after, next_state) == 75
    assert progression.reward(after, next_state) == 0
    assert next_state["progression"]["xp"] == 125


def test_goblin_reward_once_and_other_enemy_not_rewarded():
    before = {"combat": {"result": None}}
    after = {"combat": {"result": "victory", "enemy_id": "goblin_001"}}
    assert progression.reward(before, after) == 25
    assert progression.reward(before, after) == 0
    other = {"combat": {"result": "victory", "enemy_id": "other"}}
    assert progression.reward(before, other) == 0
    assert "progression" not in other


def test_old_terminal_save_and_unsupported_action_never_get_retroactive_xp():
    for state in (
        {},
        {"quest": {"ending": "law"}},
        {"followup": {"status": "completed"}},
        {"combat": {"result": "victory", "enemy_id": "goblin_001"}},
    ):
        original = deepcopy(state)
        assert progression.reward(original, state) == 0
        assert state == original


@pytest.mark.parametrize(
    "intent,targets", [("invalid", ("combat",)), ("train", ()), ("train", ("combat", "stealth"))]
)
def test_invalid_commands_leave_state_unchanged(intent, targets):
    state = ready()
    original = deepcopy(state)
    with pytest.raises(ValueError):
        progression.apply(state, intent, targets)
    assert state == original
