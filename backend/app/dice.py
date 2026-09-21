"""서버 주사위. 테스트에서는 같은 인터페이스의 roller를 주입한다."""

from secrets import randbelow
from typing import Protocol


class Roller(Protocol):
    def roll(self, sides: int) -> int: ...


class Dice:
    def roll(self, sides: int) -> int:
        if sides < 2:
            raise ValueError("주사위 면 수는 2 이상이어야 합니다.")
        return randbelow(sides) + 1
