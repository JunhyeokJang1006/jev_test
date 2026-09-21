import httpx
import pytest

from app import ai
from app.game import TurnOutcome


@pytest.fixture
def providers(monkeypatch):
    configured = [
        ("luna", "https://primary.invalid", "gpt-5.6-luna", "test-key"),
        ("deepseek", "https://fallback.invalid", "deepseek-chat", "test-key"),
    ]
    monkeypatch.setattr(ai, "_provider_config", lambda: configured)
    return configured


@pytest.mark.parametrize("body", [[], None, {}, {"choices": []}, {"choices": [None]}])
def test_malformed_primary_response_uses_fallback(monkeypatch, providers, body):
    calls = []

    def post(url, **kwargs):
        calls.append(url)
        content = (
            body
            if len(calls) == 1
            else {
                "choices": [
                    {
                        "message": {
                            "content": '{"intent":"describe_action",'
                            '"action_type":"exploration","target_ids":[]}'
                        }
                    }
                ]
            }
        )
        return httpx.Response(200, json=content, request=httpx.Request("POST", url))

    monkeypatch.setattr(ai.httpx, "post", post)
    proposal, used = ai.interpret_action("둘러본다")
    assert used == "deepseek"
    assert proposal.intent == "describe_action"
    assert len(calls) == 2


def test_narration_primary_timeout_uses_deepseek(monkeypatch, providers):
    calls = []

    def chat(provider, messages, **kwargs):
        calls.append(provider[0])
        if provider[0] == "luna":
            raise httpx.ReadTimeout("timeout")
        return "deepseek", "경비병이 지나간다."

    monkeypatch.setattr(ai, "_chat", chat)
    outcome = TurnOutcome("TEST", {}, {}, "기본 서사", {})
    assert ai.narrate_outcome("숨는다", outcome, "luna") == ("경비병이 지나간다.", "deepseek")
    assert calls == ["luna", "deepseek"]


@pytest.mark.parametrize(
    "content",
    [
        '{"intent":null,"action_type":"attack"}',
        '{"intent":"basic_attack","action_type":"attack","target_ids":"goblin_001"}',
        '{"intent":"basic_attack","action_type":"attack","target_ids":[3]}',
        '{"intent":"basic_attack","action_type":"attack","hp":999}',
    ],
)
def test_invalid_interpretation_never_reaches_engine(monkeypatch, providers, content):
    monkeypatch.setattr(ai, "_chat", lambda provider, *args, **kwargs: (provider[0], content))
    proposal, used = ai.interpret_action("숨는다")
    assert used == "mock"
    assert proposal.intent == "hide_beside_door"
