import json
from copy import deepcopy

import pytest

from app import ai
from app.dice import Dice
from app.game import interpret_mock, resolve_action
from app.memory import actor_context, initialize_knowledge, record_episode
from app.projection import public_state
from app.storage import connect, read_campaign
from app.world import prepare

from .helpers import request
from .test_game import Rolls


@pytest.fixture
def state():
    return prepare(
        {
            "location_id": "greyhaven_inn",
            "location_name": "Greyhaven Inn",
            "day": 1,
            "time": "21:36",
            "player": {"hp": 31, "ac": 17},
            "npcs": [
                {"id": "npc_harlan", "name": "Harlan", "disposition": "suspicious"},
                {"id": "npc_mira", "name": "Mira", "disposition": "neutral"},
            ],
        }
    )


@pytest.mark.parametrize("roll,success,reaction", [(11, True, "believed"), (1, False, "doubted")])
def test_claim_is_not_truth_and_repeated_claim_does_not_reroll(state, roll, success, reaction):
    before = deepcopy(state)
    proposal = interpret_mock("시장님이 직접 저를 보냈습니다.")
    outcome = resolve_action(state, proposal, roller=Rolls(roll))
    assert state == before
    claim = outcome.state["npc_knowledge"]["npc_harlan"]["claims"]["mayor_sent_player"]
    assert claim["reaction"] == reaction
    assert claim["verified"] is False
    assert claim["source"] == "player_assertion"
    assert "mayor_sent_player" not in outcome.state["npc_knowledge"]["npc_harlan"]["facts"]
    assert outcome.event_payload["success"] is success
    repeated = resolve_action(outcome.state, proposal, roller=Rolls())
    assert repeated.event_type == "NPC_CLAIM_RECALLED"
    assert repeated.state == outcome.state
    assert "npc_knowledge" not in public_state(outcome.state)


def test_two_hours_later_npc_remembers_without_sharing_with_other_npcs(state):
    state = resolve_action(
        state, interpret_mock("시장님이 직접 저를 보냈습니다."), roller=Rolls(11)
    ).state
    for _ in range(12):
        state = resolve_action(state, interpret_mock("시장으로 이동")).state
        state = resolve_action(state, interpret_mock("여관으로 이동")).state
    outcome = resolve_action(state, interpret_mock("하를란과 대화"))
    assert outcome.state["elapsed_minutes"] >= 120
    assert "아직 확인하지 못했다" in outcome.narrative
    assert (
        actor_context(outcome.state, "npc_harlan")["remembered_claims"][0]["certainty"]
        == "unverified"
    )
    assert actor_context(outcome.state, "npc_mira")["remembered_claims"] == []
    assert actor_context(outcome.state, "npc_oren")["remembered_claims"] == []


def test_recent_episode_compaction_preserves_important_claim_and_private_facts(state):
    state = resolve_action(
        state, interpret_mock("시장님이 직접 저를 보냈습니다."), roller=Rolls(11)
    ).state
    initialize_knowledge(state)
    state["npc_knowledge"]["npc_harlan"]["facts"]["secret"] = {
        "text": "PRIVATE_SENTINEL",
        "source": "gm",
        "shareable": False,
    }
    for _ in range(100):
        record_episode(state, "npc_harlan", "visit")
    context = actor_context(state, "npc_harlan")
    assert len(state["npc_knowledge"]["npc_harlan"]["episodes"]) == 20
    assert len(context["recent_contacts"]) == 6
    assert context["remembered_claims"][0]["reaction"] == "believed"
    assert "PRIVATE_SENTINEL" not in json.dumps(context)


def test_actor_receives_only_speakers_knowledge(monkeypatch, state):
    outcome = resolve_action(state, interpret_mock("하를란과 대화"))
    assert (
        actor_context(outcome.state, "npc_harlan")["recent_contacts"][-1]["time"]
        == outcome.state["time"]
    )
    monkeypatch.setattr(ai, "_provider_config", lambda: [("luna", "", "", "")])

    def chat(provider, messages):
        payload = json.loads(messages[-1]["content"])
        assert payload["speaker"]["speaker_id"] == "npc_harlan"
        assert [fact["id"] for fact in payload["speaker"]["known_facts"]] == ["seal_stolen"]
        assert "crate_seen" not in json.dumps(payload["speaker"])
        return "luna", "Harlan: 봉인의 행방을 찾아주시오."

    monkeypatch.setattr(ai, "_chat", chat)
    assert ai.narrate_outcome("대장에게 봉인의 행방을 묻는다", outcome, "luna")[1] == "luna"


def test_claim_save_restore_and_replay_preserve_internal_knowledge(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "memory.db"))
    monkeypatch.setenv("GM_PROVIDER", "mock")
    monkeypatch.setenv("JEV_ENABLED", "false")
    monkeypatch.setattr(Dice, "roll", lambda self, sides: 11)
    campaign = request("POST", "/api/campaign", json={}).json()
    cid = campaign["id"]
    payload = {
        "campaign_id": cid,
        "expected_state_version": 0,
        "request_id": "00000000-0000-4000-8000-000000000050",
        "input": "시장님이 직접 저를 보냈습니다.",
    }
    response = request("POST", "/api/game/turn", json=payload)
    assert response.status_code == 200
    assert request("POST", "/api/game/turn", json=payload).json() == response.json()
    assert "npc_knowledge" not in response.json()["state"]
    snapshot = request("POST", f"/api/campaign/{cid}/save").json()
    restored = request(
        "POST", f"/api/campaign/{cid}/load", json={"snapshot_id": snapshot["snapshot_id"]}
    ).json()
    connection = connect()
    try:
        state = read_campaign(connection, restored["id"])["state"]
    finally:
        connection.close()
    assert actor_context(state, "npc_harlan")["remembered_claims"][0]["reaction"] == "believed"


def test_claim_rejected_when_npc_absent(state):
    state = resolve_action(state, interpret_mock("시장으로 이동")).state
    with pytest.raises(ValueError, match="하를란"):
        resolve_action(state, interpret_mock("시장님이 직접 저를 보냈습니다."), roller=Rolls())
