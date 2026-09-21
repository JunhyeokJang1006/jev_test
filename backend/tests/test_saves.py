import pytest

from .helpers import request


def test_save_list_is_paginated_metadata_and_can_restore_without_local_storage():
    assert request("GET", "/api/saves").json() == {"snapshots": [], "total": 0}
    saved = []
    for name in ["첫 캠페인", "다른 캠페인", "세 번째"]:
        campaign = request("POST", "/api/campaign", json={"name": name}).json()
        saved.append(request("POST", f"/api/campaign/{campaign['id']}/save").json())
    page = request("GET", "/api/saves?limit=2").json()
    assert page["total"] == 3
    assert [s["snapshot_id"] for s in page["snapshots"]] == [
        saved[2]["snapshot_id"],
        saved[1]["snapshot_id"],
    ]
    item = request("GET", "/api/saves?limit=2&offset=2").json()["snapshots"][0]
    assert set(item) == {
        "snapshot_id",
        "campaign_id",
        "campaign_name",
        "state_version",
        "created_at",
    }
    assert item["campaign_name"] == "첫 캠페인"
    restored = request(
        "POST",
        f"/api/campaign/{item['campaign_id']}/load",
        json={"snapshot_id": item["snapshot_id"]},
    )
    assert restored.status_code == 201
    assert restored.json()["id"] != item["campaign_id"]
    assert request("GET", "/api/saves?offset=99").json() == {"snapshots": [], "total": 3}


@pytest.mark.parametrize(
    "query",
    ["limit=0", "limit=101", "offset=-1", "limit=abc", "offset=9223372036854775808"],
)
def test_save_list_rejects_invalid_pagination(query):
    assert request("GET", f"/api/saves?{query}").status_code == 422
