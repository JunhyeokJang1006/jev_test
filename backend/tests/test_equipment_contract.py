import json
from copy import deepcopy

import pytest

from app import equipment, expedition, followup
from app.context import scene_context
from app.game import interpret_mock, resolve_action
from app.projection import public_state
from app.storage import connect
from app.world import available_actions

from .helpers import request
from .test_expedition import started
from .test_game import ATTACK, END_TURN, HIDE, Rolls
from .test_tactical import active


def state():
    return {
        "location_id": "market",
        "player": {"hp": 31, "max_hp": 37},
        "resources": {"gold": 100},
        "inventory": ["royal_seal"],
    }


def wear(s, key):
    equipment.initialize(s)
    if key not in s["equipment"]["owned"]:
        s["equipment"]["owned"].append(key)
    s["equipment"]["equipped"][equipment.CATALOG[key]["slot"]] = key


def test_purchase_does_not_equip_or_touch_quest_and_costs_one_minute():
    s = state()
    before = deepcopy(s)
    result = resolve_action(s, interpret_mock("중검 구매 (16골드)"), roller=Rolls())
    assert s == before
    assert result.state["resources"]["gold"] == 84
    assert result.state["inventory"] == ["royal_seal"]
    assert result.state["equipment"]["equipped"]["weapon"] == "travel_blade"
    assert result.state["elapsed_minutes"] == 1
    assert result.event_payload["target_id"] == "heavy_blade"
    assert result.event_payload["cost"] == 16
    equipped = resolve_action(result.state, interpret_mock("장비 장착: 중검"), roller=Rolls())
    assert equipped.state["elapsed_minutes"] == 2
    assert equipped.event_payload["cost"] == 0
    assert equipment.effective_stats(equipped.state)["damage_die"] == 10
    assert equipped.state["player"] == before["player"]


@pytest.mark.parametrize(
    "change,label",
    [
        ({"resources": {"gold": 15}}, "중검 구매 (16골드)"),
        ({"resources": {"gold": 0}}, "중검 구매 (16골드)"),
        ({"player": {"hp": 0}}, "중검 구매 (16골드)"),
        ({"combat": {"active": True}}, "중검 구매 (16골드)"),
        ({"location_id": "warehouse"}, "중검 구매 (16골드)"),
        ({}, "장비 장착: 중검"),
        ({}, "장비 장착: 여행검"),
        ({"equipment": {"owned": ["heavy_blade"]}}, "중검 구매 (16골드)"),
        ({"quest": {"ending": "law"}}, "중검 구매 (16골드)"),
    ],
)
def test_rejected_equipment_preserves_state_and_rng(change, label):
    s = state() | change
    before, rolls = deepcopy(s), Rolls()
    with pytest.raises(ValueError):
        resolve_action(s, interpret_mock(label), roller=rolls)
    assert s == before
    assert rolls.used == []
    assert label not in available_actions(s)


@pytest.mark.parametrize(
    "weapon,sides,bonus,damage",
    [
        ("heavy_blade", 10, 4, 4),
        ("duelist_blade", 6, 6, 3),
        ("travel_blade", 8, 5, 3),
    ],
)
def test_weapon_critical_uses_two_correct_dice_and_effective_bonuses(weapon, sides, bonus, damage):
    s = active(state() | {"location_id": "greyhaven_inn"}, adjacent=True)
    wear(s, weapon)
    rolls = Rolls(20, 2, 2)
    result = resolve_action(s, ATTACK, roller=rolls)
    assert rolls.used == [(20, 20), (sides, 2), (sides, 2)]
    assert result.event_payload["bonus"] == bonus
    assert result.event_payload["damage"] == 4 + damage
    assert result.event_payload["damage_die"] == sides


def test_legacy_default_equipment_preserves_attack_rng():
    s = active(state() | {"location_id": "greyhaven_inn"}, adjacent=True)
    legacy_rolls, equipped_rolls = Rolls(12, 3), Rolls(12, 3)
    legacy = resolve_action(s, ATTACK, roller=legacy_rolls)
    equipment.initialize(s)
    equipped = resolve_action(s, ATTACK, roller=equipped_rolls)
    assert legacy_rolls.used == equipped_rolls.used == [(20, 12), (8, 3)]
    assert legacy.event_payload == equipped.event_payload


@pytest.mark.parametrize(
    "armor,ac,hit",
    [
        ("travel_armor", 17, True),
        ("reinforced_armor", 19, False),
        ("scout_armor", 16, True),
    ],
)
def test_armor_changes_enemy_hit_boundary(armor, ac, hit):
    s = active(state() | {"location_id": "greyhaven_inn"}, adjacent=True)
    wear(s, armor)
    result = resolve_action(s, END_TURN, roller=Rolls(13, 1))
    assert result.event_payload["enemy_attack"]["ac"] == ac
    assert result.event_payload["enemy_attack"]["hit"] is hit


