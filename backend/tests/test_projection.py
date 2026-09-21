import json

from app import ai
from app.game import TurnOutcome
from app.projection import public_state, public_turn
from app.storage import connect

from .helpers import request


def test_narrator_does_not_receive_internal_event_fields(monkeypatch):
    monkeypatch.setattr(ai, "_provider_config", lambda: [("luna", "", "", "")])

    def chat(provider, messages):
        assert "PRIVATE_SENTINEL" not in json.dumps(messages)
        body = json.loads(messages[-1]["content"])
        assert body["outcome"]["damage"] == 3
        return "luna", "공격이 명중했다."

    monkeypatch.setattr(ai, "_chat", chat)
    outcome = TurnOutcome(
        "TEST", {"damage": 3, "gm_only": "PRIVATE_SENTINEL"}, {}, "공격이 명중했다.", {}
    )
    assert ai.narrate_outcome("공격", outcome, "luna")[1] == "luna"


def test_nested_private_fields_are_not_returned():
    state = {
        "secret": "PRIVATE",
        "npc_memories": {"x": "PRIVATE"},
        "player": {"hp": 3, "secret": "PRIVATE"},
        "quest": {"status": "active", "hidden_truth": "PRIVATE", "clues": ["known"]},
        "npcs": [{"id": "npc_harlan", "knowledge": "PRIVATE"}],
        "journal": [{"text": "known", "hidden": "PRIVATE"}],
        "inventory": ["known", {"secret": "PRIVATE"}],
        "combat": {"enemy_hp": 7, "secret_plan": "PRIVATE"},
    }
    projected = public_state(state)
    assert "PRIVATE" not in json.dumps(projected)
    assert projected["player"]["hp"] == 3
    assert projected["inventory"] == ["known"]
    turn = public_turn(
        {
            "state": state,
            "internal_trace": "PRIVATE",
            "event": {
                "type": "TEST",
                "payload": {
                    "secret": "PRIVATE",
                    "enemy_attack": {"damage": 2, "secret": "PRIVATE"},
                },
            },
            "ai": {"interpreter": "luna", "key": "PRIVATE"},
        }
    )
    assert "PRIVATE" not in json.dumps(turn)
    assert turn["event"]["payload"]["enemy_attack"]["damage"] == 2


def test_private_state_survives_save_but_never_leaks_on_api_replay(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "private.db"))
    monkeypatch.setenv("GM_PROVIDER", "mock")
    monkeypatch.setenv("JEV_ENABLED", "false")
    campaign = request("POST", "/api/campaign", json={}).json()
    cid = campaign["id"]
    connection = connect()
    try:
        row = connection.execute("SELECT state_json FROM campaigns WHERE id=?", (cid,)).fetchone()
        state = json.loads(row[0])
        state["hidden_truth"] = "PRIVATE_SENTINEL"
        state["npcs"][0]["private_knowledge"] = "PRIVATE_SENTINEL"
        connection.execute("UPDATE campaigns SET state_json=? WHERE id=?", (json.dumps(state), cid))
    finally:
        connection.close()
    payload = {
        "campaign_id": cid,
        "expected_state_version": 0,
        "input": "주변 조사",
        "request_id": "00000000-0000-4000-8000-000000000040",
    }
    first = request("POST", "/api/game/turn", json=payload)
    assert first.status_code == 200
    replay = request("POST", "/api/game/turn", json=payload)
    assert replay.json() == first.json()
    fetched = request("GET", f"/api/campaign/{cid}")
    saved = request("POST", f"/api/campaign/{cid}/save").json()
    restored = request(
        "POST", f"/api/campaign/{cid}/load", json={"snapshot_id": saved["snapshot_id"]}
    )
    for response in [first, replay, fetched, restored]:
        assert response.status_code in (200, 201)
        assert "PRIVATE_SENTINEL" not in response.text
        assert "npc_memories" not in response.json()["state"]
    connection = connect()
    try:
        row = connection.execute(
            "SELECT state_json FROM campaigns WHERE id=?", (restored.json()["id"],)
        ).fetchone()
        assert json.loads(row[0])["hidden_truth"] == "PRIVATE_SENTINEL"
    finally:
        connection.close()
