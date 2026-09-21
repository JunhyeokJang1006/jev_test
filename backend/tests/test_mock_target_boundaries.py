import pytest

from app import api
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
