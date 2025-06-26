# flake8: noqa: E501
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from unittest.mock import patch

from src.main import app


def get_headers(api_key="admin-key"):
    return {"x-api-key": api_key}


def test_webhook_valid_playbook(monkeypatch):
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
    response = client.post("/webhook", json=payload, headers=get_headers())
    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "restart_service"
    assert data["controller"] == "ansible_local"  # Updated to match config
    assert data["parameters"]["service_name"] == "nginx"
    assert data["execution"]["success"] is True


def test_webhook_valid_script(monkeypatch):
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
    response = client.post("/webhook", json=payload, headers=get_headers())
    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "cleanup_disk"
    assert data["controller"] == "local"  # Updated to match config
    assert data["parameters"]["path"] == "/tmp"
    assert data["execution"]["success"] is True


def test_webhook_invalid_payload():
    client = TestClient(app)
    # Missing event_type
    payload = {"parameters": {"foo": "bar"}}
    response = client.post("/webhook", json=payload, headers=get_headers())
    assert response.status_code == 400
    assert "Invalid payload" in response.text


def test_webhook_unknown_action():
    client = TestClient(app)
    payload = {"event_type": "not_a_real_action"}
    response = client.post("/webhook", json=payload, headers=get_headers())
    assert response.status_code == 400
    assert response.json()["detail"] == "Unknown action/event_type"


def test_webhook_unknown_controller():
    client = TestClient(app)
    payload = {
        "event_type": "restart_service",
        "controller_override": "not_a_real_controller",
    }
    response = client.post("/webhook", json=payload, headers=get_headers())
    assert response.status_code == 400
    assert response.json()["detail"] == "Unknown controller"


def test_webhook_forbidden_override():
    client = TestClient(app)
    payload = {"event_type": "restart_service", "controller_override": "dc2-ansible"}
    response = client.post(
        "/webhook", json=payload, headers=get_headers("operator-key")
    )
    assert response.status_code == 403
    assert "not permitted" in response.json()["detail"]


def test_webhook_malformed_json():
    client = TestClient(app)
    # Send invalid JSON
    response = client.post("/webhook", data="{notjson}", headers=get_headers())
    assert response.status_code == 400
    assert "Malformed JSON" in response.text


def test_webhook_triggers_notifications_on_success(monkeypatch):
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
    with patch("src.notifications.requests.post") as mock_post:
        response = client.post("/webhook", json=payload, headers=get_headers())
        assert response.status_code == 200
        # Should send at least one notification (Slack or Teams)
        assert mock_post.called
        # Optionally, check payload structure for Slack/Teams
        calls = [call for call in mock_post.call_args_list]
        assert any("slack" in str(call) or "teams" in str(call) for call in calls)


def test_webhook_triggers_notifications_on_failure(monkeypatch):
    class DummyResult:
        success = False

        def as_dict(self):
            return {
                "success": False,
                "stdout": "",
                "stderr": "error occurred",
                "exit_code": 1,
                "error": "Some error",
            }

    monkeypatch.setattr(
        "src.main.executor.run_playbook", lambda *a, **kw: DummyResult()
    )
    client = TestClient(app)
    payload = {"event_type": "restart_service", "parameters": {"service_name": "nginx"}}
    with patch("src.notifications.requests.post") as mock_post:
        response = client.post("/webhook", json=payload, headers=get_headers())
        assert response.status_code == 200
        assert mock_post.called
        calls = [call for call in mock_post.call_args_list]
        assert any("slack" in str(call) or "teams" in str(call) for call in calls)


