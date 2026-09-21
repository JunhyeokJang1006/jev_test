import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event

import pytest

from app import api
from app.dice import Dice
from app.storage import connect

from .helpers import request


def fail(*args):
    raise RuntimeError("narrator unavailable")


def create_failed(monkeypatch):
    campaign = request("POST", "/api/campaign", json={}).json()
    monkeypatch.setattr(api, "with_narration", fail)
    payload = {
        "campaign_id": campaign["id"],
        "expected_state_version": 0,
        "input": "문 옆에 숨는다",
        "request_id": "00000000-0000-4000-8000-000000000051",
    }
    turn = request("POST", "/api/game/turn", json=payload).json()
    assert turn["narrative_status"] == "failed"
    return campaign, turn, payload


def url(campaign, turn):
    return f"/api/campaign/{campaign['id']}/turn/{turn['turn_id']}/narration"


def mechanics():
    db = connect()
    try:
        return {
            table: [tuple(row) for row in db.execute(f"SELECT * FROM {table}")]
            for table in ("campaigns", "events", "snapshots")
        }
    finally:
        db.close()


def edit_outcome(turn, transform):
    db = connect()
    try:
        row = db.execute(
            "SELECT outcome_json FROM turns WHERE id = ?", (turn["turn_id"],)
        ).fetchone()
        outcome = json.loads(row["outcome_json"])
        transform(outcome)
        db.execute(
            "UPDATE turns SET outcome_json = ? WHERE id = ?",
            (json.dumps(outcome, ensure_ascii=False), turn["turn_id"]),
        )
    finally:
        db.close()


def test_failed_recovery_uses_saved_turn_and_preserves_mechanics(monkeypatch):
    campaign, turn, payload = create_failed(monkeypatch)
    # 최신 상태가 달라져도 이전 턴의 당시 결과를 사용한다.
    request(
        "POST",
        "/api/game/turn",
        json={"campaign_id": campaign["id"], "expected_state_version": 1, "input": "주위를 본다"},
    )
    before = mechanics()
    observed = []

    def narrator(text, resolved, provider):
        observed.append((text, resolved.narrative, resolved.state["time"]))
        db = connect()
        try:
            db.execute("BEGIN IMMEDIATE")  # 모델 호출 중 writer lock을 잡지 않는다.
            db.rollback()
        finally:
            db.close()
        resolved.state["player"]["hp"] = 0  # 공급자 변경도 권위 상태에 반영하지 않는다.
        return replace(resolved, narrative="복구된 서사"), "mock"

    monkeypatch.setattr(api, "with_narration", narrator)
    monkeypatch.setattr(api, "interpret_action", fail)
    monkeypatch.setattr(api, "resolve_action", fail)
    monkeypatch.setattr(Dice, "roll", fail)
    response = request("POST", url(campaign, turn))
    assert response.status_code == 200
    recovered = response.json()
    assert recovered["narrative_status"] == "completed"
    assert recovered["narrative"] == "복구된 서사"
    assert observed == [(payload["input"], turn["narrative"], turn["state"]["time"])]
    for field in ("event", "state", "dice", "state_version", "actions", "turn_id"):
        assert recovered[field] == turn[field]
    assert mechanics() == before
    assert request("POST", url(campaign, turn)).json() == recovered
    assert len(observed) == 1
    assert request("POST", "/api/game/turn", json=payload).json() == recovered
    current = request("GET", f"/api/campaign/{campaign['id']}").json()
    assert current["state_version"] == 2
    assert current["latest_turn"]["turn_id"] != turn["turn_id"]
    for public in (recovered, current["latest_turn"]):
        assert not {"narration_input", "authoritative_narrative", "narration_lease"} & public.keys()


@pytest.mark.parametrize("status", ["pending", "failed"])
def test_legacy_recovery_uses_safe_baseline(monkeypatch, status):
    campaign, turn, _ = create_failed(monkeypatch)

    def legacy(outcome):
        for field in ("narration_input", "authoritative_narrative", "narration_lease"):
            outcome.pop(field, None)
        outcome["narrative_status"] = status

    edit_outcome(turn, legacy)
    observed = []

    def narrator(text, resolved, provider):
        observed.append((text, resolved.narrative))
        return resolved, "mock"

    monkeypatch.setattr(api, "with_narration", narrator)
    assert request("POST", url(campaign, turn)).json()["narrative_status"] == "completed"
    assert observed == [("", turn["narrative"])]


