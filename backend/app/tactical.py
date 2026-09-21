"""서버 권위 격자 전투. 자체 규칙이며 외부 룰셋을 구현하지 않는다."""

from collections import deque
from copy import deepcopy
from typing import Any

from .dice import Roller
from .resources import DEFAULT as DEFAULT_RESOURCES
from .resources import initialize as initialize_resources

COMMANDS = {
    "전투 시작": ("start_combat", "goblin_001"),
    "고블린을 공격한다": ("basic_attack", "goblin_001"),
    "두 번째 고블린을 공격한다": ("basic_attack", "goblin_002"),
    "전투 이동: 위": ("combat_move", "up"),
    "전투 이동: 아래": ("combat_move", "down"),
    "전투 이동: 왼쪽": ("combat_move", "left"),
    "전투 이동: 오른쪽": ("combat_move", "right"),
    "방어 태세": ("combat_defend", "player"),
    "턴 종료": ("combat_end_turn", "player"),
    "전투 중 치유 물약": ("combat_potion", "player"),
    "전투에서 후퇴": ("combat_flee", "exit"),
}
DIRECTIONS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
WALLS = {(2, 1), (2, 3)}


def _eligible(state: dict) -> bool:
    return (
        state.get("location_id") == "greyhaven_inn"
        and state.get("encounter_enemy_id") == "goblin_001"
        and state.get("player", {}).get("hp", 0) > 0
        and not state.get("quest", {}).get("ending")
        and not state.get("followup")
        and state.get("scene_status") != "ended"
    )


def _combat(state: dict) -> dict:
    combat = deepcopy(state.get("combat") or {})
    defaults = {
        "active": True,
        "enemy_id": "goblin_001",
        "enemy_name": "Goblin",
        "enemy_hp": 7,
        "enemy_ac": 12,
        "round": 1,
        "movement_remaining": 3,
        "action_available": True,
        "bonus_action_available": True,
        "defending": False,
        "result": "ongoing",
        "player_x": 1,
        "player_y": 2,
        "enemy_x": 4,
        "enemy_y": 2,
        "width": 6,
        "height": 5,
        "walls": [[2, 1], [2, 3]],
        "exit_x": 0,
        "exit_y": 2,
        "elapsed_seconds": 0,
    }
    for key, value in defaults.items():
        combat.setdefault(key, value)
    if "enemies" not in combat:
        combat["enemies"] = [
            {key: combat[f"enemy_{key}"] for key in ("id", "name", "hp", "ac", "x", "y")}
        ]
        if not state.get("combat"):
            combat["enemies"].append(
                {
                    "id": "goblin_002",
                    "name": "Goblin Scout",
                    "hp": 7,
                    "ac": 12,
                    "x": 4,
                    "y": 4,
                }
            )
    _sync_legacy(combat)
    return combat


def _sync_legacy(combat: dict) -> None:
    first = next((enemy for enemy in combat["enemies"] if enemy["id"] == "goblin_001"), None)
    if first is not None:
        for key in ("id", "name", "hp", "ac", "x", "y"):
            combat[f"enemy_{key}"] = first[key]


def _occupied(combat: dict, *, excluding: str | None = None) -> set[tuple[int, int]]:
    return {
        (enemy["x"], enemy["y"])
        for enemy in combat["enemies"]
        if enemy["hp"] > 0 and enemy["id"] != excluding
    }


def _position(combat: dict, actor: str) -> tuple[int, int]:
    return combat[f"{actor}_x"], combat[f"{actor}_y"]


def normalized_combat(state: dict) -> dict:
    """공개 투영용 사본: 진행 중인 옛 전투만 기본 격자 정보를 보완한다."""
    existing = state.get("combat") or {}
    return _combat(state) if existing else {}


def _distance(a: tuple, b: tuple) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _walkable(point: tuple) -> bool:
    return 0 <= point[0] < 6 and 0 <= point[1] < 5 and point not in WALLS


def available_actions(state: dict) -> list[str]:
    if not _eligible(state):
        return []
    existing = state.get("combat") or {}
    if not existing.get("active"):
        return [] if existing else ["전투 시작"]
    combat = _combat(state)
    player = _position(combat, "player")
    actions = [
        label
        for label, (intent, target) in COMMANDS.items()
        if intent == "basic_attack"
        and combat["action_available"]
        and any(
            enemy["id"] == target
            and enemy["hp"] > 0
            and _distance(player, (enemy["x"], enemy["y"])) == 1
            for enemy in combat["enemies"]
        )
    ]
    occupied = _occupied(combat)
    for label, (intent, direction) in COMMANDS.items():
        if intent == "combat_move" and combat["movement_remaining"] > 0:
            dx, dy = DIRECTIONS[direction]
            point = (player[0] + dx, player[1] + dy)
            if _walkable(point) and point not in occupied:
                actions.append(label)
    if combat["action_available"]:
        actions.append("방어 태세")
    resources = state.get("resources", DEFAULT_RESOURCES)
    if (
        combat["bonus_action_available"]
        and resources.get("healing_potions", 0) > 0
        and state["player"]["hp"] < state["player"].get("max_hp", 37)
    ):
        actions.append("전투 중 치유 물약")
    actions.append("턴 종료")
    if player == (0, 2):
        actions.append("전투에서 후퇴")
    return actions


