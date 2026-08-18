# flake8: noqa: E501
import time

from fastapi.testclient import TestClient

from src.main import app

client = TestClient(app)


def get_headers(api_key="admin-key"):
    return {"x-api-key": api_key}


def restart_deployment_payload(deployment="web", **overrides):
    payload = {
        "event_type": "restart_deployment",
        "parameters": {"deployment": deployment},
    }
    payload.update(overrides)
    return payload


def test_webhook_second_call_blocked_by_cooldown():
    resp1 = client.post(
        "/webhook", json=restart_deployment_payload(), headers=get_headers()
    )
    assert resp1.status_code == 200

    resp2 = client.post(
        "/webhook", json=restart_deployment_payload(), headers=get_headers()
    )
    assert resp2.status_code == 409
    body = resp2.json()
    assert "cooldown" in body["detail"].lower()
    assert body["cooldown_remaining_seconds"] > 0


def test_webhook_cooldown_scoped_by_dedup_param():
    resp1 = client.post(
        "/webhook",
        json=restart_deployment_payload(deployment="web"),
        headers=get_headers(),
    )
    assert resp1.status_code == 200

    # A different deployment is a different cooldown key entirely.
    resp2 = client.post(
        "/webhook",
        json=restart_deployment_payload(deployment="api"),
        headers=get_headers(),
    )
    assert resp2.status_code == 200


def test_webhook_dry_run_never_blocked_and_never_consumes_cooldown():
    for _ in range(3):
        resp = client.post(
            "/webhook",
            json=restart_deployment_payload(dry_run=True),
            headers=get_headers(),
        )
        assert resp.status_code == 200

    # A real (non-dry-run) call right after must still be allowed - none
    # of the dry runs should have started the cooldown clock.
    resp = client.post(
        "/webhook", json=restart_deployment_payload(), headers=get_headers()
    )
    assert resp.status_code == 200


def test_webhook_cooldown_clears_after_window_elapses(monkeypatch):
    base = time.time()
    monkeypatch.setattr("src.cooldown.time.time", lambda: base)
    resp1 = client.post(
        "/webhook", json=restart_deployment_payload(), headers=get_headers()
    )
    assert resp1.status_code == 200

    monkeypatch.setattr("src.cooldown.time.time", lambda: base + 100)
    resp2 = client.post(
        "/webhook", json=restart_deployment_payload(), headers=get_headers()
    )
    assert resp2.status_code == 409  # restart_deployment's cooldown is 300s

    monkeypatch.setattr("src.cooldown.time.time", lambda: base + 301)
    resp3 = client.post(
        "/webhook", json=restart_deployment_payload(), headers=get_headers()
    )
    assert resp3.status_code == 200


def test_webhook_actions_without_cooldown_are_unaffected():
    payload = {"event_type": "restart_service", "parameters": {"service_name": "nginx"}}
    resp1 = client.post("/webhook", json=payload, headers=get_headers())
    resp2 = client.post("/webhook", json=payload, headers=get_headers())
    assert resp1.status_code == 200
    assert resp2.status_code == 200


def test_approve_blocked_by_cooldown_leaves_entry_pending():
    # Queue two separate approval requests for the same deployment.
    resp1 = client.post(
        "/webhook",
        json=restart_deployment_payload(approval_required=True),
        headers=get_headers("admin-key"),
    )
    resp2 = client.post(
        "/webhook",
        json=restart_deployment_payload(approval_required=True),
        headers=get_headers("admin-key"),
    )
    approval_id_1 = resp1.json()["approval_id"]
    approval_id_2 = resp2.json()["approval_id"]

    # Approving the first executes it and starts the cooldown.
    approve1 = client.post(
        f"/approvals/{approval_id_1}/approve", headers=get_headers("operator-key")
    )
    assert approve1.status_code == 200

    # Approving the second immediately hits the cooldown - blocked, but
    # the entry itself must stay pending (retryable), not consumed.
    approve2 = client.post(
        f"/approvals/{approval_id_2}/approve", headers=get_headers("operator-key")
    )
    assert approve2.status_code == 409

    listing = client.get("/approvals", headers=get_headers("admin-key")).json()
    entry2 = next(a for a in listing if a["id"] == approval_id_2)
    assert entry2["status"] == "pending"


def test_approve_succeeds_once_cooldown_clears(monkeypatch):
    base = time.time()
    monkeypatch.setattr("src.cooldown.time.time", lambda: base)

    resp1 = client.post(
        "/webhook",
        json=restart_deployment_payload(approval_required=True),
        headers=get_headers("admin-key"),
    )
    resp2 = client.post(
        "/webhook",
        json=restart_deployment_payload(approval_required=True),
        headers=get_headers("admin-key"),
    )
    approval_id_1 = resp1.json()["approval_id"]
    approval_id_2 = resp2.json()["approval_id"]

    assert (
        client.post(
            f"/approvals/{approval_id_1}/approve", headers=get_headers("operator-key")
        ).status_code
        == 200
    )

    monkeypatch.setattr("src.cooldown.time.time", lambda: base + 301)
    approve2 = client.post(
        f"/approvals/{approval_id_2}/approve", headers=get_headers("operator-key")
    )
    assert approve2.status_code == 200
