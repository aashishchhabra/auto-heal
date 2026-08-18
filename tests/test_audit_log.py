import os
import sys
import json
import pytest
from fastapi.testclient import TestClient
from src.main import app, AUDIT_LOG_PATH

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def clear_audit_log():
    if os.path.exists(AUDIT_LOG_PATH):
        os.remove(AUDIT_LOG_PATH)


def read_audit_log():
    if not os.path.exists(AUDIT_LOG_PATH):
        return []
    with open(AUDIT_LOG_PATH) as f:
        return [json.loads(line) for line in f if line.strip()]


@pytest.fixture(autouse=True)
def run_around_tests():
    clear_audit_log()
    yield
    clear_audit_log()


def test_audit_log_written_on_webhook(monkeypatch):
    # Patch executor to avoid real execution
    class DummyResult:
        success = True

        def as_dict(self):
            return {
                "success": True,
                "stdout": "ok",
                "stderr": "",
                "exit_code": 0,
                "error": None,
            }

    monkeypatch.setattr(
        "src.main.executor.run_playbook", lambda *a, **kw: DummyResult()
    )
    monkeypatch.setattr("src.main.executor.run_script", lambda *a, **kw: DummyResult())

    client = TestClient(app)
    payload = {"event_type": "restart_service", "parameters": {"service_name": "nginx"}}
    headers = {"x-api-key": "admin-key"}
    response = client.post("/webhook", json=payload, headers=headers)
    assert response.status_code == 200
    audit_entries = read_audit_log()
    assert len(audit_entries) == 1
    entry = audit_entries[0]
    assert entry["user"] == "admin-key"
    assert entry["role"] == "admin"
    assert entry["action"] == "restart_service"
    # Updated to match the config default_controller
    assert entry["controller"] == "ansible_local"
    assert entry["parameters"]["service_name"] == "nginx"
    assert entry["execution"]["success"] is True
    assert "timestamp" in entry


def test_audit_log_written_on_script(monkeypatch):
    class DummyResult:
        success = True

        def as_dict(self):
            return {
                "success": True,
                "stdout": "done",
                "stderr": "",
                "exit_code": 0,
                "error": None,
            }

    monkeypatch.setattr("src.main.executor.run_script", lambda *a, **kw: DummyResult())
    client = TestClient(app)
    payload = {"event_type": "cleanup_disk", "parameters": {"path": "/tmp"}}
    headers = {"x-api-key": "admin-key"}
    response = client.post("/webhook", json=payload, headers=headers)
    assert response.status_code == 200
    audit_entries = read_audit_log()
    assert len(audit_entries) == 1
    entry = audit_entries[0]
    assert entry["action"] == "cleanup_disk"
    assert entry["execution"]["stdout"] == "done"
    assert entry["execution"]["success"] is True
    assert "timestamp" in entry


def test_audit_endpoint_accessible_to_all_roles(monkeypatch):
    # audit_read must be granted in config/auth.yaml for every role, or
    # /audit is unreachable regardless of who asks.
    class DummyResult:
        success = True

        def as_dict(self):
            return {
                "success": True,
                "stdout": "ok",
                "stderr": "",
                "exit_code": 0,
                "error": None,
            }

    monkeypatch.setattr(
        "src.main.executor.run_playbook", lambda *a, **kw: DummyResult()
    )
    client = TestClient(app)
    payload = {"event_type": "restart_service", "parameters": {"service_name": "nginx"}}
    client.post("/webhook", json=payload, headers={"x-api-key": "admin-key"})

    for api_key, role in (
        ("admin-key", "admin"),
        ("operator-key", "operator"),
        ("readonly-key", "readonly"),
    ):
        response = client.get("/audit", headers={"x-api-key": api_key})
        assert response.status_code == 200, f"role {role} was denied /audit"
        entries = response.json()
        assert len(entries) == 1
        assert entries[0]["role"] == "admin"


def test_audit_endpoint_rejects_unknown_key():
    # An unrecognized key maps to no role, so has_permission(None, ...)
    # denies audit_read and the route itself returns 403. (Note: this is
    # not the 401 the auth middleware is meant to produce for unknown
    # keys - see the separate finding about APIKeyAuthMiddleware not
    # being attached to the live `app` instance.)
    client = TestClient(app)
    response = client.get("/audit", headers={"x-api-key": "not-a-real-key"})
    assert response.status_code == 403


def test_audit_log_on_error(monkeypatch):
    class DummyResult:
        success = False

        def as_dict(self):
            return {
                "success": False,
                "stdout": "",
                "stderr": "fail",
                "exit_code": 1,
                "error": "fail",
            }

    monkeypatch.setattr(
        "src.main.executor.run_playbook", lambda *a, **kw: DummyResult()
    )
    client = TestClient(app)
    payload = {"event_type": "restart_service", "parameters": {"service_name": "bad"}}
    headers = {"x-api-key": "admin-key"}
    response = client.post("/webhook", json=payload, headers=headers)
    assert response.status_code == 200
    audit_entries = read_audit_log()
    assert len(audit_entries) == 1
    entry = audit_entries[0]
    assert entry["execution"]["success"] is False
    assert entry["execution"]["error"] == "fail"
    assert "timestamp" in entry