def _enemy_response(state: dict, actor: dict, roller: Roller, *, defend: bool = False) -> dict:
    combat = state["combat"]
    player, enemy = _position(combat, "player"), (actor["x"], actor["y"])
    occupied = _occupied(combat, excluding=actor["id"])
    origin = enemy
    if _distance(player, enemy) > 1:
        queue = deque([(enemy, [])])
        seen = {enemy}
        while queue:
            point, path = queue.popleft()
            if _distance(point, player) == 1:
                enemy = path[0]
                actor["x"], actor["y"] = enemy
                break
            for dx, dy in DIRECTIONS.values():
                neighbor = point[0] + dx, point[1] + dy
                if (
                    _walkable(neighbor)
                    and neighbor != player
                    and neighbor not in occupied
                    and neighbor not in seen
                ):
                    seen.add(neighbor)
                    queue.append((neighbor, [*path, neighbor]))
    response: dict[str, Any] = {
        "enemy_id": actor["id"],
        "moved": enemy != origin,
        "from": list(origin),
        "to": list(enemy),
    }
    if _distance(player, enemy) != 1:
        response["attacked"] = False
        return response
    roll = roller.roll(20)
    ac = int(state["player"].get("ac", 17)) + (2 if defend else 0)
    hit = roll == 20 or (roll != 1 and roll + 4 >= ac)
    damage_rolls = [roller.roll(6) for _ in range(2 if roll == 20 else 1)] if hit else []
    damage = sum(damage_rolls) + 2 if hit else 0
    state["player"]["hp"] = max(0, state["player"]["hp"] - damage)
    response.update(
        attacked=True,
        roll=roll,
        bonus=4,
        ac=ac,
        hit=hit,
        critical=roll == 20,
        damage_rolls=damage_rolls,
        damage_bonus=2,
        damage=damage,
        remaining_hp=state["player"]["hp"],
    )
    if state["player"]["hp"] == 0:
        combat.update(active=False, result="defeat")
    return response


def _enemy_side_response(state: dict, roller: Roller, *, defend: bool = False) -> list[dict]:
    responses = []
    for actor in state["combat"]["enemies"]:
        if state["player"]["hp"] <= 0:
            break
        if actor["hp"] > 0:
            responses.append(_enemy_response(state, actor, roller, defend=defend))
    return responses


