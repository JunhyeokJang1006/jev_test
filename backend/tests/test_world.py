import json

import pytest

from app import ai, api
from app.game import ActionProposal
from app.storage import connect, read_campaign

from .helpers import request


def internal_state(campaign_id):
    connection = connect()
    try:
        return read_campaign(connection, campaign_id)["state"]
    finally:
        connection.close()


@pytest.fixture
def campaign(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "world.db"))
    monkeypatch.setenv("GM_PROVIDER", "mock")
    monkeypatch.setenv("JEV_ENABLED", "false")
    return request("POST", "/api/campaign", json={}).json()


def turn(campaign, action, **extra):
    response = request(
        "POST",
        "/api/game/turn",
        json={
            "campaign_id": campaign["id"],
            "expected_state_version": campaign["state_version"],
            "input": action,
            **extra,
        },
    )
    if response.status_code == 200:
        campaign.update(response.json())
    return response


def recover(campaign):
    for action in [
        "하를란과 대화",
        "미라와 대화",
        "시장으로 이동",
        "오렌과 대화",
        "창고로 이동",
        "주변 조사",
        "봉인 회수",
    ]:
        assert turn(campaign, action).status_code == 200


@pytest.mark.parametrize(
    "ending,action",
    [
        ("law", "하를란에게 봉인 반환"),
        ("mercy", "미라에게 봉인 전달"),
        ("exile", "봉인을 가지고 도시 떠나기"),
    ],
)
def test_complete_each_ending_and_restore_before_choice(campaign, ending, action):
    recover(campaign)
    assert campaign["state"]["inventory"] == ["royal_seal"]
    assert campaign["ai"] == {"interpreter": "engine", "narrator": "engine"}
    saved = request("POST", f"/api/campaign/{campaign['id']}/save").json()
    assert turn(campaign, "시장으로 이동").status_code == 200
    if ending != "exile":
        assert turn(campaign, "여관으로 이동").status_code == 200
    preview = turn(campaign, action)
    assert preview.status_code == 409
    assert preview.json()["detail"]["code"] == "ending_confirmation_required"
    assert turn(campaign, action, confirmed_ending=ending).status_code == 200
    assert campaign["state"]["quest"]["ending"] == ending
    assert campaign["state"]["quest"]["status"] == "completed"
    assert campaign["actions"] == ["후속 사건 시작"]
    assert turn(campaign, "주변 조사").status_code == 422
    restored = request(
        "POST", f"/api/campaign/{campaign['id']}/load", json={"snapshot_id": saved["snapshot_id"]}
    ).json()
    assert restored["state"]["quest"]["ending"] is None
    assert restored["state"]["inventory"] == ["royal_seal"]
    assert "npc_memories" not in restored["state"]
    assert internal_state(restored["id"])["npc_memories"]["npc_oren"] == ["seal_discussed"]
    assert len(restored["state"]["journal"]) == 7


@pytest.mark.parametrize(
    "action",
    ["창고로 이동", "오렌과 대화", "봉인 회수", "하를란에게 봉인 반환", "미라에게 봉인 전달"],
)
def test_cannot_skip_location_or_quest_conditions(campaign, action):
    before = campaign["state"]
    assert turn(campaign, action).status_code == 422
    fetched = request("GET", f"/api/campaign/{campaign['id']}").json()
    assert fetched["state_version"] == 0
    assert fetched["state"] == before


def test_clues_must_be_discovered_and_cannot_duplicate_seal(campaign):
    assert "seal_cache" not in campaign["state"]["quest"]["clues"]
    for action in ["시장으로 이동", "창고로 이동", "주변 조사"]:
        assert turn(campaign, action).status_code == 200
    assert "seal_cache" not in campaign["state"]["quest"]["clues"]
    assert turn(campaign, "봉인 회수").status_code == 422
    for action in ["시장으로 이동", "주변 조사", "창고로 이동", "주변 조사", "봉인 회수"]:
        assert turn(campaign, action).status_code == 200
    assert turn(campaign, "봉인 회수").status_code == 422
    assert campaign["state"]["inventory"].count("royal_seal") == 1


