import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from app import api
from app.dice import Dice
from app.storage import connect

from .helpers import request


@pytest.fixture(autouse=True)
def isolated_database(monkeypatch):
    monkeypatch.setenv("GM_PROVIDER", "mock")
    monkeypatch.setenv("JEV_ENABLED", "false")
    monkeypatch.setattr(Dice, "roll", lambda self, sides: 11 if sides == 20 else 3)
    with tempfile.TemporaryDirectory() as directory:
        monkeypatch.setenv("DATABASE_PATH", str(Path(directory) / "test.db"))
        yield


def test_stealth_turn_commits_state_and_is_idempotent():
    campaign = request("POST", "/api/campaign", json={"name": "테스트 캠페인"}).json()
    payload = {
        "campaign_id": campaign["id"],
        "request_id": "00000000-0000-4000-8000-000000000001",
        "expected_state_version": 0,
        "input": "문 옆 그림자에 숨어 기다린다",
    }
    first = request("POST", "/api/game/turn", json=payload)
    assert first.status_code == 200
    assert first.json()["state"]["hidden"] is True
    assert first.json()["dice"]["total"] == 16
    second = request("POST", "/api/game/turn", json=payload)
    assert second.status_code == 200
    assert second.json() == first.json()
    assert request("GET", f"/api/campaign/{campaign['id']}").json()["state_version"] == 1


def test_stale_version_and_reused_request_id_are_rejected():
    campaign = request("POST", "/api/campaign", json={}).json()
    payload = {
        "campaign_id": campaign["id"],
        "request_id": "00000000-0000-4000-8000-000000000002",
        "expected_state_version": 0,
        "input": "숨는다",
    }
    assert request("POST", "/api/game/turn", json=payload).status_code == 200
    stale = {**payload, "request_id": "00000000-0000-4000-8000-000000000003"}
    assert request("POST", "/api/game/turn", json=stale).status_code == 409
    changed = {**payload, "input": "문을 연다"}
    assert request("POST", "/api/game/turn", json=changed).status_code == 409


def test_unknown_action_records_event_without_changing_mechanical_state():
    campaign = request("POST", "/api/campaign", json={}).json()
    response = request(
        "POST",
        "/api/game/turn",
        json={
            "campaign_id": campaign["id"],
            "expected_state_version": 0,
            "input": "여관 주인에게 인사한다",
        },
    )
    assert response.status_code == 200
    assert response.json()["state"]["hidden"] is False
    assert response.json()["event"]["type"] == "PLAYER_ACTION_RECORDED"


def test_save_and_load_creates_a_new_campaign_branch():
    campaign = request("POST", "/api/campaign", json={}).json()
    request(
        "POST",
        "/api/game/turn",
        json={"campaign_id": campaign["id"], "expected_state_version": 0, "input": "숨는다"},
    )
    saved = request("POST", f"/api/campaign/{campaign['id']}/save")
    assert saved.status_code == 201
    restored = request(
        "POST",
        f"/api/campaign/{campaign['id']}/load",
        json={"snapshot_id": saved.json()["snapshot_id"]},
    )
    assert restored.status_code == 201
    assert restored.json()["id"] != campaign["id"]
    assert restored.json()["state"]["hidden"] is True
    assert restored.json()["state_version"] == 0


def test_basic_attack_uses_engine_result_and_reduces_enemy_hp():
    campaign = request("POST", "/api/campaign", json={}).json()
    for version, action in enumerate(["전투 시작", "전투 이동: 오른쪽"]):
        response = request(
            "POST",
            "/api/game/turn",
            json={
                "campaign_id": campaign["id"],
                "expected_state_version": version,
                "input": action,
            },
        )
        assert response.status_code == 200
    response = request(
        "POST",
        "/api/game/turn",
        json={
            "campaign_id": campaign["id"],
            "expected_state_version": 2,
            "input": "고블린을 공격한다",
        },
    )
    assert response.status_code == 200
    assert response.json()["event"]["type"] == "PLAYER_ATTACKED"
    assert response.json()["state"]["combat"]["enemy_hp"] == 1


