import json
import logging
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from app import ai
from app.ai_metrics import capture_calls

PROVIDER = ("luna", "https://example.invalid/private-path", "gpt-5.6-luna", "PRIVATE_KEY")
MESSAGES = [{"role": "user", "content": "PRIVATE_PROMPT"}]


def response(body, status=200):
    return httpx.Response(status, json=body, request=httpx.Request("POST", PROVIDER[1]))


def test_success_records_usage_without_content(monkeypatch, caplog):
    monkeypatch.setattr(
        ai.httpx,
        "post",
        lambda *a, **k: response(
            {
                "choices": [{"message": {"content": "PRIVATE_RESPONSE"}}],
                "usage": {"prompt_tokens": 42, "completion_tokens": 7, "extra": "PRIVATE_USAGE"},
            }
        ),
    )
    caplog.set_level(logging.INFO, logger="luna_realms.ai_calls")
    with capture_calls(max_calls=1) as calls:
        assert ai._chat(PROVIDER, MESSAGES, json_mode=True) == ("luna", "PRIVATE_RESPONSE")
    assert len(calls) == 1
    assert calls[0]["status"] == "ok"
    assert calls[0]["call_type"] == "interpreter"
    assert calls[0]["input_tokens"] == 42
    assert calls[0]["output_tokens"] == 7
    assert calls[0]["latency_ms"] >= 0
    assert "PRIVATE" not in json.dumps(calls) + caplog.text
    assert "private-path" not in caplog.text


@pytest.mark.parametrize(
    "mode,status", [("timeout", "timeout"), ("http", "http_error"), ("body", "invalid_response")]
)
def test_failures_count_and_do_not_log_exception_text(monkeypatch, caplog, mode, status):
    def post(*args, **kwargs):
        if mode == "timeout":
            raise httpx.ReadTimeout("PRIVATE_ERROR")
        return response({"error": "PRIVATE_ERROR"}, 503 if mode == "http" else 200)

    monkeypatch.setattr(ai.httpx, "post", post)
    caplog.set_level(logging.INFO, logger="luna_realms.ai_calls")
    with capture_calls(max_calls=1) as calls:
        with pytest.raises((httpx.HTTPError, ValueError)):
            ai._chat(PROVIDER, MESSAGES)
        with pytest.raises(ValueError, match="budget_exhausted"):
            ai._chat(PROVIDER, MESSAGES)
    assert len(calls) == 1 and calls[0]["status"] == status
    assert calls[0]["input_tokens"] is None
    assert "PRIVATE" not in json.dumps(calls) + caplog.text


def test_nested_capture_cannot_bypass_parent_limit(monkeypatch):
    sent = []

    def post(*args, **kwargs):
        sent.append(True)
        return response({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(ai.httpx, "post", post)
    with capture_calls(max_calls=1) as outer:
        with capture_calls(max_calls=2) as inner:
            ai._chat(PROVIDER, MESSAGES)
            with pytest.raises(ValueError, match="budget_exhausted"):
                ai._chat(PROVIDER, MESSAGES)
        assert len(outer) == len(inner) == 1
    ai._chat(PROVIDER, MESSAGES)
    assert len(sent) == 2


def test_concurrent_captures_are_isolated(monkeypatch):
    monkeypatch.setattr(
        ai.httpx, "post", lambda *a, **k: response({"choices": [{"message": {"content": "ok"}}]})
    )

    def job():
        with capture_calls(max_calls=1) as calls:
            ai._chat(PROVIDER, MESSAGES)
            return calls

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: job(), range(2)))
    assert all(len(calls) == 1 for calls in results)
    assert results[0][0] is not results[1][0]


def test_zero_budget_never_sends_http(monkeypatch):
    def unexpected(*a, **k):
        raise AssertionError("HTTP forbidden")

    monkeypatch.setattr(ai.httpx, "post", unexpected)
    with capture_calls(max_calls=0) as calls:
        with pytest.raises(ValueError, match="budget_exhausted"):
            ai._chat(PROVIDER, MESSAGES)
    assert calls == []


def test_invalid_usage_is_unknown_not_zero(monkeypatch):
    monkeypatch.setattr(
        ai.httpx,
        "post",
        lambda *a, **k: response(
            {
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": True, "completion_tokens": -1},
            }
        ),
    )
    with capture_calls() as calls:
        ai._chat(PROVIDER, MESSAGES)
    assert calls[0]["input_tokens"] is None and calls[0]["output_tokens"] is None
