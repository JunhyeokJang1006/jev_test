"""Stubbed provider contract checks, not live-model language quality evaluation."""

import json

import pytest

from app import ai


@pytest.mark.parametrize(
    "text,intent,target",
    [
        ("눈앞 고블린을 밀어 넘어뜨릴게", "combat_shove", "goblin_001"),
        ("고블린의 시선을 속여 빈틈을 만들래", "combat_feint", "goblin_001"),
        ("공격 대신 빠르게 달릴게", "combat_dash", "player"),
    ],
)
@pytest.mark.parametrize("available", [True, False])
def test_model_tactical_intent_must_match_current_budget(
    monkeypatch, text, intent, target, available
):
    state = {
        "location_id": "greyhaven_inn",
        "encounter_enemy_id": "goblin_001",
        "player": {"hp": 31, "max_hp": 37},
        "combat": {
            "active": True,
            "enemy_x": 2,
            "enemy_y": 2,
            "action_available": available,
            "bonus_action_available": available,
        },
    }
    monkeypatch.setattr(ai, "_provider_config", lambda: [("luna", "", "", "")])

    def chat(provider, messages, **kwargs):
        body = json.loads(messages[-1]["content"])
        assert body["player_input"] == text
        commands = body["scene"]["available_commands"]
        assert (
            any(c["intent"] == intent and c["target_id"] == target for c in commands) == available
        )
        assert intent in messages[0]["content"]
        return "luna", json.dumps(
            {"intent": intent, "action_type": "exploration", "target_ids": [target]}
        )

    monkeypatch.setattr(ai, "_chat", chat)
    proposal, provider = ai.interpret_action(text, state)
    assert provider == ("luna" if available else "mock")
    assert proposal.intent == (intent if available else "describe_action")
