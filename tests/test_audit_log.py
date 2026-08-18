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
    # APIKeyAuthMiddleware rejects the request before it ever reaches the
    # route, since "not-a-real-key" isn't in config/auth.yaml.
    client = TestClient(app)
    response = client.get("/audit", headers={"x-api-key": "not-a-real-key"})
    assert response.status_code == 401


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


def test_audit_log_entries_are_hash_chained(monkeypatch):
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
    headers = {"x-api-key": "admin-key"}
    client.post("/webhook", json=payload, headers=headers)
    client.post("/webhook", json=payload, headers=headers)

    entries = read_audit_log()
    assert len(entries) == 2
    first, second = entries
    assert first["sequence"] == 1
    assert second["sequence"] == 2
    assert second["prev_hash"] == first["entry_hash"]
    assert "entry_hash" in first and "entry_hash" in second


def test_audit_verify_endpoint_reports_healthy_chain(monkeypatch):
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
    client.post("/webhook", json=payload, headers={"x-api-key": "admin-key"})

    resp = client.get("/audit/verify", headers={"x-api-key": "admin-key"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["entries_checked"] == 2


def test_audit_verify_endpoint_detects_tampering(monkeypatch):
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
    client.post("/webhook", json=payload, headers={"x-api-key": "admin-key"})

    lines = open(AUDIT_LOG_PATH).readlines()
    tampered = json.loads(lines[0])
    tampered["action"] = "TAMPERED"
    lines[0] = json.dumps(tampered) + "\n"
    with open(AUDIT_LOG_PATH, "w") as f:
        f.writelines(lines)

    resp = client.get("/audit/verify", headers={"x-api-key": "admin-key"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["first_broken_line"] == 1


def test_audit_verify_requires_audit_read_permission(monkeypatch):
    import src.auth as auth

    monkeypatch.setattr(
        auth,
        "_load_auth_config",
        lambda: {
            "roles": {"norights": {"permissions": []}},
            "api_keys": {"norights-key": "norights"},
        },
    )
    client = TestClient(app)
    resp = client.get("/audit/verify", headers={"x-api-key": "norights-key"})
    assert resp.status_code == 403


def test_webhook_audit_entry_preserves_dry_run_flag(monkeypatch):
    class DummyResult:
        success = True

        def as_dict(self):
            return {
                "success": True,
                "stdout": "[DRY-RUN]",
                "stderr": "",
                "exit_code": 0,
                "error": None,
            }

    monkeypatch.setattr(
        "src.main.executor.run_playbook", lambda *a, **kw: DummyResult()
    )
    client = TestClient(app)
    payload = {
        "event_type": "restart_service",
        "parameters": {"service_name": "nginx"},
        "dry_run": True,
    }
    client.post("/webhook", json=payload, headers={"x-api-key": "admin-key"})

    entries = read_audit_log()
    assert len(entries) == 1
    # Previously dropped by write_audit_log's fixed field allowlist even
    # though every call site already computed it.
    assert entries[0]["dry_run"] is True


def test_cooldown_block_audit_entry_preserves_blocked_reason():
    # restart_deployment's default controller (dc2-oc) is non-local, so
    # this goes through the conftest-autouse-mocked run_remote (a
    # successful DummyResult) - no extra mocking needed here.
    client = TestClient(app)
    payload = {"event_type": "restart_deployment", "parameters": {"deployment": "web"}}
    # First call executes and starts the cooldown; second is blocked.
    client.post("/webhook", json=payload, headers={"x-api-key": "admin-key"})
    client.post("/webhook", json=payload, headers={"x-api-key": "admin-key"})

    entries = read_audit_log()
    assert len(entries) == 2
    blocked = entries[1]
    # Previously dropped by write_audit_log's fixed field allowlist even
    # though cooldown_block_audit_entry already computed it.
    assert blocked["blocked_reason"] == "cooldown"
    assert blocked["dry_run"] is False