def test_failed_retry_can_retry_again_and_wrong_campaign_is_not_found(monkeypatch):
    campaign, turn, _ = create_failed(monkeypatch)
    other = request("POST", "/api/campaign", json={}).json()
    assert request("POST", url(other, turn)).status_code == 404
    assert request("POST", url(campaign, {"turn_id": "missing"})).status_code == 404
    for _ in range(2):
        response = request("POST", url(campaign, turn))
        assert response.status_code == 200
        assert response.json()["narrative_status"] == "failed"
        assert response.json()["narrative"] == turn["narrative"]


@pytest.mark.parametrize("status", ["unknown", None])
def test_unknown_status_is_not_rewritten_or_narrated(monkeypatch, status):
    campaign, turn, _ = create_failed(monkeypatch)
    edit_outcome(turn, lambda outcome: outcome.update(narrative_status=status))
    before = mechanics()
    calls = []

    def narrator(*args):
        calls.append(args)
        raise AssertionError("unknown status must not narrate")

    monkeypatch.setattr(api, "with_narration", narrator)
    response = request("POST", url(campaign, turn))
    assert response.status_code == 409
    assert response.json()["detail"] == "narration_status_not_recoverable"
    assert calls == []
    assert mechanics() == before
    current = request("GET", f"/api/campaign/{campaign['id']}").json()["latest_turn"]
    assert current["narrative_status"] == status


def test_concurrent_retries_have_one_owner(monkeypatch):
    campaign, turn, _ = create_failed(monkeypatch)
    entered, resume = Event(), Event()
    calls = []

    def narrator(text, resolved, provider):
        calls.append(text)
        entered.set()
        assert resume.wait(5)
        return resolved, "mock"

    monkeypatch.setattr(api, "with_narration", narrator)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(request, "POST", url(campaign, turn))
        try:
            assert entered.wait(5)
            second = request("POST", url(campaign, turn))
            assert second.status_code == 409
            assert second.json()["detail"] == "narration_in_progress"
        finally:
            resume.set()
        assert first.result(5).json()["narrative_status"] == "completed"
    assert len(calls) == 1


def test_expired_original_lease_can_recover_and_late_original_cannot_overwrite(monkeypatch):
    campaign = request("POST", "/api/campaign", json={}).json()
    entered, resume = Event(), Event()
    calls = []

    def narrator(text, resolved, provider):
        calls.append(text)
        if len(calls) == 1:
            entered.set()
            assert resume.wait(5)
            return replace(resolved, narrative="늦은 원본"), "mock"
        return replace(resolved, narrative="복구 결과"), "mock"

    monkeypatch.setattr(api, "with_narration", narrator)
    with ThreadPoolExecutor(max_workers=1) as pool:
        original = pool.submit(
            request,
            "POST",
            "/api/game/turn",
            json={"campaign_id": campaign["id"], "expected_state_version": 0, "input": "숨는다"},
        )
        try:
            assert entered.wait(5)
            turn = request("GET", f"/api/campaign/{campaign['id']}").json()["latest_turn"]
            before = mechanics()
            assert request("POST", url(campaign, turn)).status_code == 409
            edit_outcome(turn, lambda outcome: outcome["narration_lease"].update(expires_at=0))
            recovered = request("POST", url(campaign, turn))
            assert recovered.json()["narrative"] == "복구 결과"
        finally:
            resume.set()
        assert original.result(5).json() == recovered.json()
    assert mechanics() == before
    assert request("POST", url(campaign, turn)).json() == recovered.json()


def test_narration_save_failure_preserves_pending_for_expiry_recovery(monkeypatch):
    campaign = request("POST", "/api/campaign", json={}).json()
    real_connect = api.connect

    class FailingSave:
        def __init__(self):
            self.db = real_connect()

        def __getattr__(self, key):
            return getattr(self.db, key)

        def execute(self, sql, *args):
            if sql.startswith("UPDATE turns SET outcome_json"):
                raise sqlite3.OperationalError("test save failure")
            return self.db.execute(sql, *args)

    monkeypatch.setattr(api, "connect", FailingSave)
    payload = {
        "campaign_id": campaign["id"],
        "expected_state_version": 0,
        "input": "숨는다",
        "request_id": "00000000-0000-4000-8000-000000000052",
    }
    response = request("POST", "/api/game/turn", json=payload)
    assert response.status_code == 200
    assert response.json()["narrative_status"] == "pending"
    assert request("POST", "/api/game/turn", json=payload).json() == response.json()
    monkeypatch.setattr(api, "connect", real_connect)
    edit_outcome(response.json(), lambda outcome: outcome["narration_lease"].update(expires_at=0))
    assert request("POST", url(campaign, response.json())).json()["narrative_status"] == "completed"