def resolve(state: dict, intent: str, targets: tuple, *, roller: Roller) -> dict:
    """검증 실패는 입력이나 주사위를 변경하지 않고 예외를 발생시킨다."""
    if len(targets) != 1 or (intent, targets[0]) not in COMMANDS.values():
        raise ValueError("유효하지 않은 전투 행동 또는 대상입니다.")
    if not _eligible(state):
        raise ValueError("현재 장면에서는 전투할 수 없습니다.")
    existing = state.get("combat") or {}
    starting = not existing
    if existing and not existing.get("active"):
        raise ValueError("이미 종료된 전투입니다.")
    if starting and intent not in {"start_combat", "basic_attack"}:
        raise ValueError("먼저 전투를 시작해 주세요.")
    if not starting and intent == "start_combat":
        raise ValueError("이미 전투 중입니다.")
    result = deepcopy(state)
    combat = result["combat"] = _combat(state)
    if intent == "basic_attack" and not any(
        enemy["id"] == targets[0] and enemy["hp"] > 0 for enemy in combat["enemies"]
    ):
        raise ValueError("존재하지 않거나 쓰러진 적은 공격할 수 없습니다.")
    payload: dict[str, Any] = {
        "intent": intent,
        "target_id": targets[0],
        "rule_id": "greyhaven-tactical-v3",
        "enemy_attack": None,
        "enemy_attacks": [],
    }
    dice: dict[str, Any] = {"outcome": "no_check_required"}
    event_type = "COMBAT_ACTION_RESOLVED"
    narrative = "방어 태세를 취해 이번 적 공격에 방어도가 2 증가한다."
    if starting:
        player_roll, enemy_roll = roller.roll(20), roller.roll(20)
        first = "player" if player_roll >= enemy_roll else "enemy"
        combat["initiative"] = {
            "player_roll": player_roll,
            "enemy_roll": enemy_roll,
            "player_bonus": 2,
            "enemy_bonus": 2,
            "first": first,
        }
        payload["initiative"] = deepcopy(combat["initiative"])
        if first == "enemy":
            payload["enemy_attacks"] = _enemy_side_response(result, roller)
            combat["elapsed_seconds"] += 6
        event_type = "COMBAT_STARTED"
        narrative = "전투가 시작됐다. 격자에서 이동해 적에게 접근할 수 있다."
        dice = {"outcome": "initiative", "player_roll": player_roll, "enemy_roll": enemy_roll}
    else:
        label = next(
            label for label, command in COMMANDS.items() if command == (intent, targets[0])
        )
        if label not in available_actions(state):
            raise ValueError(
                "행동 예산, 자원, 사거리, 장애물 또는 후퇴 위치 때문에 실행할 수 없는 행동입니다."
            )
        if intent == "combat_move":
            dx, dy = DIRECTIONS[targets[0]]
            combat["player_x"] += dx
            combat["player_y"] += dy
            combat["movement_remaining"] -= 1
            narrative = "한 칸 이동했다."
        elif intent == "combat_defend":
            combat.update(action_available=False, defending=True)
        elif intent == "combat_potion":
            initialize_resources(result)
            result["resources"]["healing_potions"] -= 1
            combat["bonus_action_available"] = False
            rolls = [roller.roll(4), roller.roll(4)]
            before = result["player"]["hp"]
            result["player"]["hp"] = min(
                result["player"].get("max_hp", 37), before + sum(rolls) + 2
            )
            healing = result["player"]["hp"] - before
            payload.update(healing=healing, healing_rolls=rolls, cost=0)
            dice = {"outcome": "healed", "healing": healing}
            narrative = f"치유 물약 1개를 사용해 HP {healing} 회복했다."
        elif intent == "combat_end_turn":
            narrative = "플레이어의 턴을 종료했다."
            payload["enemy_attacks"] = _enemy_side_response(
                result, roller, defend=combat["defending"]
            )
            combat["defending"] = False
            if combat["active"]:
                combat.update(
                    movement_remaining=3, action_available=True, bonus_action_available=True
                )
                combat["round"] += 1
        elif intent == "combat_flee":
            combat.update(active=False, result="fled")
            result["encounter_enemy_id"] = None
            narrative = "출구로 후퇴했다. 이번 조우의 재진입은 지원하지 않는다."
        elif intent == "basic_attack":
            combat["action_available"] = False
            enemy = next(enemy for enemy in combat["enemies"] if enemy["id"] == targets[0])
            roll = roller.roll(20)
            ac = int(enemy["ac"])
            bonus = int(result["player"].get("attack_bonus", 5))
            damage_bonus = int(result["player"].get("damage_bonus", 3))
            hit = roll == 20 or (roll != 1 and roll + bonus >= ac)
            damage_rolls = [roller.roll(8) for _ in range(2 if roll == 20 else 1)] if hit else []
            damage = max(0, sum(damage_rolls) + damage_bonus) if hit else 0
            enemy["hp"] = max(0, enemy["hp"] - damage)
            if all(actor["hp"] <= 0 for actor in combat["enemies"]):
                combat.update(active=False, result="victory")
            payload.update(
                roll=roll,
                bonus=bonus,
                ac=ac,
                hit=hit,
                critical=roll == 20,
                damage=damage,
                damage_rolls=damage_rolls,
                damage_bonus=damage_bonus,
                remaining_hp=enemy["hp"],
            )
            dice = {
                "roll": roll,
                "bonus": bonus,
                "total": roll + bonus,
                "ac": ac,
                "damage": damage,
                "outcome": "hit" if hit else "miss",
            }
            event_type = "PLAYER_ATTACKED"
            narrative = (
                f"{enemy['name']}에게 {damage} 피해를 입혔다." if hit else "공격이 빗나갔다."
            )
        if intent == "combat_end_turn" or combat["result"] in {"victory", "fled"}:
            combat["elapsed_seconds"] += 6
    _sync_legacy(combat)
    responses = payload["enemy_attacks"]
    payload["enemy_attack"] = responses[0] if responses else None
    for response in responses:
        enemy_name = next(
            enemy["name"] for enemy in combat["enemies"] if enemy["id"] == response["enemy_id"]
        )
        if response.get("attacked"):
            narrative += f" {enemy_name}의 공격으로 {response['damage']} 피해를 입었다."
        elif response["moved"]:
            narrative += f" {enemy_name}이 한 칸 접근했다."
    if combat["result"] == "victory":
        narrative += " 고블린이 쓰러졌다. 전투에서 승리했다."
    elif combat["result"] == "defeat":
        narrative += " 쓰러져 더 이상 싸울 수 없다. 이전 저장을 복원할 수 있다."
    result["hidden"] = False
    payload["result"] = combat["result"]
    return {
        "event_type": event_type,
        "event_payload": payload,
        "state": result,
        "narrative": narrative,
        "dice": dice,
    }
