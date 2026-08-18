from fastapi.testclient import TestClient

import src.main as main
from src.main import app

client = TestClient(app)


def get_headers(api_key="admin-key"):
    return {"x-api-key": api_key}


def test_caller_rate_limit_blocks_after_role_limit(monkeypatch):
    # readonly's configured limit is 5/min in config/rate_limits.yaml
    monkeypatch.setattr(
        main.rate_limiter,
        "config",
        {"per_role": {"readonly": {"requests_per_minute": 3}}},
    )
    payload = {"event_type": "restart_service", "parameters": {"service_name": "nginx"}}
    for _ in range(3):
        resp = client.post(
            "/webhook", json=payload, headers=get_headers("readonly-key")
        )
        # readonly's execute_actions permission is false, so this always
        # 403s rather than executing - but rate limiting is checked
        # first regardless, so these calls just need to not be
        # rate-limited yet.
        assert resp.status_code != 429

    resp = client.post("/webhook", json=payload, headers=get_headers("readonly-key"))
    assert resp.status_code == 429
    body = resp.json()
    assert "retry_after_seconds" in body
    assert resp.headers.get("Retry-After") is not None


def test_rate_limit_is_scoped_per_api_key(monkeypatch):
    monkeypatch.setattr(
        main.rate_limiter,
        "config",
        {"per_role": {"admin": {"requests_per_minute": 1}}},
    )
    payload = {"event_type": "restart_service", "parameters": {"service_name": "nginx"}}
    resp1 = client.post("/webhook", json=payload, headers=get_headers("admin-key"))
    assert resp1.status_code != 429
    # admin-key is now at its limit...
    resp2 = client.post("/webhook", json=payload, headers=get_headers("admin-key"))
    assert resp2.status_code == 429
    # ...but a different caller (operator-key) has its own independent bucket.
    resp3 = client.post("/webhook", json=payload, headers=get_headers("operator-key"))
    assert resp3.status_code != 429


def test_action_level_rate_limit_applies_across_callers(monkeypatch):
    monkeypatch.setattr(
        main.rate_limiter,
        "config",
        {"per_action": {"restart_deployment": {"requests_per_minute": 1}}},
    )
    payload = {
        "event_type": "restart_deployment",
        "parameters": {"deployment": "web"},
    }
    resp1 = client.post("/webhook", json=payload, headers=get_headers("admin-key"))
    assert resp1.status_code != 429

    # A different caller triggering the SAME action still hits the
    # action-level limit, since it's scoped globally, not per caller.
    resp2 = client.post("/webhook", json=payload, headers=get_headers("operator-key"))
    assert resp2.status_code == 429


def test_unconfigured_action_has_no_action_level_limit(monkeypatch):
    monkeypatch.setattr(main.rate_limiter, "config", {})
    payload = {"event_type": "restart_service", "parameters": {"service_name": "nginx"}}
    for _ in range(20):
        resp = client.post("/webhook", json=payload, headers=get_headers("admin-key"))
        assert resp.status_code != 429
