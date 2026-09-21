"""단궁 능력치와 정확한 선분/닫힌 벽 사각형 교차 판정."""

from fractions import Fraction

from .equipment import gear
from .resources import arrows


def ranged_stats(state: dict) -> dict:
    player = state.get("player", {})
    return {
        "equipped": gear(state)["equipped"].get("ranged") == "shortbow",
        "attack_bonus": int(player.get("attack_bonus", 5)),
        "damage_die": 6,
        "damage_bonus": int(player.get("damage_bonus", 3)),
        "minimum_range": 2,
        "maximum_range": 5,
        "ammunition": arrows(state),
    }


def clear_line(start: tuple[int, int], end: tuple[int, int], walls: set[tuple[int, int]]) -> bool:
    """좌표를 두 배로 확장하고 유리수 구간 교차를 사용한다. 모서리 접촉도 차단."""
    for wall in walls:
        lower, upper = Fraction(0), Fraction(1)
        for origin, target, center in zip(start, end, wall, strict=True):
            delta = 2 * (target - origin)
            left, right = 2 * (center - origin) - 1, 2 * (center - origin) + 1
            if delta == 0:
                if not left <= 0 <= right:
                    break
            else:
                entry, leave = sorted((Fraction(left, delta), Fraction(right, delta)))
                lower, upper = max(lower, entry), min(upper, leave)
                if lower > upper:
                    break
        else:
            return False
    return True
