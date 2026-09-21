"""평가 corpus·명시 opt-in·실모델 coverage의 독립 검증."""

import importlib.util
import json
from pathlib import Path

import pytest

from app import ai, evaluation
from app.ai_metrics import tracked_call
from app.context import scene_context
from app.game import ActionProposal
from app.world import COMMANDS


def test_corpus_is_free_text_and_labels_match_synthetic_scene():
    assert len(evaluation.CORPUS) >= 24
    assert len({case.id for case in evaluation.CORPUS}) == len(evaluation.CORPUS)
    for case in evaluation.CORPUS:
        assert case.text.strip().lower() not in {label.lower() for label in COMMANDS}
        state = evaluation.fixture_state(case.scene)
        allowed = {
            (item["intent"], (item["target_id"],))
            for item in scene_context(state)["available_commands"]
        }
        if case.intent not in {"describe_action", "hide_beside_door"}:
            assert (case.intent, case.targets) in allowed, case.id
    exhausted = scene_context(evaluation.fixture_state("exhausted"))["available_commands"]
    assert not {"combat_shove", "combat_feint", "combat_dash"} & {
        item["intent"] for item in exhausted
    }
    empty = scene_context(evaluation.fixture_state("empty"))["available_commands"]
    assert not any(item["intent"] == "recover" and item["target_id"] == "potion" for item in empty)


def test_mock_never_reads_provider_configuration_or_calls_http(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("must not call")

    monkeypatch.setattr(ai, "_provider_config", forbidden)
    monkeypatch.setattr(ai.httpx, "post", forbidden)
    report = evaluation.evaluate()
    assert report["mode"] == "mock"
    assert report["complete"]
    assert not report["passed"]  # mock의 실제 한계를 정답 수정으로 감추지 않는다.
    assert report["totals"]["coverage"] == 0
    assert report["totals"]["provider_only_accuracy"] is None
    assert report["totals"]["call_count"] == 0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"live": True},
        {"live": True, "max_calls": 0},
        {"live": True, "max_calls": 101},
        {"max_calls": 1},
        {"limit": 0},
        {"limit": 1000},
        {"provider": "auto"},
    ],
)
def test_invalid_options_never_discover_providers(monkeypatch, kwargs):
    monkeypatch.setattr(ai, "_provider_config", lambda: pytest.fail("unexpected provider access"))
    with pytest.raises(ValueError):
        evaluation.evaluate(**kwargs)


def test_live_counts_only_selected_provider_and_stops_at_budget(monkeypatch):
    monkeypatch.setattr(
        ai,
        "_provider_config",
        lambda: [
            ("luna", "unused", "gpt-test", "unused"),
            ("deepseek", "unused", "deepseek-test", "unused"),
        ],
    )
    seen = []

    def chat(provider, messages, *, json_mode=False):
        assert provider[0] == "luna"
        with tracked_call(provider[0], provider[2], json_mode=json_mode) as record:
            seen.append(provider[0])
            record.update(input_tokens=12, output_tokens=4)
            case = evaluation.CORPUS[len(seen) - 1]
            return provider[0], json.dumps(
                {
                    "intent": case.intent,
                    "action_type": "exploration",
                    "target_ids": list(case.targets),
                    "skill": None,
                    "difficulty_band": None,
                }
            )

    monkeypatch.setattr(ai, "_chat", chat)
    report = evaluation.evaluate(live=True, max_calls=1, limit=2)
    assert seen == ["luna"]
    assert report["totals"]["call_count"] == 1
    assert report["totals"]["coverage"] == 0.5
    assert report["totals"]["provider_only_accuracy"] == 1
    assert report["totals"]["tokens"]["input_tokens"] == {"sum": 12, "missing_count": 0}
    assert not report["complete"] and not report["passed"]


def test_fallback_correctness_does_not_count_as_model_evaluation(monkeypatch):
    monkeypatch.setattr(ai, "_provider_config", lambda: [])
    report = evaluation.evaluate(live=True, max_calls=1)
    assert any(row["correct"] for row in report["cases"])
    assert report["totals"]["coverage"] == 0
    assert not report["passed"]


def test_each_state_is_independent_and_report_contains_no_raw_data(monkeypatch):
    observed = []

    def interpret(text, state):
        observed.append(state["player"]["hp"])
        state["player"]["hp"] = -999
        return ActionProposal(
            "secret-model-response", "exploration", ("secret-target",), None, None
        ), "mock"

    monkeypatch.setattr(ai, "interpret_action", interpret)
    report = evaluation.evaluate(limit=2)
    assert observed == [20, 20]
    serialized = json.dumps(report, ensure_ascii=False)
    assert "secret-model-response" not in serialized and "secret-target" not in serialized
    assert "평가 모험가" not in serialized
    assert all(case.text not in serialized for case in evaluation.CORPUS)
    assert "state" not in report["cases"][0]


def test_cli_live_gate_and_mock_json(monkeypatch, capsys):
    script = Path(__file__).resolve().parents[2] / "scripts" / "evaluate_ai.py"
    spec = importlib.util.spec_from_file_location("evaluate_ai_cli", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(ai, "_provider_config", lambda: pytest.fail("unexpected provider access"))
    with pytest.raises(SystemExit) as error:
        module.main(["--live"])
    assert error.value.code == 2
    assert module.main(["--limit", "1"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["mode"] == "mock" and report["totals"]["attempted"] == 1
