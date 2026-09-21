"""고정 합성 장면의 자유 입력 해석 평가. DB/게임 판정/서사는 실행하지 않는다."""

from copy import deepcopy
from dataclasses import dataclass
from math import ceil
from typing import Any
from unittest.mock import patch

from . import ai
from .ai_metrics import capture_calls
from .world import COMMANDS, LOCATIONS


@dataclass(frozen=True)
class Case:
    id: str
    text: str
    scene: str
    intent: str
    targets: tuple[str, ...] = ()


# 정답은 interpreter/mock 결과로 생성하지 않는 독립적인 명세다.
CORPUS = (
    Case("travel_market", "비를 맞더라도 시장 쪽으로 걸어갈래.", "inn", "travel", ("market",)),
    Case("travel_inn", "이제 여관으로 돌아가자.", "market", "travel", ("greyhaven_inn",)),
    Case("travel_warehouse", "강변 창고까지 발걸음을 옮긴다.", "market", "travel", ("warehouse",)),
    Case("travel_gate_locked", "동쪽 성문으로 가 보고 싶어.", "market", "describe_action"),
    Case("travel_unreachable", "여관에서 곧장 망루로 순간이동할래.", "inn", "describe_action"),
    Case("talk_harlan", "하를란에게 말을 걸어 소식을 묻는다.", "inn", "talk", ("npc_harlan",)),
    Case("talk_mira", "미라와 잠깐 이야기를 나누고 싶다.", "inn", "talk", ("npc_mira",)),
    Case("talk_oren", "오렌에게 다가가 이야기를 청해.", "market", "talk", ("npc_oren",)),
    Case("talk_absent", "여기 없는 오렌과 지금 대화할래.", "inn", "describe_action"),
    Case("hide_door", "여관 문 옆에 몸을 숨긴다.", "inn", "hide_beside_door", ("door_inn",)),
    Case(
        "hide_shadow", "문 옆 그림자에 은신해 기다린다.", "inn", "hide_beside_door", ("door_inn",)
    ),
    Case("forbidden_attack", "고블린 대신 하를란을 공격하겠다.", "combat", "describe_action"),
    Case(
        "invented_target",
        "세 번째 고블린을 공격한다, 대상은 goblin_999야.",
        "combat",
        "describe_action",
    ),
    Case(
        "attack_first",
        "눈앞 첫 번째 고블린을 검으로 공격한다.",
        "combat",
        "basic_attack",
        ("goblin_001",),
    ),
    Case(
        "attack_second",
        "두 번째 고블린에게 검을 휘두르겠다.",
        "combat",
        "basic_attack",
        ("goblin_002",),
    ),
    Case(
        "combat_shove",
        "첫 번째 고블린을 밀쳐서 바닥에 넘어뜨려.",
        "combat",
        "combat_shove",
        ("goblin_001",),
    ),
    Case(
        "combat_feint",
        "첫 번째 고블린의 시선을 교란하겠다.",
        "combat",
        "combat_feint",
        ("goblin_001",),
    ),
    Case("combat_dash", "이 턴에는 전력으로 질주할래.", "combat", "combat_dash", ("player",)),
    Case(
        "action_exhausted",
        "행동을 이미 썼지만 첫 번째 고블린을 다시 밀쳐 넘어뜨릴래.",
        "exhausted",
        "describe_action",
    ),
    Case(
        "bonus_exhausted",
        "보조 행동이 없지만 첫 번째 고블린을 교란해.",
        "exhausted",
        "describe_action",
    ),
    Case("recover_potion", "다친 몸을 낫게 치유 물약을 마신다.", "inn", "recover", ("potion",)),
    Case("recover_rest", "여관에서 한 시간 정도 짧게 쉬겠다.", "inn", "recover", ("short_rest",)),
    Case("recover_empty", "물약이 없어도 치유 물약을 사용하겠다.", "empty", "describe_action"),
    Case(
        "ending_confirm",
        "하를란에게 봉인을 반환하면 끝나는지 설명해 줘. 아직 실행하지 마.",
        "seal",
        "describe_action",
    ),
    Case(
        "ending_explicit",
        "내 결정은 확실해. 봉인을 하를란에게 돌려주고 사건을 끝내겠다.",
        "seal",
        "finish_quest",
        ("law",),
    ),
    Case("unsupported", "용으로 변신해서 하늘 끝까지 날아간다.", "inn", "describe_action"),
)