def test_attack_retry_does_not_roll_again(monkeypatch):
    campaign = request("POST", "/api/campaign", json={}).json()
    rolls = []

    def roll(self, sides):
        rolls.append(sides)
        return 11 if sides == 20 else 3

    monkeypatch.setattr(Dice, "roll", roll)
    payload = {
        "campaign_id": campaign["id"],
        "request_id": "00000000-0000-4000-8000-000000000030",
        "expected_state_version": 0,
        "input": "고블린을 공격한다",
    }
    first = request("POST", "/api/game/turn", json=payload)
    assert first.status_code == 200
    assert rolls == [20, 20]
    second = request("POST", "/api/game/turn", json=payload)
    assert second.json() == first.json()
    assert rolls == [20, 20]


@pytest.mark.parametrize("text", ["미라를 공격한다", "여관 주인을 공격한다", "경비대장을 찌른다"])
def test_unsupported_target_is_not_replaced_by_goblin(text, monkeypatch):
    campaign = request("POST", "/api/campaign", json={}).json()

    def unexpected_roll(*args):
        raise AssertionError("unresolved action must not roll dice")

    monkeypatch.setattr(Dice, "roll", unexpected_roll)
    response = request(
        "POST",
        "/api/game/turn",
        json={"campaign_id": campaign["id"], "expected_state_version": 0, "input": text},
    )
    assert response.status_code == 200
    assert response.json()["state"] == campaign["state"]
    assert response.json()["event"]["payload"]["resolved"] is False


def test_narration_runs_after_commit_and_failure_preserves_replay(monkeypatch):
    campaign = request("POST", "/api/campaign", json={}).json()
    payload = {
        "campaign_id": campaign["id"],
        "request_id": "00000000-0000-4000-8000-000000000010",
        "expected_state_version": 0,
        "input": "숨는다",
    }
    observed = []

    def failed_narration(*args):
        db = connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT state_version FROM campaigns WHERE id = ?", (campaign["id"],)
            ).fetchone()
            observed.append(row["state_version"])
            assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
            db.rollback()
        finally:
            db.close()
        raise RuntimeError("narrator unavailable")

    monkeypatch.setattr(api, "with_narration", failed_narration)
    response = request("POST", "/api/game/turn", json=payload)
    assert response.status_code == 200
    assert observed == [1]
    assert response.json()["narrative_status"] == "failed"
    assert response.json()["state"]["hidden"] is True
    assert request("POST", "/api/game/turn", json=payload).json() == response.json()
    assert observed == [1]


def test_rejected_action_returns_422_and_leaves_state_intact(monkeypatch):
    campaign = request("POST", "/api/campaign", json={}).json()

    def reject(*args):
        raise ValueError("invalid target")

    monkeypatch.setattr(api, "resolve_action", reject)
    response = request(
        "POST",
        "/api/game/turn",
        json={"campaign_id": campaign["id"], "expected_state_version": 0, "input": "숨는다"},
    )
    assert response.status_code == 422
    assert request("GET", f"/api/campaign/{campaign['id']}").json()["state_version"] == 0


@pytest.mark.parametrize("duplicate", [True, False])
def test_concurrent_interpretations_commit_only_one_turn(monkeypatch, duplicate):
    campaign = request("POST", "/api/campaign", json={}).json()
    barrier = Barrier(2)
    interpret = api.interpret_action

    def simultaneous_interpret(text, state=None):
        barrier.wait(timeout=5)
        return interpret(text, state)

    monkeypatch.setattr(api, "interpret_action", simultaneous_interpret)
    first = {
        "campaign_id": campaign["id"],
        "request_id": "00000000-0000-4000-8000-000000000020",
        "expected_state_version": 0,
        "input": "숨는다",
    }
    second = first if duplicate else {**first, "request_id": "00000000-0000-4000-8000-000000000021"}
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(request, "POST", "/api/game/turn", json=payload)
            for payload in (first, second)
        ]
        responses = [future.result(timeout=10) for future in futures]
    assert sorted(response.status_code for response in responses) == (
        [200, 200] if duplicate else [200, 409]
    )
    db = connect()
    try:
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM turns").fetchone()[0] == 1
    finally:
        db.close()
    assert request("GET", f"/api/campaign/{campaign['id']}").json()["state_version"] == 1
