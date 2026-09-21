import json

import pytest

from app.context import scene_context
from app.storage import connect, read_campaign

from .helpers import request
from .test_world import turn


@pytest.mark.parametrize("branch,price", [("law", 6), ("mercy", 10), ("exile", 8)])
def test_delayed_prices_are_atomic_and_old_quotes_rejected(branch, price):
    campaign = request("POST", "/api/campaign", json={}).json()
    turn(campaign, "시장으로 이동")
    state = campaign["state"]
    state["quest"]["ending"] = branch
    state["followup"] = {"status": "completed", "branch": branch, "evidence": []}
    state["world_effects"] = {
        "effective_at": state["elapsed_minutes"] + 60,
        "applied": False,
        "notice": None,
    }
    connection = connect()
    connection.execute(
        "UPDATE campaigns SET state_json=? WHERE id=?", (json.dumps(state), campaign["id"])
    )
    connection.close()
    for _ in range(5):
        assert turn(campaign, "공고 기다리기 (10분)").status_code == 200
        assert not campaign["state"]["world_effects"]["applied"]
        assert "world_notice" not in campaign["event"]["payload"]
    saved = request("POST", f"/api/campaign/{campaign['id']}/save").json()
    assert turn(campaign, "공고 기다리기 (10분)").status_code == 200
    assert campaign["state"]["world_effects"]["applied"]
    assert "world_notice" in campaign["event"]["payload"]
    label = f"치유 물약 구매 ({price}골드)"
    assert label in campaign["actions"]
    assert label in [
        item["label"] for item in scene_context(campaign["state"])["available_commands"]
    ]
    before = request("GET", f"/api/campaign/{campaign['id']}").json()
    assert turn(campaign, "공고 기다리기 (10분)").status_code == 422
    if price != 8:
        assert turn(campaign, "치유 물약 구매 (8골드)").status_code == 422
    assert request("GET", f"/api/campaign/{campaign['id']}").json() == before
    assert turn(campaign, label).status_code == 200
    assert campaign["state"]["resources"]["gold"] == 20 - price
    assert campaign["event"]["payload"]["cost"] == price
    assert turn(campaign, "오렌과 대화").status_code == 200
    connection = connect()
    actual = read_campaign(connection, campaign["id"])["state"]
    connection.close()
    for npc, ledger in actual["npc_knowledge"].items():
        assert ("public_market_notice" in ledger["facts"]) == (npc == "npc_oren")
    restored = request(
        "POST", f"/api/campaign/{campaign['id']}/load", json={"snapshot_id": saved["snapshot_id"]}
    ).json()
    assert not restored["state"]["world_effects"]["applied"]
    assert turn(restored, "공고 기다리기 (10분)").status_code == 200
    assert restored["state"]["world_effects"]["applied"]
    assert restored["state"]["resources"]["gold"] == 20
