import pytest


def test_liveness(client):
    assert client.get("/health/live").json() == {"status": "ok", "service": "api"}


def test_status_page_is_explicit_about_scaffold(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "scaffold" in response.text.lower()


def test_readiness_without_database_is_unavailable(client):
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "DATABASE_NOT_CONFIGURED"


def test_jobs_require_authentication(client):
    assert client.post("/api/jobs", json={}).status_code == 401


def test_caller_cannot_supply_tenant(client):
    response = client.post(
        "/api/jobs",
        headers={"Authorization": "Bearer analyst-test-token"},
        json={"scenario": "automatic_hold", "idempotency_key": "key-1", "tenant_id": "other"},
    )
    assert response.status_code == 422


def test_valid_job_is_explicitly_unimplemented(client):
    response = client.post(
        "/api/jobs",
        headers={"Authorization": "Bearer analyst-test-token"},
        json={"scenario": "automatic_hold", "idempotency_key": "key-1"},
    )
    assert response.status_code == 501
    assert response.json()["detail"]["code"] == "WORKFLOW_NOT_IMPLEMENTED"


def test_analyst_cannot_approve(client):
    response = client.post(
        "/api/proposals/proposal-1/decision",
        headers={"Authorization": "Bearer analyst-test-token"},
        json={"decision": "APPROVE", "proposal_version": 1, "reason": "Reviewed evidence"},
    )
    assert response.status_code == 403


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("get", "/api/jobs/job-1", None),
        ("get", "/api/jobs/job-1/events?after_seq=0", None),
        ("get", "/api/jobs/job-1/export", None),
        ("post", "/api/control", {"paused": True}),
        ("post", "/api/memories/mem-1/invalidate", {"reason": "Incorrect source"}),
        (
            "post",
            "/api/proposals/proposal-1/decision",
            {"decision": "APPROVE", "proposal_version": 1, "reason": "Reviewed"},
        ),
    ],
)
def test_planned_routes_are_registered(client, method, path, payload):
    response = client.request(
        method,
        path,
        headers={"Authorization": "Bearer officer-test-token"},
        **({"json": payload} if payload is not None else {}),
    )
    assert response.status_code == 501


def test_unknown_scenario_rejected(client):
    response = client.post(
        "/api/jobs",
        headers={"Authorization": "Bearer analyst-test-token"},
        json={"scenario": "transfer_real_funds", "idempotency_key": "key-1"},
    )
    assert response.status_code == 422
