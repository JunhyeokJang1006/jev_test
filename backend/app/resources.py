"""회복·보급의 서버 규칙. 현재는 전투 밖의 회복만 지원한다."""

from typing import Any

from . import abilities
from .dice import Roller
from .world_effects import prices

DEFAULT = {"gold": 20, "healing_potions": 2, "camp_supplies": 2, "hit_dice": 2}
COMMANDS = {
    "치유 물약 사용": ("recover", "potion"),
    "여관에서 짧은 휴식": ("recover", "short_rest"),
    "여관에서 긴 휴식": ("recover", "long_rest"),
    **{
        f"치유 물약 구매 ({price}골드)": ("buy_resource", f"healing_potions:{price}")
        for price in (6, 8, 10)
    },
    **{
        f"야영 보급품 구매 ({price}골드)": ("buy_resource", f"camp_supplies:{price}")
        for price in (2, 3, 4)
    },
}


def initialize(state: dict[str, Any]) -> None:
    # 구버전 상태에만 초기 자원을 부여한다. 0인 자원을 다시 채우지 않는다.
    state.setdefault("resources", dict(DEFAULT))


def available_actions(state: dict[str, Any]) -> list[str]:
    player = state.get("player", {})
    if player.get("hp", 0) <= 0 or state.get("combat", {}).get("active"):
        return []
    if state.get("quest", {}).get("ending") and state.get("followup", {}).get("status") not in {
        "active",
        "completed",
    }:
        return []
    resources = state.get("resources", DEFAULT)
    injured = player.get("hp", 0) < player.get("max_hp", 37)
    actions = []
    if injured and resources.get("healing_potions", 0) > 0:
        actions.append("치유 물약 사용")
    if state.get("location_id") == "greyhaven_inn":
        depleted = abilities.remaining(state) == 0
        if (injured and resources.get("hit_dice", 0) > 0) or depleted:
            actions.append("여관에서 짧은 휴식")
        if resources.get("camp_supplies", 0) > 0 and (
            injured or resources.get("hit_dice", 0) < 2 or depleted
        ):
            actions.append("여관에서 긴 휴식")
    if state.get("location_id") == "market":
        for item, price in prices(state).items():
            if resources.get("gold", 0) >= price and resources.get(item, 0) < 5:
                name = "치유 물약" if item == "healing_potions" else "야영 보급품"
                actions.append(f"{name} 구매 ({price}골드)")
    return actions


def apply(state: dict[str, Any], intent: str, target: str, roller: Roller) -> dict:
    if (intent, target) not in {COMMANDS[label] for label in available_actions(state)}:
        raise ValueError("현재 위치·체력·자원으로는 이 행동을 할 수 없습니다.")
    initialize(state)
    resources = state["resources"]
    player = state["player"]
    before = player["hp"]
    rolls = []
    minutes = 1
    cost = 0
    if intent == "buy_resource":
        target, quoted_price = target.split(":")
        cost = int(quoted_price)
        resources["gold"] -= cost
        resources[target] = resources.get(target, 0) + 1
        narrative = (
            f"상인에게 {cost}골드를 지불하고 "
            + ("치유 물약" if target == "healing_potions" else "야영 보급품")
            + " 1개를 샀다."
        )
    elif target == "long_rest":
        resources["camp_supplies"] -= 1
        resources["hit_dice"] = 2
        abilities.set_remaining(state, 1)
        player["hp"] = player.get("max_hp", 37)
        minutes = 480
        narrative = "보급품 1개로 8시간 쉬었다. 체력·회복 주사위·전투 회복력을 회복했다."
    else:
        if target == "potion":
            resources["healing_potions"] -= 1
            rolls = [roller.roll(4), roller.roll(4)]
            narrative = "치유 물약 1개를 사용했다."
        else:
            minutes = 60
            abilities.set_remaining(state, 1)
            narrative = "여관에서 1시간 쉬며 전투 회복력을 회복했다."
            if before < player.get("max_hp", 37) and resources.get("hit_dice", 0) > 0:
                resources["hit_dice"] -= 1
                rolls = [roller.roll(8)]
                narrative += " 회복 주사위 1개를 사용했다."
        if rolls:
            player["hp"] = min(player.get("max_hp", 37), before + sum(rolls) + 2)
    healed = player["hp"] - before
    if intent == "recover":
        state["hidden"] = False
        narrative += f" HP {healed} 회복 ({player['hp']}/{player.get('max_hp', 37)})."
    return {
        "narrative": narrative,
        "minutes": minutes,
        "dice": {"outcome": "healed" if intent == "recover" else "purchased", "healing": healed},
        "payload": {
            "healing": healed,
            "healing_rolls": rolls,
            "cost": cost,
            "rule_id": "greyhaven-recovery-v2",
        },
    }