def test_repeated_dialogue_remembers_and_clock_advances(campaign):
    assert turn(campaign, "하를란과 대화").status_code == 200
    assert turn(campaign, "시장으로 이동").status_code == 200
    assert turn(campaign, "여관으로 이동").status_code == 200
    assert turn(campaign, "하를란과 대화").status_code == 200
    assert "기억" in campaign["narrative"]
    assert "npc_memories" not in campaign["state"]
    assert internal_state(campaign["id"])["npc_memories"]["npc_harlan"] == ["seal_discussed"]
    assert campaign["state"]["time"] == "21:48"
    assert campaign["state"]["npcs"][0]["disposition"] == "suspicious"


def test_free_language_interpreter_commits_world_transition(campaign, monkeypatch):
    monkeypatch.setattr(ai, "_provider_config", lambda: [("luna", "", "", "")])

    def chat(provider, messages, *, json_mode=False):
        body = json.loads(messages[-1]["content"])
        if json_mode:
            assert body["scene"]["location"]["id"] == "greyhaven_inn"
            assert body["player_input"] == "시장 쪽으로 걸어갈게요"
            return "luna", '{"intent":"travel","action_type":"exploration","target_ids":["market"]}'
        return "luna", body["authoritative_narrative"]

    monkeypatch.setattr(ai, "_chat", chat)
    response = turn(campaign, "시장 쪽으로 걸어갈게요")
    assert response.status_code == 200
    assert campaign["state"]["location_id"] == "market"
    assert campaign["ai"] == {"interpreter": "luna", "narrator": "luna"}
    fetched = request("GET", f"/api/campaign/{campaign['id']}").json()
    assert fetched["state"]["location_id"] == "market"
    assert "오렌과 대화" in fetched["actions"]


def test_model_cannot_end_quest_without_player_confirmation(campaign, monkeypatch):
    recover(campaign)
    turn(campaign, "시장으로 이동")
    before = request("GET", f"/api/campaign/{campaign['id']}").json()
    connection = connect()
    count = connection.execute("SELECT COUNT(*) FROM turns").fetchone()[0]
    connection.close()
    monkeypatch.setattr(
        api,
        "interpret_action",
        lambda *_: (ActionProposal("finish_quest", "exploration", ("exile",), None, None), "luna"),
    )
    for _ in range(2):
        preview = turn(campaign, "도시를 떠나는 게 좋을지 고민만 한다")
        assert preview.status_code == 409
        assert preview.json()["detail"]["ending"] == "exile"
    assert request("GET", f"/api/campaign/{campaign['id']}").json() == before
    connection = connect()
    assert connection.execute("SELECT COUNT(*) FROM turns").fetchone()[0] == count
    connection.close()


def test_ending_confirmation_is_bound_to_command_version_and_request(campaign):
    recover(campaign)
    turn(campaign, "시장으로 이동")
    preview_version = campaign["state_version"]
    assert turn(campaign, "봉인을 가지고 도시 떠나기").status_code == 409
    assert turn(campaign, "주변 조사", confirmed_ending="exile").status_code == 422
    assert turn(campaign, "봉인을 가지고 도시 떠나기", confirmed_ending="law").status_code == 422
    turn(campaign, "주변 조사")
    payload = {
        "campaign_id": campaign["id"],
        "request_id": "00000000-0000-4000-8000-000000000099",
        "input": "봉인을 가지고 도시 떠나기",
        "confirmed_ending": "exile",
        "expected_state_version": preview_version,
    }
    assert request("POST", "/api/game/turn", json=payload).status_code == 409
    payload["expected_state_version"] = campaign["state_version"]
    first = request("POST", "/api/game/turn", json=payload)
    assert first.status_code == 200
    assert first.json()["state"]["quest"]["ending"] == "exile"
    assert request("POST", "/api/game/turn", json=payload).json() == first.json()
    del payload["confirmed_ending"]
    assert request("POST", "/api/game/turn", json=payload).status_code == 409