@pytest.mark.parametrize("armor,bonus", [("reinforced_armor", 3), ("scout_armor", 7)])
def test_armor_changes_hide_and_both_expedition_stealth_routes(armor, bonus):
    s = state() | {"location_id": "greyhaven_inn", "nearby_object_ids": ["door_inn"]}
    wear(s, armor)
    assert resolve_action(s, HIDE, roller=Rolls(7)).event_payload["bonus"] == bonus
    for intent, location in [
        ("expedition_passage", "eastern_gate"),
        ("expedition_approach", "watchtower"),
    ]:
        s = started()
        wear(s, armor)
        s["location_id"] = location
        if location == "watchtower":
            s["expedition"]["passage"] = "repair"
        result = expedition.apply(s, intent, ("stealth",), Rolls(7))
        assert result["dice"]["bonus"] == bonus


def test_followup_stealth_applies_armor_penalty():
    s = state() | {
        "location_id": "warehouse",
        "quest": {"ending": "law"},
        "followup": {"status": "active", "branch": "law", "evidence": []},
    }
    wear(s, "reinforced_armor")
    assert followup.check(s, "tax_ledger", Rolls(10))[2]["bonus"] == 3


@pytest.mark.parametrize(
    "raw",
    [
        None,
        {},
        {"owned": "heavy_blade"},
        {"owned": [], "equipped": {"weapon": "heavy_blade"}},
        {"owned": ["heavy_blade"], "equipped": {"armor": "heavy_blade"}},
        {"owned": [{"id": "heavy_blade"}], "equipped": {"weapon": "heavy_blade"}},
    ],
)
def test_malformed_gear_does_not_grant_default_ownership_or_bonuses(raw):
    s = state() | {"equipment": raw}
    assert equipment.gear(s)["equipped"] == {}
    assert equipment.effective_stats(s)["attack_bonus"] == 5
    assert "travel_blade" not in equipment.gear(s)["owned"]


def test_public_projection_and_context_do_not_stack_or_leak_catalog_canary():
    s = state()
    wear(s, "heavy_blade")
    wear(s, "scout_armor")
    s["equipment"]["owned"].extend(["PRIVATE_CANARY", {"secret": "PRIVATE_CANARY"}])
    s["equipment"]["catalog"] = [{"name": "PRIVATE_CANARY"}]
    s["effective_stats"] = {"attack_bonus": 999}
    first = public_state(s)
    assert public_state(first) == first
    assert first["effective_stats"]["attack_bonus"] == 4
    context = scene_context(first)
    assert context["effective_stats"] == first["effective_stats"]
    assert "PRIVATE_CANARY" not in json.dumps(context)
    assert {x["label"] for x in context["available_commands"]} == set(available_actions(first))


def test_api_purchase_replay_save_load_and_growth_do_not_stack():
    campaign = request("POST", "/api/campaign", json={}).json()
    s = campaign["state"]
    s.update(location_id="market", resources={"gold": 16})
    s["progression"].update(xp=100)
    connection = connect()
    connection.execute(
        "UPDATE campaigns SET state_json=? WHERE id=?", (json.dumps(s), campaign["id"])
    )
    connection.close()
    payload = {
        "campaign_id": campaign["id"],
        "input": "중검 구매 (16골드)",
        "expected_state_version": 0,
        "request_id": "00000000-0000-4000-8000-000000000887",
    }
    first = request("POST", "/api/game/turn", json=payload)
    assert first.status_code == 200
    assert first.json()["state"]["resources"]["gold"] == 0
    assert request("POST", "/api/game/turn", json=payload).json() == first.json()
    for version, label in enumerate(
        ["장비 장착: 중검", "성장: 전투 숙련", "장비 장착: 여행검", "장비 장착: 중검"], 1
    ):
        response = request(
            "POST",
            "/api/game/turn",
            json={"campaign_id": campaign["id"], "input": label, "expected_state_version": version},
        )
        assert response.status_code == 200, response.text
    assert response.json()["state"]["player"]["attack_bonus"] == 6
    assert response.json()["state"]["effective_stats"]["attack_bonus"] == 5
    saved = request("POST", f"/api/campaign/{campaign['id']}/save").json()
    restored = request(
        "POST", f"/api/campaign/{campaign['id']}/load", json={"snapshot_id": saved["snapshot_id"]}
    ).json()
    assert restored["state"]["effective_stats"]["attack_bonus"] == 5
    assert restored["state"]["resources"]["gold"] == 0


