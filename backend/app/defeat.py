"""여관 고정 시나리오의 대가 있는 패배 회복. 외부 게임 룰셋이 아니다."""

from typing import Any

from .resources import DEFAULT, initialize

COMMANDS = {
    "응급 치료 받기 (10골드, 1시간)": ("recover_defeat", "medic"),
    "보급품으로 치료하기 (보급품 1개, 4시간)": ("recover_defeat", "supplies"),
    "도움을 기다리기 (8시간)": ("recover_defeat", "wait"),
}


def eligible(state: dict[str, Any]) -> bool:
    combat = state.get("combat", {})
    return (
        state.get("player", {}).get("hp") == 0
        and state.get("location_id") == "greyhaven_inn"
        and state.get("encounter_enemy_id") == "goblin_001"
        and combat.get("result") == "defeat"
        and combat.get("active") is False
        and state.get("defeat", {}).get("status", "pending") == "pending"
    )


def available_actions(state: dict[str, Any]) -> list[str]:
    if not eligible(state):
        return []
    resources = state.get("resources", DEFAULT)
    return [
        label
        for label, (_, method) in COMMANDS.items()
        if method == "wait"
        or (method == "medic" and resources.get("gold", 0) >= 10)
        or (method == "supplies" and resources.get("camp_supplies", 0) >= 1)
    ]


def apply(state: dict[str, Any], targets: tuple[str, ...]) -> dict[str, Any]:
    if len(targets) != 1 or ("recover_defeat", targets[0]) not in {
        COMMANDS[label] for label in available_actions(state)
    }:
        raise ValueError("현재 상태·장소·자원으로는 패배 후 회복을 할 수 없습니다.")
    method = targets[0]
    initialize(state)
    gold, supplies, minutes = {
        "medic": (10, 0, 60),
        "supplies": (0, 1, 240),
        "wait": (0, 0, 480),
    }[method]
    state["resources"]["gold"] = state["resources"].get("gold", 0) - gold
    state["resources"]["camp_supplies"] = state["resources"].get("camp_supplies", 0) - supplies
    max_hp = max(1, int(state["player"].get("max_hp", 37)))
    healing = min(max_hp, max(1, max_hp // 2))
    state["player"]["hp"] = healing
    state["hidden"] = False
    state["defeat"] = {
        "status": "recovered",
        "method": method,
        "gold_spent": gold,
        "supplies_spent": supplies,
        "minutes": minutes,
        "healing": healing,
    }
    description = {
        "medic": "10골드를 지불하고 1시간 동안 응급 치료를 받았다.",
        "supplies": "보급품 1개를 사용해 4시간 동안 상처를 치료했다.",
        "wait": "8시간 뒤 여관 사람들의 도움으로 의식을 되찾았다.",
    }[method]
    return {
        "event_type": "DEFEAT_RECOVERED",
        "event_payload": {
            "intent": "recover_defeat",
            "target_id": method,
            "healing": healing,
            "cost": gold,
            "gold_spent": gold,
            "supplies_spent": supplies,
            "minutes": minutes,
            "rule_id": "greyhaven-defeat-recovery-v1",
            "result": "recovered",
        },
        "state": state,
        "narrative": description + f" HP {healing}/{max_hp}로 회복했다. 모험을 계속할 수 있다.",
        "dice": {"outcome": "recovered", "healing": healing},
    }
