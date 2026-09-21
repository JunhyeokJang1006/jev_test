"""실제 API 모험 연쇄, 원정 저장/재송신과 정보 경계의 통합 회귀."""

import json

import pytest

from app import ai, api, expedition
from app.context import scene_context
from app.game import ActionProposal
from app.storage import connect, read_campaign

from .helpers import request


def act(campaign, text, **extra):
    response = request(
        "POST",
        "/api/game/turn",
        json={
            "campaign_id": campaign["id"],
            "expected_state_version": campaign["state_version"],
            "input": text,
            **extra,
        },
    )
    assert response.status_code == 200, response.text
    campaign.update(response.json())
    return response.json()


def at_tower(branch="law"):
    campaign = request("POST", "/api/campaign", json={}).json()
    for text in [
        "시장으로 이동",
        "오렌과 대화",
        "창고로 이동",
        "주변 조사",
        "봉인 회수",
        "시장으로 이동",
    ]:
        act(campaign, text)
    ending = {
        "law": "하를란에게 봉인 반환",
        "mercy": "미라에게 봉인 전달",
        "exile": "봉인을 가지고 도시 떠나기",
    }[branch]
    if branch != "exile":
        act(campaign, "여관으로 이동")
    act(campaign, ending, confirmed_ending=branch)
    act(campaign, "후속 사건 시작")
    if branch != "exile":
        act(campaign, "시장으로 이동")
    act(campaign, "오렌에게 안전한 피난로 확인" if branch == "exile" else "오렌의 통행세 증언 기록")
    act(campaign, "창고로 이동")
    act(campaign, "창고에서 피난 보급품 확보" if branch == "exile" else "창고의 통행세 장부 확보")
    act(campaign, "시장으로 이동")
    if branch == "law":
        act(campaign, "여관으로 이동")
    act(
        campaign,
        {
            "law": "하를란에게 감사 증거 제출",
            "mercy": "시장에서 통행세 증거 공개",
            "exile": "피난민과 함께 성문 통과",
        }[branch],
    )
    act(campaign, "성장: 설득의 기술")
    if branch == "law":
        act(campaign, "시장으로 이동")
    act(campaign, "꺼진 망루의 전령 의뢰 수락")
    act(
        campaign,
        {
            "law": "경비대 통행증 확보",
            "mercy": "상인 소개장 확보",
            "exile": "피난로 경험으로 길 준비",
        }[branch],
    )
    act(campaign, "야영 보급품 1개로 구조 로프 준비")
    act(campaign, "동쪽 성문으로 이동")
    act(
        campaign,
        "경비대 통행증으로 성문 통과" if branch == "law" else "성문 보수 작업을 돕고 통과 (20분)",
    )
    act(campaign, "망루로 이동")
    for text in [
        "망루에서 전령 위치 조사 (5분)",
        "망루에서 문서 위치 조사 (5분)",
        "망루 계단 보강 (10분)",
    ]:
        act(campaign, text)
    return campaign


@pytest.mark.parametrize("branch", ["law", "mercy", "exile"])
def test_expedition_follows_original_choice_and_persists_reward_once(branch):
    campaign = at_tower(branch)
    assert campaign["state"]["expedition"]["branch"] == branch
    snapshot = request("POST", f"/api/campaign/{campaign['id']}/save").json()
    choice = "로프로 전령과 문서 모두 확보 확정 (5분)"
    assert choice in campaign["actions"]
    act(campaign, choice)
    assert campaign["state"]["expedition"]["status"] == "resolved"
    for text in ["동쪽 성문으로 이동", "시장으로 이동"]:
        act(campaign, text)
    gold = campaign["state"]["resources"]["gold"]
    envelope = {
        "campaign_id": campaign["id"],
        "expected_state_version": campaign["state_version"],
        "request_id": "00000000-0000-4000-8000-000000000555",
        "input": "오렌에게 망루 결과 보고 (25골드)",
    }
    first = request("POST", "/api/game/turn", json=envelope)
    assert first.status_code == 200
    campaign.update(first.json())
    assert campaign["state"]["resources"]["gold"] == gold + 25
    assert campaign["state"]["progression"]["xp"] == 250
    assert campaign["state"]["quest"]["ending"] == branch
    assert campaign["state"]["followup"]["status"] == "completed"
    assert request("POST", "/api/game/turn", json=envelope).json() == first.json()
    act(campaign, "성장: 전투 숙련")
    assert campaign["state"]["progression"]["level"] == 5
    act(campaign, "오렌과 대화")
    assert "전령과 봉인 문서를 모두 구했다" in campaign["narrative"]
    db = connect()
    try:
        internal = read_campaign(db, campaign["id"])["state"]
    finally:
        db.close()
    assert "expedition_report" in internal["npc_knowledge"]["npc_oren"]["facts"]
    report = internal["npc_knowledge"]["npc_oren"]["facts"]["expedition_report"]
    assert report["certainty"] == "reported"
    assert report["source"] == "player_report"
    assert "현장을 직접 보지는 않았다" in report["text"]
    assert "expedition_report" not in internal["npc_knowledge"]["npc_harlan"]["facts"]
    assert "expedition_report" not in internal["npc_knowledge"]["npc_mira"]["facts"]
    assert "npc_knowledge" not in campaign["state"]
    assert scene_context(internal)["expedition"]["status"] == "completed"
    restored = request(
        "POST",
        f"/api/campaign/{campaign['id']}/load",
        json={"snapshot_id": snapshot["snapshot_id"]},
    ).json()
    assert restored["state"]["expedition"]["status"] == "active"
    assert restored["state"]["progression"]["xp"] == 125
    assert choice in restored["actions"]
    current = request("GET", f"/api/campaign/{campaign['id']}").json()
    assert current["state"]["expedition"]["status"] == "completed"


def test_model_cannot_infer_an_irreversible_expedition_choice(monkeypatch):
    campaign = at_tower()
    monkeypatch.setattr(
        api,
        "interpret_action",
        lambda *_: (
            ActionProposal("resolve_expedition", "exploration", ("documents",), None, None),
            "mock",
        ),
    )
    response = request(
        "POST",
        "/api/game/turn",
        json={
            "campaign_id": campaign["id"],
            "expected_state_version": campaign["state_version"],
            "input": "문서를 포기하면 어떻게 될까?",
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "expedition_choice_requires_explicit_command"
    current = request("GET", f"/api/campaign/{campaign['id']}").json()
    assert current["state_version"] == campaign["state_version"]
    assert current["state"]["expedition"] == campaign["state"]["expedition"]


def test_new_locations_are_locked_before_expedition():
    campaign = request("POST", "/api/campaign", json={}).json()
    act(campaign, "시장으로 이동")
    for text in ["동쪽 성문으로 이동", "망루로 이동", "꺼진 망루의 전령 의뢰 수락"]:
        response = request(
            "POST",
            "/api/game/turn",
            json={
                "campaign_id": campaign["id"],
                "expected_state_version": campaign["state_version"],
                "input": text,
            },
        )
        assert response.status_code == 422
    assert "expedition" not in json.dumps(campaign["state"])


def test_all_expedition_buttons_bypass_ai_including_uppercase_dc(monkeypatch):
    def unexpected(*args):
        raise AssertionError("canonical buttons must never require an external model")

    monkeypatch.setattr(ai, "_provider_config", unexpected)
    for label, (intent, target) in expedition.COMMANDS.items():
        proposal, provider = ai.interpret_action(label)
        assert provider == "engine"
        assert (proposal.intent, proposal.target_ids) == (intent, (target,))
