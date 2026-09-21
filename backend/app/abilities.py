"""CUSTOM 무예 능력. 직업·SRD 구현이 아닌 서버 권위 회복 규칙."""

from typing import Any


def remaining(state: dict[str, Any]) -> int:
    if "abilities" not in state:
        return 1  # 구버전 저장에만 최초 사용권을 부여한다.
    abilities = state["abilities"]
    ability = abilities.get("second_wind") if isinstance(abilities, dict) else None
    value = ability.get("remaining") if isinstance(ability, dict) else None
    return value if type(value) is int and value in (0, 1) else 0


def initialize(state: dict[str, Any]) -> None:
    if "abilities" not in state:
        state["abilities"] = {"second_wind": {"remaining": 1}}


def set_remaining(state: dict[str, Any], value: int) -> None:
    # 잘못된 저장값도 유효한 휴식 이후에만 사용권을 회복한다.
    if not isinstance(state.get("abilities"), dict):
        state["abilities"] = {}
    state["abilities"]["second_wind"] = {"remaining": value}


def public_abilities(state: dict[str, Any]) -> dict[str, Any]:
    progress = state.get("progression")
    level = progress.get("level", 3) if isinstance(progress, dict) else 3
    level = level if type(level) is int and 1 <= level <= 6 else 3
    return {
        "second_wind": {
            "remaining": remaining(state),
            "maximum": 1,
            "healing_die": 10,
            "healing_bonus": level,
            "recharge": "short_or_long_rest",
        }
    }