def test_webhook_playbook_dry_run(monkeypatch):
    class DummyResult:
        success = True

        def as_dict(self):
            return {
                "success": True,
                "stdout": "[DRY-RUN] Would execute playbook: playbooks/restart_service.yml with vars: {'service_name': 'nginx'}",
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
    response = client.post("/webhook", json=payload, headers=get_headers())
    assert response.status_code == 200
    data = response.json()
    assert data["dry_run"] is True
    assert data["execution"]["success"] is True
    assert "[DRY-RUN]" in data["execution"]["stdout"]
    assert data["stdout"] == (
        "[DRY-RUN] Would execute playbook: "
        "playbooks/restart_service.yml with vars: {'service_name': 'nginx'}"
    )


def test_webhook_script_dry_run(monkeypatch):
    class DummyResult:
        success = True

        def as_dict(self):
            return {
                "success": True,
                "stdout": "[DRY-RUN] Would execute script: scripts/cleanup_disk.sh with args: ['--path', '/tmp']",
                "stderr": "",
                "exit_code": 0,
                "error": None,
            }

    monkeypatch.setattr("src.main.executor.run_script", lambda *a, **kw: DummyResult())
    client = TestClient(app)
    payload = {
        "event_type": "cleanup_disk",
        "parameters": {"path": "/tmp"},
        "dry_run": True,
    }
    response = client.post("/webhook", json=payload, headers=get_headers())
    assert response.status_code == 200
    data = response.json()
    assert data["dry_run"] is True
    assert data["execution"]["success"] is True
    assert "[DRY-RUN]" in data["execution"]["stdout"]
    assert data["stdout"] == (
        "[DRY-RUN] Would execute script: "
        "scripts/cleanup_disk.sh with args: ['--path', '/tmp']"
    )


def test_webhook_approval_request(monkeypatch):
    client = TestClient(app)
    payload = {
        "event_type": "restart_service",
        "parameters": {"service_name": "nginx"},
        "approval_required": True,
    }
    response = client.post("/webhook", json=payload, headers=get_headers())
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "pending"
    assert "approval_id" in data


def test_approval_list_and_approve(monkeypatch):
    # Patch executor to avoid real execution
    class DummyResult:
        success = True

        def as_dict(self):
            return {
                "success": True,
                "stdout": "approved!",
                "stderr": "",
                "exit_code": 0,
                "error": None,
            }

    monkeypatch.setattr(
        "src.main.executor.run_playbook", lambda *a, **kw: DummyResult()
    )
    client = TestClient(app)
    # Request approval
    payload = {
        "event_type": "restart_service",
        "parameters": {"service_name": "nginx"},
        "approval_required": True,
    }
    resp = client.post("/webhook", json=payload, headers=get_headers())
    approval_id = resp.json()["approval_id"]
    # List approvals
    resp2 = client.get("/approvals")
    assert resp2.status_code == 200
    approvals = resp2.json()
    found = [a for a in approvals if a["id"] == approval_id]
    assert found and found[0]["status"] == "pending"
    # Approve
    resp3 = client.post(f"/approvals/{approval_id}/approve")
    assert resp3.status_code == 200
    data = resp3.json()
    assert data["status"] == "approved"
    assert data["result"]["success"] is True
    # Approvals list should now show status approved
    resp4 = client.get("/approvals")
    found2 = [a for a in resp4.json() if a["id"] == approval_id]
    assert found2 and found2[0]["status"] == "approved"


def test_approval_reject(monkeypatch):
    client = TestClient(app)
    # Request approval
    payload = {
        "event_type": "restart_service",
        "parameters": {"service_name": "nginx"},
        "approval_required": True,
    }
    resp = client.post("/webhook", json=payload, headers=get_headers())
    approval_id = resp.json()["approval_id"]
    # Reject
    resp2 = client.post(f"/approvals/{approval_id}/reject")
    assert resp2.status_code == 200
    data = resp2.json()
    assert data["status"] == "rejected"
    # Approvals list should now show status rejected
    resp3 = client.get("/approvals")
    found = [a for a in resp3.json() if a["id"] == approval_id]
    assert found and found[0]["status"] == "rejected"


def test_approval_not_found():
    client = TestClient(app)
    resp = client.post("/approvals/notarealid/approve")
    assert resp.status_code == 404
    resp2 = client.post("/approvals/notarealid/reject")
    assert resp2.status_code == 404


def test_approval_already_processed(monkeypatch):
    # Patch executor to avoid real execution
    class DummyResult:
        success = True

        def as_dict(self):
            return {
                "success": True,
                "stdout": "approved!",
                "stderr": "",
                "exit_code": 0,
                "error": None,
            }

    monkeypatch.setattr(
        "src.main.executor.run_playbook", lambda *a, **kw: DummyResult()
    )
    client = TestClient(app)
    # Request approval
    payload = {
        "event_type": "restart_service",
        "parameters": {"service_name": "nginx"},
        "approval_required": True,
    }
    resp = client.post("/webhook", json=payload, headers=get_headers())
    approval_id = resp.json()["approval_id"]
    # Approve
    resp2 = client.post(f"/approvals/{approval_id}/approve")
    assert resp2.status_code == 200
    # Approve again (should fail)
    resp3 = client.post(f"/approvals/{approval_id}/approve")
    assert resp3.status_code == 400
    # Reject after approve (should fail)
    resp4 = client.post(f"/approvals/{approval_id}/reject")
    assert resp4.status_code == 400
