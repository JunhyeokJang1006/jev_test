"""Interpreter에 전달하는 공개 정보만 명시적으로 선택한다."""

from typing import Any

from .projection import public_state
from .world import COMMANDS, LOCATIONS, available_actions


def scene_context(state: dict[str, Any]) -> dict[str, Any]:
    state = public_state(state)
    location = LOCATIONS.get(state.get("location_id"), {})
    player = state.get("player", {})
    quest = state.get("quest", {})
    commands = [
        {"label": label, "intent": COMMANDS[label][0], "target_id": COMMANDS[label][1]}
        for label in available_actions(state)
        if label in COMMANDS
    ]
    return {
        "location": {"id": state.get("location_id"), "name": state.get("location_name")},
        "exits": [
            {"id": key, "name": LOCATIONS[key]["name"]}
            for key in location.get("exits", [])
            if any(item["intent"] == "travel" and item["target_id"] == key for item in commands)
        ],
        "player": {key: player.get(key) for key in ("id", "name", "hp", "max_hp", "ac")},
        "nearby_npcs": [
            {key: npc.get(key) for key in ("id", "name", "disposition")}
            for npc in state.get("npcs", [])[:10]
        ],
        "known_clues": list(quest.get("clues", []))[:20],
        "inventory": list(state.get("inventory", []))[:30],
        "resources": state.get("resources"),
        "progression": state.get("progression"),
        "combat": state.get("combat"),
        "quest_status": quest.get("status"),
        "followup": state.get("followup"),
        "expedition": state.get("expedition"),
        "world_consequences": state.get("world_consequences"),
        "market_policy": state.get("market_policy"),
        "world_effects": state.get("world_effects"),
        "recent_public_events": [
            str(entry.get("text", ""))[:500] for entry in state.get("journal", [])[-6:]
        ],
        "available_commands": commands,
    }