@pytest.mark.parametrize(
    "change",
    [
        {"player": None},
        {"combat": []},
        {"resources": "private"},
        {"quest": None},
        {"followup": []},
        {"player": {"hp": "31"}},
        {"resources": {"gold": None}},
        {"resources": {"gold": True}},
        {"location_id": []},
    ],
)
def test_equipment_malformed_guards_fail_closed_without_mutation(change):
    s = state() | change
    before = deepcopy(s)
    assert equipment.available_actions(s) == []
    with pytest.raises(ValueError):
        equipment.apply(s, "buy_equipment", ("heavy_blade",))
    assert s == before


def test_ai_provider_stub_receives_effective_stats_and_equipment_commands(monkeypatch):
    from app import ai

    s = state()
    wear(s, "scout_armor")
    monkeypatch.setattr(ai, "_provider_config", lambda: [("stub", "invalid", "stub", "stub")])

    def chat(provider, messages, **kwargs):
        assert "Player stats are base values" in messages[0]["content"]
        assert "catalog modifiers again" in messages[0]["content"]
        assert "Authoritative dice override" in messages[0]["content"]
        scene = json.loads(messages[1]["content"])["scene"]
        assert scene["effective_stats"]["stealth_bonus"] == 7
        assert any(x["intent"] == "buy_equipment" for x in scene["available_commands"])
        return "stub", json.dumps(
            {
                "intent": "buy_equipment",
                "action_type": "exploration",
                "target_ids": ["heavy_blade"],
                "skill": None,
                "difficulty_band": None,
            }
        )

    monkeypatch.setattr(ai, "_chat", chat)
    proposal, provider = ai.interpret_action("중검을 구입한다", s)
    assert provider == "stub"
    assert proposal.intent == "buy_equipment"


def test_narrator_stub_receives_equipment_no_recalculation_rule(monkeypatch):
    from app import ai

    outcome = resolve_action(state(), interpret_mock("중검 구매 (16골드)"), roller=Rolls())
    monkeypatch.setattr(ai, "_provider_config", lambda: [("stub", "invalid", "stub", "stub")])

    def chat(provider, messages, **kwargs):
        system = messages[0]["content"]
        assert "Player stats are base values" in system
        assert "effective_stats includes equipped modifiers exactly once" in system
        assert "catalog modifiers again" in system
        assert "Authoritative dice override" in system
        assert json.loads(messages[1]["content"])["outcome"]["cost"] == 16
        return "stub", "중검을 구입했다."

    monkeypatch.setattr(ai, "_chat", chat)
    assert ai.narrate_outcome("중검 구매 (16골드)", outcome, "stub") == ("중검을 구입했다.", "stub")


@pytest.mark.parametrize("weapon,hit", [("heavy_blade", False), ("duelist_blade", True)])
def test_weapon_accuracy_tradeoff_changes_hit_boundary(weapon, hit):
    s = active(state() | {"location_id": "greyhaven_inn"}, adjacent=True)
    s["hidden"] = False
    wear(s, weapon)
    result = resolve_action(s, ATTACK, roller=Rolls(7, 1))
    assert result.event_payload["hit"] is hit


def test_reinforced_armor_defend_adds_two_without_changing_base_ac():
    s = active(state() | {"location_id": "greyhaven_inn"}, adjacent=True)
    wear(s, "reinforced_armor")
    guarded = resolve_action(s, interpret_mock("방어 태세"), roller=Rolls())
    result = resolve_action(guarded.state, END_TURN, roller=Rolls(16))
    assert result.event_payload["enemy_attack"]["ac"] == 21
    assert result.event_payload["enemy_attack"]["hit"] is False
    assert "ac" not in result.state["player"]


@pytest.mark.parametrize(
    "change",
    [
        {"resources": {"gold": 15}},
        {"player": {"hp": 0}},
        {"combat": {"active": True}},
    ],
)
def test_api_rejected_purchase_keeps_stored_state_and_version(change):
    campaign = request("POST", "/api/campaign", json={}).json()
    s = campaign["state"] | {"location_id": "market"} | change
    connection = connect()
    connection.execute(
        "UPDATE campaigns SET state_json=? WHERE id=?", (json.dumps(s), campaign["id"])
    )
    connection.close()
    before = request("GET", f"/api/campaign/{campaign['id']}").json()
    result = request(
        "POST",
        "/api/game/turn",
        json={
            "campaign_id": campaign["id"],
            "input": "중검 구매 (16골드)",
            "expected_state_version": 0,
        },
    )
    assert result.status_code == 422
    after = request("GET", f"/api/campaign/{campaign['id']}").json()
    assert after["state"] == before["state"]
    assert after["state_version"] == before["state_version"]
