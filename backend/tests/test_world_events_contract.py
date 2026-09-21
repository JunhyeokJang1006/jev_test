"""실제 API 모험 뒤 지연 세계 사건의 원자성·정보 경계 검증."""

import json
from copy import deepcopy
from uuid import uuid4

import pytest

from app import ai
from app.context import scene_context
from app.projection import public_payload

from .helpers import request
from .test_expedition_contract import act, at_tower
from .test_world import internal_state, turn


def reported(choice="rescue"):
    campaign = at_tower()
    act(
        campaign,
        {
            "rescue": "전령 구조 우선 확정 (문서 포기, 5분)",
            "documents": "문서 확보 우선 확정 (전령 구조 포기, 5분)",
            "both": "로프로 전령과 문서 모두 확보 확정 (5분)",
        }[choice],
    )
    for label in ["동쪽 성문으로 이동", "시장으로 이동", "오렌에게 망루 결과 보고 (25골드)"]:
        act(campaign, label)
    return campaign


@pytest.mark.parametrize(
    "choice,support",
    [
        ("documents", "보급 수송 호위 요청 (10분)"),
        ("rescue", "보급 수송 자금 지원 (8골드, 10분)"),
        ("rescue", "보급 수송 자원봉사 (30분)"),
        ("both", None),
    ],
)
def test_api_support_and_due_tick_survive_replay_restore(choice, support):
    campaign = reported(choice)
    state = campaign["state"]
    assert state["world_events"][0]["status"] == "pending"
    assert state["world_events"][0]["due_at"] == state["elapsed_minutes"] + 60
    assert len(state["factions"]) == 3
    assert state["progression"]["xp"] == 250
    if support:
        gold = state["resources"]["gold"]
        envelope = {
            "campaign_id": campaign["id"],
            "expected_state_version": campaign["state_version"],
            "request_id": str(uuid4()),
            "input": support,
        }
        response = request("POST", "/api/game/turn", json=envelope)
        assert response.status_code == 200, response.text
        assert request("POST", "/api/game/turn", json=envelope).json() == response.json()
        campaign.update(response.json())
        assert campaign["state"]["resources"]["gold"] == gold - (8 if "자금" in support else 0)
        assert turn(campaign, support).status_code == 422
    saved = request("POST", f"/api/campaign/{campaign['id']}/save").json()
    restored = request(
        "POST", f"/api/campaign/{campaign['id']}/load", json={"snapshot_id": saved["snapshot_id"]}
    ).json()
    assert restored["state"] == campaign["state"]
    campaign = restored
    for _ in range(6):
        if campaign["state"]["world_events"][0]["status"] != "pending":
            break
        envelope = {
            "campaign_id": campaign["id"],
            "expected_state_version": campaign["state_version"],
            "request_id": str(uuid4()),
            "input": "세계 사건 기다리기 (10분)",
        }
        response = request("POST", "/api/game/turn", json=envelope)
        assert response.status_code == 200, response.text
        assert request("POST", "/api/game/turn", json=envelope).json() == response.json()
        campaign.update(response.json())
    assert campaign["state"]["world_events"][0]["outcome"] == "arrived"
    assert campaign["state"]["market_policy"] == "relief"
    assert campaign["state"]["progression"]["xp"] == 250
    assert len(campaign["state"]["world_events"]) == 2
    assert "world_events" in campaign["event"]["payload"]
    assert "치유 물약 구매 (6골드)" in campaign["actions"]
    assert {c["label"] for c in scene_context(campaign["state"])["available_commands"]} == set(
        campaign["actions"]
    )


