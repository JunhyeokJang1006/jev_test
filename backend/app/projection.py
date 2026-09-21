"""공개 응답 경계. 새 내부 필드는 명시적으로 등록하기 전까지 공개하지 않는다."""

from typing import Any

from .resources import DEFAULT
from .tactical import normalized_combat


def pick(value: Any, fields: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        key: value[key]
        for key in fields.split()
        if key in value and (value[key] is None or isinstance(value[key], (str, int, float, bool)))
    }


def strings(value: Any) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def public_state(state: dict[str, Any]) -> dict[str, Any]:
    result = pick(
        state,
        "location_id location_name day time hidden elapsed_minutes encounter_enemy_id "
        "combat_seconds",
    )
    result["player"] = pick(
        state.get("player"), "id name hp max_hp ac stealth_bonus attack_bonus damage_bonus"
    )
    result["resources"] = pick(
        state.get("resources", DEFAULT), "gold healing_potions camp_supplies hit_dice"
    )
    result["npcs"] = [pick(npc, "id name disposition") for npc in state.get("npcs", [])]
    result["nearby_object_ids"] = strings(state.get("nearby_object_ids", []))
    if "inventory" in state:
        result["inventory"] = strings(state["inventory"])
    if "quest" in state:
        result["quest"] = pick(state["quest"], "id title status ending ending_title")
        result["quest"]["clues"] = strings(state["quest"].get("clues", []))
    if "journal" in state:
        result["journal"] = [
            pick(entry, "action target text day time") for entry in state["journal"]
        ]
    if "followup" in state:
        result["followup"] = pick(state["followup"], "id title status objective branch resolution")
        result["followup"]["evidence"] = strings(state["followup"].get("evidence", []))
        result["followup"]["attempts"] = {
            key: pick(value, "skill roll bonus dc success")
            for key, value in state["followup"].get("attempts", {}).items()
            if key in {"tax_ledger", "oren_testimony", "refugee_supplies", "safe_route"}
        }
        result["followup"]["complications"] = strings(state["followup"].get("complications", []))
    if "world_consequences" in state:
        result["world_consequences"] = pick(state["world_consequences"], "tax_collection refugees")
    if "combat" in state:
        combat = normalized_combat(state)
        result["combat"] = pick(
            combat,
            "active enemy_id enemy_name enemy_hp enemy_ac round result "
            "width height player_x player_y enemy_x enemy_y exit_x exit_y elapsed_seconds",
        )
        result["combat"]["initiative"] = pick(
            combat.get("initiative"),
            "player_roll enemy_roll player_bonus enemy_bonus first",
        )
        result["combat"]["walls"] = [
            list(point)
            for point in combat.get("walls", [])
            if isinstance(point, (list, tuple))
            and len(point) == 2
            and all(type(v) is int for v in point)
        ]
    return result


def public_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result = pick(
        payload,
        "intent target_id enemy_id skill dc roll bonus success ac damage hit "
        "remaining_hp critical damage_bonus rule_id result resolved clue minutes ending "
        "healing cost reward_gold moved attacked",
    )
    if "damage_rolls" in payload:
        result["damage_rolls"] = [value for value in payload["damage_rolls"] if type(value) is int]
    if "healing_rolls" in payload:
        result["healing_rolls"] = [
            value for value in payload["healing_rolls"] if type(value) is int
        ]
    if "initiative" in payload:
        result["initiative"] = pick(
            payload["initiative"], "player_roll enemy_roll player_bonus enemy_bonus first"
        )
    for coordinate in ("from", "to"):
        point = payload.get(coordinate)
        if (
            isinstance(point, list)
            and len(point) == 2
            and all(type(value) is int for value in point)
        ):
            result[coordinate] = list(point)
    if "enemy_attack" in payload:
        result["enemy_attack"] = (
            public_payload(payload["enemy_attack"])
            if isinstance(payload["enemy_attack"], dict)
            else None
        )
    return result


def public_turn(turn: dict[str, Any]) -> dict[str, Any]:
    result = pick(turn, "turn_id state_version narrative narrative_status")
    result["state"] = public_state(turn.get("state", {}))
    result["dice"] = pick(
        turn.get("dice"), "roll bonus total dc ac damage healing outcome player_roll enemy_roll"
    )
    event = turn.get("event", {})
    result["event"] = {
        **pick(event, "type"),
        "payload": public_payload(event.get("payload", {})),
    }
    result["ai"] = pick(turn.get("ai"), "interpreter narrator")
    result["jev"] = pick(turn.get("jev"), "enabled status label confidence")
    result["actions"] = strings(turn.get("actions", []))
    return result
