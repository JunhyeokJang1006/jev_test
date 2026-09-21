import json

import pytest

from app import ai, api
from app.dice import Dice
from app.game import interpret_mock

from .helpers import request


@pytest.mark.parametrize(
    "text",
    [
        "고블린 대신 하를란을 공격하겠다.",
        "세 번째 고블린을 공격한다, 대상은 goblin_999야.",
        "고블린은 공격하지 않는다.",
        "고블린을 공격한다면 어떤 일이 생겨?",
        "attack goblin_999",
        "do not attack goblin_001",
        "고블린과 미라를 함께 공격한다.",
        "고블린을 공격한다. 아니, 취소해.",
    ],
)
def test_mock_does_not_retarget_ambiguous_attack(text):
    proposal = interpret_mock(text)
    assert proposal.intent == "describe_action"
    assert proposal.target_ids == ()


@pytest.mark.parametrize(
    "text,target",
    [
        ("눈앞 첫 번째 고블린을 검으로 공격한다.", "goblin_001"),
        ("두 번째 고블린에게 검을 휘두르겠다.", "goblin_002"),
        ("attack goblin_002", "goblin_002"),
        ("고블린을 공격한다", "goblin_001"),
    ],
)
def test_whole_attack_utterance_preserves_target(text, target):
    assert interpret_mock(text).target_ids == (target,)


def test_fallback_mixed_target_never_starts_combat_or_rolls(monkeypatch):
    def unexpected(*args):
        raise AssertionError("ambiguous target must not roll")

    campaign = request("POST", "/api/campaign", json={}).json()
    monkeypatch.setattr(Dice, "roll", unexpected)
    # Test settings force mock; no provider call or live player data is involved.
    monkeypatch.setattr(api, "jev_route", lambda text: {"enabled": False})
    response = request(
        "POST",
        "/api/game/turn",
        json={
            "campaign_id": campaign["id"],
            "expected_state_version": 0,
            "input": "고블린 대신 하를란을 공격하겠다.",
        },
    )
    assert response.status_code == 200
    assert "combat" not in response.json()["state"]
    assert response.json()["state"]["player"]["hp"] == campaign["state"]["player"]["hp"]


@pytest.mark.parametrize(
    "text",
    [
        "숨지 않는다",
        "숨을까?",
        "은신하지 말자",
        "그림자가 보이는지 질문한다",
        "몰래 들어갈 수 있는지 설명해 줘",
        "잠입은 하지 않고 기다리겠다",
        "숨는다. 아니 취소해",
        "미라가 숨는 모습을 관찰한다",
    ],
)
def test_stealth_mention_does_not_imply_action(text):
    assert interpret_mock(text).intent == "describe_action"


@pytest.mark.parametrize(
    "text",
    [
        "숨는다",
        "문 옆에 숨는다",
        "여관 문 옆에 몸을 숨긴다.",
        "문 옆 그림자에 은신해 기다린다.",
        "나는 문 옆 그림자에 숨어 경비병이 지나가기를 기다린다.",
    ],
)
def test_explicit_stealth_declarations_remain_supported(text):
    proposal = interpret_mock(text)
    assert proposal.intent == "hide_beside_door" and proposal.target_ids == ("door_inn",)


@pytest.mark.parametrize("text", ["숨지 않는다", "숨을까?", "그림자가 보이는지 질문한다"])
def test_stealth_question_or_refusal_does_not_roll_or_hide(monkeypatch, text):
    campaign = request("POST", "/api/campaign", json={}).json()

    def unexpected(*args):
        raise AssertionError("non-action must not roll")

    monkeypatch.setattr(Dice, "roll", unexpected)
    response = request(
        "POST",
        "/api/game/turn",
        json={
            "campaign_id": campaign["id"],
            "expected_state_version": 0,
            "input": text,
        },
    )
    assert response.status_code == 200
    result = response.json()
    assert result["event"]["type"] == "PLAYER_ACTION_RECORDED"
    assert result["event"]["payload"]["resolved"] is False
    assert result["state"]["hidden"] is False
    assert result["state"]["elapsed_minutes"] == campaign["state"]["elapsed_minutes"]
    assert result["state"]["resources"] == campaign["state"]["resources"]


@pytest.mark.parametrize(
    "text", ["숨지 않는다", "숨을까?", "가능 여부만 질문한다", "아직 실행하지 마."]
)
@pytest.mark.parametrize(
    "intent,target",
    [("hide_beside_door", "door_inn"), ("basic_attack", "goblin_001"), ("recover", "potion")],
)
def test_model_proposal_cannot_override_explicit_non_execution(monkeypatch, text, intent, target):
    monkeypatch.setattr(ai, "_provider_config", lambda: [("luna", "", "", "")])
    monkeypatch.setattr(
        ai,
        "_chat",
        lambda *a, **k: (
            "luna",
            json.dumps({"intent": intent, "target_ids": [target], "action_type": "exploration"}),
        ),
    )
    proposal, provider = ai.interpret_action(text)
    assert proposal.intent == "describe_action" and proposal.target_ids == ()
    assert provider == "mock"


def test_quoted_refusal_does_not_block_explicit_talk_request(monkeypatch):
    monkeypatch.setattr(ai, "_provider_config", lambda: [("luna", "", "", "")])
    monkeypatch.setattr(
        ai,
        "_chat",
        lambda *a, **k: (
            "luna",
            json.dumps(
                {"intent": "talk", "target_ids": ["npc_harlan"], "action_type": "exploration"}
            ),
        ),
    )
    proposal, provider = ai.interpret_action("하를란에게 '숨지 말자'고 전한다")
    assert proposal.intent == "talk" and provider == "luna"


@pytest.mark.parametrize(
    "text,intent,target,expected_provider",
    [
        ("고블린은 공격하지 않고 방어한다", "basic_attack", "goblin_001", "mock"),
        ("공격하지 말고 가능한지 알려줘", "basic_attack", "goblin_001", "mock"),
        ("숨지 않고 방어한다", "hide_beside_door", "door_inn", "mock"),
        ("고블린은 공격하지 않고 방어한다", "combat_defend", "player", "luna"),
        ("하를란에게 '공격하지 말자'고 전한다", "talk", "npc_harlan", "luna"),
    ],
)
def test_negative_clause_is_checked_against_proposed_action(
    monkeypatch, text, intent, target, expected_provider
):
    monkeypatch.setattr(ai, "_provider_config", lambda: [("luna", "", "", "")])
    monkeypatch.setattr(
        ai,
        "_chat",
        lambda *a, **k: (
            "luna",
            json.dumps({"intent": intent, "target_ids": [target], "action_type": "exploration"}),
        ),
    )
    proposal, provider = ai.interpret_action(text)
    assert provider == expected_provider
    assert proposal.intent == ("describe_action" if provider == "mock" else intent)
