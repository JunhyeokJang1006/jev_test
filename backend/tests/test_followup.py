import json
from copy import deepcopy

import pytest

from app.context import scene_context
from app.followup import BRANCHES
from app.projection import public_state
from app.storage import connect, read_campaign

from .helpers import request
from .test_world import recover, turn


def start(branch):
    campaign = request("POST", "/api/campaign", json={}).json()
    recover(campaign)
    turn(campaign, "시장으로 이동")
    if branch != "exile":
        turn(campaign, "여관으로 이동")
    action = {
        "law": "하를란에게 봉인 반환",
        "mercy": "미라에게 봉인 전달",
        "exile": "봉인을 가지고 도시 떠나기",
    }[branch]
    assert turn(campaign, action, confirmed_ending=branch).status_code == 200
    return campaign


@pytest.mark.parametrize("branch", ["law", "mercy", "exile"])
def test_followup_keeps_choice_and_restores_evidence(branch):
    campaign = start(branch)
    original = deepcopy(campaign["state"]["quest"])
    assert turn(campaign, "후속 사건 시작").status_code == 200
    assert campaign["event"]["payload"]["rule_id"] == "greyhaven-aftermath-v1"
    assert campaign["state"]["followup"]["branch"] == branch
    if branch != "exile":
        turn(campaign, "하를란과 대화")
        assert "봉인이 사라졌소" not in campaign["narrative"]
        turn(campaign, "시장으로 이동")
    assert (
        turn(
            campaign,
            "오렌에게 안전한 피난로 확인" if branch == "exile" else "오렌의 통행세 증언 기록",
        ).status_code
        == 200
    )
    saved = request("POST", f"/api/campaign/{campaign['id']}/save").json()
    restored = request(
        "POST", f"/api/campaign/{campaign['id']}/load", json={"snapshot_id": saved["snapshot_id"]}
    ).json()
    assert restored["state"]["followup"] == campaign["state"]["followup"]
    campaign = restored
    assert turn(campaign, "창고로 이동").status_code == 200
    evidence_action = (
        "창고에서 피난 보급품 확보" if branch == "exile" else "창고의 통행세 장부 확보"
    )
    assert turn(campaign, evidence_action).status_code == 200
    version = campaign["state_version"]
    assert turn(campaign, evidence_action).status_code == 422
    assert campaign["state_version"] == version
    turn(campaign, "시장으로 이동")
    if branch == "law":
        turn(campaign, "여관으로 이동")
    finish = {
        "law": "하를란에게 감사 증거 제출",
        "mercy": "시장에서 통행세 증거 공개",
        "exile": "피난민과 함께 성문 통과",
    }[branch]
    assert turn(campaign, finish).status_code == 200
    assert campaign["state"]["quest"] == original
    assert campaign["state"]["followup"]["status"] == "completed"
    assert campaign["state"]["resources"]["gold"] == 35
    assert campaign["event"]["payload"]["reward_gold"] == 15
    assert (
        campaign["state"]["world_consequences"]["tax_collection"]
        == BRANCHES[branch]["tax_collection"]
    )
    assert campaign["state"]["progression"]["xp"] == 125
    assert len([action for action in campaign["actions"] if action.startswith("성장:")]) == 3
    assert turn(campaign, finish).status_code == 422
    skill = {"law": "전투 숙련", "mercy": "설득의 기술", "exile": "은밀한 발걸음"}[branch]
    assert turn(campaign, f"성장: {skill}").status_code == 200
    assert campaign["state"]["progression"]["level"] == 4
    assert campaign["state"]["player"]["max_hp"] == 42
    assert not any(action.startswith("성장:") for action in campaign["actions"])
    assert any("이동" in action for action in campaign["actions"])
    assert campaign["state"]["world_effects"]["applied"] is True
    connection = connect()
    state = read_campaign(connection, campaign["id"])["state"]
    connection.close()
    for npc, ledger in state["npc_knowledge"].items():
        assert ("seal_aftermath" in ledger["facts"]) == (npc == BRANCHES[branch]["ally"])


def test_followup_rejects_shortcuts_and_old_quest_actions():
    campaign = start("law")
    for action in ["하를란에게 감사 증거 제출", "창고의 통행세 장부 확보"]:
        assert turn(campaign, action).status_code == 422
    turn(campaign, "후속 사건 시작")
    for action in [
        "후속 사건 시작",
        "하를란에게 감사 증거 제출",
        "창고의 통행세 장부 확보",
        "오렌에게 안전한 피난로 확인",
        "봉인 회수",
        "주변 조사",
        "하를란에게 시장이 보냈다고 거짓말",
    ]:
        before = request("GET", f"/api/campaign/{campaign['id']}").json()
        assert turn(campaign, action).status_code == 422
        assert request("GET", f"/api/campaign/{campaign['id']}").json() == before


def test_followup_projection_and_model_commands_are_consistent():
    campaign = start("mercy")
    turn(campaign, "후속 사건 시작")
    turn(campaign, "시장으로 이동")
    state = campaign["state"]
    state["followup"]["hidden_truth"] = "SECRET"
    state["world_consequences"] = {"hidden_truth": "SECRET"}
    assert "SECRET" not in json.dumps(public_state(state))
    context = scene_context(state)
    assert "SECRET" not in json.dumps(context)
    assert context["followup"]["branch"] == "mercy"
    assert "오렌의 통행세 증언 기록" in [item["label"] for item in context["available_commands"]]
