import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.context import scene_context
from app.dice import Dice
from app.game import interpret_mock, resolve_action
from app.projection import public_state
from app.storage import connect, read_campaign

from .helpers import request
from .test_followup import start
from .test_world import turn

ROUTES = [
    ("law", "warehouse", "tax_ledger", "몰래 통행세 장부 복사", "창고의 통행세 장부 확보"),
    ("law", "market", "oren_testimony", "오렌 설득해 증언 확보", "오렌의 통행세 증언 기록"),
    (
        "exile",
        "warehouse",
        "refugee_supplies",
        "몰래 피난 보급품 확보",
        "창고에서 피난 보급품 확보",
    ),
    ("exile", "market", "safe_route", "오렌 설득해 피난로 확인", "오렌에게 안전한 피난로 확인"),
]


def setup_route(branch, location):
    campaign = start(branch)
    turn(campaign, "후속 사건 시작")
    if branch != "exile":
        turn(campaign, "시장으로 이동")
    if location == "warehouse":
        turn(campaign, "창고로 이동")
    return campaign


@pytest.mark.parametrize("branch,location,target,action,safe", ROUTES)
@pytest.mark.parametrize("roll,success", [(1, False), (20, True)])
def test_risky_route_rolls_once_and_failure_has_safe_progress(
    monkeypatch, branch, location, target, action, safe, roll, success
):
    campaign = setup_route(branch, location)
    calls = []
    monkeypatch.setattr(Dice, "roll", lambda self, sides: calls.append(sides) or roll)
    before_minutes = campaign["state"]["elapsed_minutes"]
    payload = {
        "campaign_id": campaign["id"],
        "expected_state_version": campaign["state_version"],
        "request_id": "00000000-0000-4000-8000-000000000222",
        "input": action,
    }
    response = request("POST", "/api/game/turn", json=payload)
    assert response.status_code == 200
    outcome = response.json()
    campaign.update(outcome)
    assert request("POST", "/api/game/turn", json=payload).json() == outcome
    assert calls == [20]
    assert outcome["dice"]["outcome"] == ("success" if success else "failure")
    assert outcome["state"]["elapsed_minutes"] - before_minutes == (2 if success else 5)
    assert (target in outcome["state"]["followup"]["evidence"]) == success
    assert action not in outcome["actions"]
    assert turn(campaign, action).status_code == 422
    assert calls == [20]
    context = scene_context(outcome["state"])
    assert action not in [item["label"] for item in context["available_commands"]]
    if not success:
        saved = request("POST", f"/api/campaign/{campaign['id']}/save").json()
        campaign = request(
            "POST",
            f"/api/campaign/{campaign['id']}/load",
            json={"snapshot_id": saved["snapshot_id"]},
        ).json()
        assert turn(campaign, action).status_code == 422
        assert turn(campaign, safe).status_code == 200
        assert campaign["state"]["elapsed_minutes"] == before_minutes + 30
        assert target in campaign["state"]["followup"]["evidence"]
    connection = connect()
    state = read_campaign(connection, campaign["id"])["state"]
    connection.close()
    for npc, ledger in state["npc_knowledge"].items():
        assert (f"persuasion_{target}" in ledger["facts"]) == (
            location == "market" and npc == "npc_oren"
        )
    state["followup"]["attempts"][target]["secret"] = "SECRET"
    state["followup"]["attempts"]["hidden_target"] = {"skill": "SECRET"}
    assert "SECRET" not in json.dumps(public_state(state))


def test_concurrent_risky_commands_consume_only_one_roll(monkeypatch):
    campaign = setup_route("law", "market")
    calls = []
    monkeypatch.setattr(Dice, "roll", lambda self, sides: calls.append(sides) or 1)
    payload = {
        "campaign_id": campaign["id"],
        "expected_state_version": campaign["state_version"],
        "input": "오렌 설득해 증언 확보",
    }
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda _: request("POST", "/api/game/turn", json=payload), range(2))
        )
    assert sorted(result.status_code for result in results) == [200, 409]
    assert calls == [20]
    campaign.update(next(result.json() for result in results if result.status_code == 200))
    turn(campaign, "여관으로 이동")
    turn(campaign, "시장으로 이동")
    assert campaign["state"]["npcs"][0]["disposition"] == "wary"


def test_evidence_before_followup_is_rejected_without_roll(monkeypatch):
    campaign = request("POST", "/api/campaign", json={}).json()
    monkeypatch.setattr(Dice, "roll", lambda *_: pytest.fail("invalid action consumed RNG"))
    for _, _, _, action, safe in ROUTES:
        assert turn(campaign, action).status_code == 422
        assert turn(campaign, safe).status_code == 422


def test_falsey_injected_roller_is_not_replaced(monkeypatch):
    campaign = setup_route("law", "market")

    class FalseyRoller:
        def __bool__(self):
            return False

        def roll(self, sides):
            assert sides == 20
            return 1

    monkeypatch.setattr(Dice, "roll", lambda *_: pytest.fail("injected roller was ignored"))
    outcome = resolve_action(
        campaign["state"], interpret_mock("오렌 설득해 증언 확보"), roller=FalseyRoller()
    )
    assert outcome.dice["roll"] == 1
    assert outcome.dice["outcome"] == "failure"
