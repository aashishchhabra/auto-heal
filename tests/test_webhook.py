import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient

from src.main import app


def get_headers(api_key="admin-key"):
    return {"x-api-key": api_key}


def test_webhook_valid_playbook(monkeypatch):
    class DummyResult:
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
    assert data["controller"] == "dc1-ansible"
    assert data["parameters"]["service_name"] == "nginx"
    assert data["execution"]["success"] is True


def test_webhook_valid_script(monkeypatch):
    class DummyResult:
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
    assert data["controller"] == "dc2-ansible"
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