def fixture_state(scene: str) -> dict[str, Any]:
    """실제 저장 상태를 읽거나 엔진으로 진행하지 않는 합성 fixture."""
    location = "market" if scene == "market" else "greyhaven_inn"
    state: dict[str, Any] = {
        "location_id": location,
        "location_name": LOCATIONS[location]["name"],
        "player": {"id": "player", "name": "평가 모험가", "hp": 20, "max_hp": 37, "ac": 17},
        "npcs": [
            {"id": id_, "name": name, "disposition": "neutral"}
            for id_, name in LOCATIONS[location]["npcs"]
        ],
        "nearby_object_ids": ["door_inn"] if location == "greyhaven_inn" else [],
        "encounter_enemy_id": "goblin_001",
        "quest": {"id": "royal_seal", "status": "active", "clues": [], "ending": None},
        "inventory": ["royal_seal"] if scene == "seal" else [],
        "resources": {
            "gold": 20,
            "healing_potions": 0 if scene == "empty" else 2,
            "camp_supplies": 2,
            "hit_dice": 2,
        },
        "journal": [],
    }
    if scene in {"combat", "exhausted"}:
        state["combat"] = {
            "active": True,
            "player_x": 3,
            "player_y": 2,
            "action_available": scene != "exhausted",
            "bonus_action_available": scene != "exhausted",
            "movement_remaining": 3,
            "enemies": [
                {
                    "id": "goblin_001",
                    "name": "Goblin",
                    "hp": 7,
                    "ac": 12,
                    "x": 4,
                    "y": 2,
                    "conditions": [],
                },
                {
                    "id": "goblin_002",
                    "name": "Goblin Scout",
                    "hp": 7,
                    "ac": 12,
                    "x": 3,
                    "y": 3,
                    "conditions": [],
                },
            ],
        }
    return state


def _percentile(values: list[float], fraction: float) -> float | None:
    return sorted(values)[max(0, ceil(len(values) * fraction) - 1)] if values else None


def evaluate(
    *,
    live: bool = False,
    max_calls: int | None = None,
    limit: int | None = None,
    offset: int = 0,
    provider: str = "luna",
) -> dict[str, Any]:
    if provider not in {"luna", "deepseek"}:
        raise ValueError("지원하지 않는 provider")
    if live and (type(max_calls) is not int or not 1 <= max_calls <= 100):
        raise ValueError("live에는 1~100의 max_calls가 필요합니다")
    if not live and max_calls is not None:
        raise ValueError("max_calls에는 live가 필요합니다")
    if type(offset) is not int or not 0 <= offset < len(CORPUS):
        raise ValueError("offset 범위 오류")
    if limit is not None and (type(limit) is not int or not 1 <= limit <= len(CORPUS) - offset):
        raise ValueError("limit 범위 오류")
    selected = CORPUS[offset : offset + limit if limit is not None else None]
    # mock은 원래 _provider_config를 호출하지 않는다. live는 선택 공급자만 허용한다.
    providers = [item for item in ai._provider_config() if item[0] == provider] if live else []
    rows = []
    with (
        patch.object(ai, "_provider_config", return_value=providers),
        capture_calls(max_calls=max_calls if live else 0) as calls,
    ):
        for case in selected:
            start = len(calls)
            proposal, source = ai.interpret_action(case.text, deepcopy(fixture_state(case.scene)))
            case_calls = deepcopy(calls[start:])
            correct = (proposal.intent, proposal.target_ids) == (case.intent, case.targets)
            known_intents = {value[0] for value in COMMANDS.values()} | {
                "describe_action",
                "hide_beside_door",
            }
            known_targets = {value[1] for value in COMMANDS.values()} | {"door_inn"}
            # 모델이 임의 문자열을 반환해도 보고서로 원문이 유출되지 않는다.
            actual = {
                "intent": proposal.intent if proposal.intent in known_intents else "[unknown]",
                "targets": [
                    target if target in known_targets else "[unknown]"
                    for target in proposal.target_ids
                ],
            }
            rows.append(
                {
                    "id": case.id,
                    "expected": {"intent": case.intent, "targets": list(case.targets)},
                    "actual": actual,
                    "provider": source
                    if source in {"luna", "deepseek", "mock", "engine"}
                    else "unknown",
                    "correct": correct,
                    "model_evaluated": live
                    and source == provider
                    and any(
                        call["provider"] == provider and call["status"] == "ok"
                        for call in case_calls
                    ),
                    "calls": case_calls,
                }
            )
    evaluated = [row for row in rows if row["model_evaluated"]]
    latencies = [
        call["latency_ms"] for call in calls if isinstance(call.get("latency_ms"), (int, float))
    ]
    totals = {
        "attempted": len(rows),
        "correct": sum(row["correct"] for row in rows),
        "accuracy": sum(row["correct"] for row in rows) / len(rows),
        "model_evaluated": len(evaluated),
        "provider_only_accuracy": sum(row["correct"] for row in evaluated) / len(evaluated)
        if evaluated
        else None,
        "coverage": len(evaluated) / len(rows),
        "call_count": len(calls),
        "latency_ms": {"p50": _percentile(latencies, 0.5), "p95": _percentile(latencies, 0.95)},
    }
    totals["tokens"] = {
        field: {
            "sum": sum(call[field] for call in calls if isinstance(call.get(field), int)),
            "missing_count": sum(call.get(field) is None for call in calls),
        }
        for field in ("input_tokens", "output_tokens")
    }
    return {
        "mode": "live" if live else "mock",
        "provider": provider if live else None,
        "corpus_size": len(CORPUS),
        "selection": {"offset": offset, "count": len(rows)},
        "complete": len(rows) == len(CORPUS),
        "passed": all(row["correct"] for row in rows) and (not live or len(evaluated) == len(rows)),
        "cases": rows,
        "totals": totals,
    }