def test_ignored_convoy_delays_then_factions_recover_and_only_contacted_npc_learns():
    campaign = reported("rescue")
    original = deepcopy(campaign["state"]["expedition"])
    for _ in range(6):
        act(campaign, "세계 사건 기다리기 (10분)")
    assert campaign["state"]["market_policy"] == "shortage"
    assert campaign["state"]["world_events"][0]["outcome"] == "delayed"
    before = internal_state(campaign["id"])
    assert all(
        "public_world_event" not in ledger["facts"] for ledger in before["npc_knowledge"].values()
    )
    act(campaign, "오렌과 대화")
    known = internal_state(campaign["id"])
    for npc, ledger in known["npc_knowledge"].items():
        assert ("public_world_event" in ledger["facts"]) == (npc == "npc_oren")
    assert turn(campaign, "보급 수송 자원봉사 (30분)").status_code == 422
    assert turn(campaign, "치유 물약 구매 (6골드)").status_code == 422
    for _ in range(6):
        act(campaign, "세계 사건 기다리기 (10분)")
    assert campaign["state"]["market_policy"] == "caravan"
    assert all(event["status"] == "resolved" for event in campaign["state"]["world_events"])
    assert campaign["state"]["expedition"] == original
    assert "세계 사건 기다리기 (10분)" not in campaign["actions"]
    finished = deepcopy(campaign["state"])
    act(campaign, "오렌과 대화")
    assert campaign["state"]["factions"] == finished["factions"]
    assert campaign["state"]["world_events"] == finished["world_events"]


def test_rest_crosses_both_deadlines_once_without_retroactive_support():
    campaign = reported("rescue")
    act(campaign, "여관으로 이동")
    before = deepcopy(campaign["state"])
    envelope = {
        "campaign_id": campaign["id"],
        "expected_state_version": campaign["state_version"],
        "request_id": str(uuid4()),
        "input": "여관에서 긴 휴식",
    }
    response = request("POST", "/api/game/turn", json=envelope)
    assert response.status_code == 200, response.text
    assert request("POST", "/api/game/turn", json=envelope).json() == response.json()
    state = response.json()["state"]
    assert state["elapsed_minutes"] == before["elapsed_minutes"] + 480
    assert [event["outcome"] for event in state["world_events"]] == ["delayed", "recovered"]
    assert state["resources"]["camp_supplies"] == before["resources"]["camp_supplies"] - 1
    assert state["factions"]["guards"]["stock"] == before["factions"]["guards"]["stock"] - 1
    assert state["expedition"] == before["expedition"]
    changes = response.json()["event"]["payload"]["world_events"]
    assert [(event["id"], event["phase"]) for event in changes] == [
        ("supply_convoy", "resolved"),
        ("market_settlement", "scheduled"),
        ("market_settlement", "resolved"),
    ]
    fetched = request("GET", f"/api/campaign/{campaign['id']}").json()
    assert fetched["state"] == state
    assert all(
        "public_world_event" not in npc["facts"]
        for npc in internal_state(campaign["id"])["npc_knowledge"].values()
    )


@pytest.mark.parametrize("late", [False, True])
def test_interpreter_support_is_scoped_to_current_event_and_deadline(monkeypatch, late):
    campaign = reported("rescue")
    if late:
        for _ in range(4):
            act(campaign, "세계 사건 기다리기 (10분)")
    state = campaign["state"]
    monkeypatch.setattr(ai, "_provider_config", lambda: [("stub", "", "", "")])

    def chat(provider, messages, **kwargs):
        scene = json.loads(messages[-1]["content"])["scene"]
        assert scene["world_events"][0]["choice"] == "rescue"
        assert len(scene["factions"]) == 3
        assert any(
            command["intent"] == "support_convoy" and command["target_id"] == "volunteers"
            for command in scene["available_commands"]
        ) == (not late)
        return "stub", json.dumps(
            {"intent": "support_convoy", "action_type": "exploration", "target_ids": ["volunteers"]}
        )

    monkeypatch.setattr(ai, "_chat", chat)
    original = deepcopy(state)
    proposal, provider = ai.interpret_action("돈 대신 내 시간을 써서 수송 준비를 돕겠다", state)
    assert proposal.intent == ("describe_action" if late else "support_convoy")
    assert provider == ("mock" if late else "stub")
    assert state == original


def test_event_payload_projects_only_registered_summaries():
    payload = {
        "world_events": [
            {"id": "supply_convoy", "phase": "resolved", "text": "공개 결과", "private": "SECRET"},
            {"id": [], "phase": "resolved", "text": "SECRET"},
            {"id": "supply_convoy", "phase": [], "text": "SECRET"},
            {"id": "private_event", "phase": "resolved", "text": "SECRET"},
            None,
        ]
    }
    assert public_payload(payload) == {
        "world_events": [{"id": "supply_convoy", "phase": "resolved", "text": "공개 결과"}]
    }
