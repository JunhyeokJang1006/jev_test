from .helpers import request


def test_health_exposes_bootstrap_status_without_provider_configuration():
    response = request("GET", "/api/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "luna-realms-api",
        "stage": "bootstrap",
    }


def test_unimplemented_turn_is_not_reported_as_success():
    response = request(
        "POST",
        "/api/game/turn",
        json={"campaign_id": "missing", "expected_state_version": 0, "input": "숨는다"},
    )
    assert response.status_code == 404
