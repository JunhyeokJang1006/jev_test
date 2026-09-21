"""실제 narrator 요청 구성에서 관련 기억·출처·NPC 정보 경계를 검사한다."""

import json
from copy import deepcopy

from app import ai
from app.game import interpret_mock, resolve_action
from app.world import prepare


def test_narrator_receives_relevant_late_memory_but_no_other_npc_or_private_fact(monkeypatch):
    state = prepare(
        {
            "location_id": "greyhaven_inn",
            "player": {"hp": 31},
            "npcs": [{"id": "npc_harlan", "name": "Harlan"}],
        }
    )
    ledger = state["npc_knowledge"]["npc_harlan"]["facts"]
    for index in range(30):
        ledger[f"old_{index}"] = {
            "text": f"옛 순찰 근무 기록 {index}",
            "source": "witnessed_event",
            "certainty": "known",
            "shareable": True,
        }
    ledger["sluice_key"] = {
        "text": "남쪽 배수문 열쇠를 보관한다는 이야기를 상인에게 들었다.",
        "source": "merchant_report",
        "certainty": "reported",
        "shareable": True,
    }
    ledger["secret"] = {
        "text": "PRIVATE_NEVER 남쪽 배수문 열쇠",
        "source": "gm",
        "certainty": "known",
        "shareable": False,
    }
    state["npc_knowledge"]["npc_mira"]["facts"]["other"] = {
        "text": "OTHER_NPC_ONLY 남쪽 배수문 열쇠",
        "source": "witnessed_event",
        "certainty": "known",
        "shareable": True,
    }
    state["hidden_world_truth"] = "WORLD_SECRET_NEVER"
    outcome = resolve_action(state, interpret_mock("하를란과 대화"))
    before = deepcopy(outcome.state)
    monkeypatch.setattr(ai, "_provider_config", lambda: [("luna", "", "", "")])
    captured = []

    def chat(provider, messages):
        payload = json.loads(messages[-1]["content"])
        captured.append(payload)
        serialized = json.dumps(payload)
        for marker in ("PRIVATE_NEVER", "OTHER_NPC_ONLY", "WORLD_SECRET_NEVER"):
            assert marker not in serialized
        facts = payload["speaker"]["known_facts"]
        assert len(facts) <= 12
        fact = next(item for item in facts if item["id"] == "sluice_key")
        assert fact["certainty"] == "reported"
        assert fact["source"] == "merchant_report"
        return "luna", "Harlan: 상인에게 들은 이야기라 직접 확인하지는 못했소."

    monkeypatch.setattr(ai, "_chat", chat)
    result = ai.narrate_outcome("남쪽 배수문 열쇠에 대해 아는 것을 말해줘", outcome, "luna")
    assert result[1] == "luna"
    assert len(captured) == 1
    assert outcome.state == before
