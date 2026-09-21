"""Content-free provider metrics and scoped HTTP attempt budgets."""

import json
import logging
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from threading import Lock
from time import perf_counter

import httpx

logger = logging.getLogger("luna_realms.ai_calls")


@dataclass
class Capture:
    max_calls: int | None
    calls: list[dict] = field(default_factory=list)


_captures: ContextVar[tuple[Capture, ...]] = ContextVar("ai_captures", default=())
_lock = Lock()


@contextmanager
def capture_calls(max_calls: int | None = None):
    if max_calls is not None and (type(max_calls) is not int or max_calls < 0):
        raise ValueError("invalid_call_budget")
    capture = Capture(max_calls)
    token = _captures.set((*_captures.get(), capture))
    try:
        yield capture.calls
    finally:
        _captures.reset(token)


@contextmanager
def tracked_call(provider: str, model: str, *, json_mode: bool):
    # Never collect keys, URLs, prompts, response text, request IDs or error messages.
    record = {
        "call_type": "interpreter" if json_mode else "narrator",
        "provider": provider if provider in {"luna", "deepseek"} else "other",
        "model": model
        if re.fullmatch(r"(?:gpt-|deepseek-)[a-zA-Z0-9._-]{1,80}", model)
        else "other",
        "status": "pending",
        "latency_ms": 0.0,
        "input_tokens": None,
        "output_tokens": None,
    }
    captures = _captures.get()
    with _lock:
        if any(c.max_calls is not None and len(c.calls) >= c.max_calls for c in captures):
            raise ValueError("ai_call_budget_exhausted")
        for capture in captures:
            capture.calls.append(record)
    started = perf_counter()
    try:
        yield record
        record["status"] = "ok"
    except httpx.TimeoutException:
        record["status"] = "timeout"
        raise
    except httpx.HTTPError:
        record["status"] = "http_error"
        raise
    except Exception:
        record["status"] = "invalid_response"
        raise
    finally:
        record["latency_ms"] = round(max(0, perf_counter() - started) * 1000, 3)
        logger.info("ai_call %s", json.dumps(record, ensure_ascii=True))


def add_usage(record: dict, body: dict) -> None:
    usage = body.get("usage")
    if not isinstance(usage, dict):
        return
    for source, target in (
        ("prompt_tokens", "input_tokens"),
        ("completion_tokens", "output_tokens"),
    ):
        value = usage.get(source)
        record[target] = value if type(value) is int and value >= 0 else None
