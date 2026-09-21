"""누적 경험치와 선택형 성장의 서버 권위 규칙."""

from copy import deepcopy
from typing import Any

DEFAULT = {"level": 3, "xp": 0, "earned": [], "choices": []}
THRESHOLDS = {3: 100, 4: 250, 5: 450}
COMMANDS = {
    "성장: 전투 숙련": ("train", "combat"),
    "성장: 은밀한 발걸음": ("train", "stealth"),
    "성장: 설득의 기술": ("train", "persuasion"),
}
TRAITS = {
    "combat": ("attack_bonus", 5, 1),
    "stealth": ("stealth_bonus", 5, 2),
    "persuasion": ("persuasion_bonus", 3, 2),
}


def initialize(state: dict[str, Any]) -> None:
    """기존 저장의 값(0 포함)을 보존하고 없는 필드만 채운다."""
    progress = state.setdefault("progression", {})
    for key, value in DEFAULT.items():
        if key not in progress:
            progress[key] = deepcopy(value)


def public_progression(state: dict[str, Any]) -> dict[str, Any]:
    progress = state.get("progression", {})
    level = progress.get("level", DEFAULT["level"])
    level = level if type(level) is int else DEFAULT["level"]
    xp = progress.get("xp", 0)
    return {
        "level": level,
        "xp": xp if type(xp) is int else 0,
        "next_level_xp": THRESHOLDS.get(level),
        "choices": [
            choice
            for choice in progress.get("choices", [])
            if isinstance(choice, str) and choice in TRAITS
        ],
    }


def available_actions(state: dict[str, Any]) -> list[str]:
    progress = public_progression(state)
    threshold = progress["next_level_xp"]
    if (
        state.get("player", {}).get("hp", 0) <= 0
        or state.get("combat", {}).get("active", False)
        or threshold is None
        or progress["xp"] < threshold
    ):
        return []
    return list(COMMANDS)


def apply(state: dict[str, Any], intent: str, targets: tuple[str, ...]) -> dict[str, Any]:
    """검증 후 호출자가 복제한 상태에 한 단계 성장을 적용한다."""
    allowed = {COMMANDS[label] for label in available_actions(state)}
    if len(targets) != 1 or (intent, targets[0]) not in allowed:
        raise ValueError("현재 선택할 수 없는 성장입니다.")
    target = targets[0]
    initialize(state)
    progress, player = state["progression"], state["player"]
    progress["level"] += 1
    progress["choices"].append(target)
    player["max_hp"] = player.get("max_hp", 37) + 5
    player["hp"] = min(player["max_hp"], player["hp"] + 5)
    stat, default, increase = TRAITS[target]
    player[stat] = player.get(stat, default) + increase
    return {
        "narrative": f"한 시간의 수련을 마쳤다. 레벨 {progress['level']}로 성장했다.",
        "minutes": 60,
        "dice": {"outcome": "trained"},
        "payload": {
            "rule_id": "greyhaven-growth-v1",
            "level": progress["level"],
            "choice": target,
        },
    }


def reward(before: dict[str, Any], after: dict[str, Any]) -> int:
    """실제 완료 전이만 보상하며 서버 내부 원장으로 중복을 막는다."""
    candidates = []
    if not before.get("quest", {}).get("ending") and after.get("quest", {}).get("ending") in {
        "law",
        "mercy",
        "exile",
    }:
        candidates.append(("seal_ending", 50))
    if (
        before.get("followup", {}).get("status") != "completed"
        and after.get("followup", {}).get("status") == "completed"
    ):
        candidates.append(("followup_completed", 75))
    combat = after.get("combat", {})
    if (
        before.get("combat", {}).get("result") != "victory"
        and combat.get("result") == "victory"
        and combat.get("enemy_id") == "goblin_001"
    ):
        candidates.append(("goblin_victory", 25))
    earned = after.get("progression", {}).get("earned", [])
    awards = [(key, amount) for key, amount in candidates if key not in earned]
    if not awards:
        return 0
    initialize(after)
    amount = sum(value for _, value in awards)
    after["progression"]["xp"] += amount
    after["progression"]["earned"].extend(key for key, _ in awards)
    return amount
