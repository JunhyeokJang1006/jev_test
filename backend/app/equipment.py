"""고정 장비 목록과 서버 권위 소유권·실효 능력치. 기본 능력치는 변경하지 않는다."""

from copy import deepcopy

from .resources import DEFAULT


def _item(id, name, slot, price, **deltas):
    return (
        dict(
            id=id,
            name=name,
            slot=slot,
            price=price,
            attack_delta=0,
            damage_delta=0,
            damage_die=8,
            ac_delta=0,
            stealth_delta=0,
        )
        | deltas
    )


CATALOG = {
    item["id"]: item
    for item in (
        _item("travel_blade", "여행검", "weapon", 0),
        _item("heavy_blade", "중검", "weapon", 16, attack_delta=-1, damage_delta=1, damage_die=10),
        _item("duelist_blade", "결투검", "weapon", 12, attack_delta=1, damage_die=6),
        _item("shortbow", "단궁", "ranged", 10, damage_die=6),
        _item("travel_armor", "여행 갑옷", "armor", 0),
        _item("reinforced_armor", "강화 갑옷", "armor", 18, ac_delta=2, stealth_delta=-2),
        _item("scout_armor", "정찰 갑옷", "armor", 14, ac_delta=-1, stealth_delta=2),
    )
}
BASE_GEAR = {
    "owned": ["travel_blade", "travel_armor"],
    "equipped": {"weapon": "travel_blade", "armor": "travel_armor"},
}
COMMANDS = {
    **{
        f"{item['name']} 구매 ({item['price']}골드)": ("buy_equipment", key)
        for key, item in CATALOG.items()
        if item["price"]
    },
    **{f"장비 장착: {item['name']}": ("equip_equipment", key) for key, item in CATALOG.items()},
}


def gear(state: dict) -> dict:
    """전체 필드가 없는 옛 저장만 기본 장비를 받는다. 잘못된 소유권은 인정하지 않는다."""
    raw = state.get("equipment", BASE_GEAR)
    raw = raw if isinstance(raw, dict) else {}
    owned = raw.get("owned", [])
    owned = owned if isinstance(owned, list) else []
    owned = list(dict.fromkeys(x for x in owned if isinstance(x, str) and x in CATALOG))
    equipped = raw.get("equipped", {})
    equipped = equipped if isinstance(equipped, dict) else {}
    return {
        "owned": owned,
        "equipped": {
            slot: item
            for slot, item in equipped.items()
            if slot in {"weapon", "armor", "ranged"}
            and isinstance(item, str)
            and item in owned
            and CATALOG[item]["slot"] == slot
        },
    }


def initialize(state: dict) -> None:
    state["equipment"] = gear(state)


def public_equipment(state: dict) -> dict:
    return gear(state) | {"catalog": deepcopy(list(CATALOG.values()))}


def effective_stats(state: dict) -> dict:
    player = state.get("player", {})
    stats = {
        key: int(player.get(key, value))
        for key, value in {
            "ac": 17,
            "attack_bonus": 5,
            "damage_bonus": 3,
            "stealth_bonus": 5,
            "persuasion_bonus": 3,
        }.items()
    }
    stats["damage_die"] = 8
    for slot, key in gear(state)["equipped"].items():
        if slot == "ranged":
            continue
        item = CATALOG[key]
        for stat, delta in (
            ("ac", "ac_delta"),
            ("attack_bonus", "attack_delta"),
            ("damage_bonus", "damage_delta"),
            ("stealth_bonus", "stealth_delta"),
        ):
            stats[stat] += item[delta]
        if slot == "weapon":
            stats["damage_die"] = item["damage_die"]
    return stats


def available_actions(state: dict) -> list[str]:
    for field in ("player", "combat", "resources", "quest", "followup"):
        if field in state and not isinstance(state[field], dict):
            return []
    hp = state.get("player", {}).get("hp", 0)
    gold = state.get("resources", DEFAULT).get("gold", 0)
    location = state.get("location_id")
    status = state.get("followup", {}).get("status")
    if type(hp) is not int or type(gold) is not int or not isinstance(location, str):
        return []
    if (
        hp <= 0
        or state.get("combat", {}).get("active")
        or state.get("location_id")
        not in {"greyhaven_inn", "market", "warehouse", "eastern_gate", "watchtower"}
        or (state.get("quest", {}).get("ending") and status not in ("active", "completed"))
    ):
        return []
    equipment = gear(state)
    return [
        label
        for label, (intent, key) in COMMANDS.items()
        if (
            intent == "buy_equipment"
            and state.get("location_id") == "market"
            and key not in equipment["owned"]
            and gold >= CATALOG[key]["price"]
        )
        or (
            intent == "equip_equipment"
            and key in equipment["owned"]
            and equipment["equipped"].get(CATALOG[key]["slot"]) != key
        )
    ]


def apply(state: dict, intent: str, targets: tuple[str, ...]) -> dict:
    if len(targets) != 1 or (intent, targets[0]) not in {
        COMMANDS[label] for label in available_actions(state)
    }:
        raise ValueError("현재 위치·체력·소유권·골드로는 이 장비 행동을 할 수 없습니다.")
    initialize(state)
    key = targets[0]
    item = CATALOG[key]
    if intent == "buy_equipment":
        state.setdefault("resources", dict(DEFAULT))["gold"] -= item["price"]
        state["equipment"]["owned"].append(key)
        narrative = f"{item['price']}골드를 지불하고 {item['name']}을 구입했다. 장착할 수 있다."
    else:
        state["equipment"]["equipped"][item["slot"]] = key
        narrative = f"{item['name']}을 장착했다."
    return {
        "narrative": narrative,
        "minutes": 1,
        "dice": {"outcome": intent},
        "payload": {
            "rule_id": "greyhaven-equipment-v1",
            "cost": item["price"] if intent == "buy_equipment" else 0,
        },
    }
