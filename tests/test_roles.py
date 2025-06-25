import os
import sys
from fastapi.testclient import TestClient
from src.main import app

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

client = TestClient(app)

API_KEY = os.getenv("API_KEY", "admin-key")


def test_admin_can_override():
    response = client.get(
        "/can-override-controller", headers={"x-api-key": "admin-key"}
    )
    assert response.status_code == 200
    assert response.json()["allowed"] is True
    assert response.json()["role"] == "admin"


def test_operator_cannot_override():
    response = client.get(
        "/can-override-controller", headers={"x-api-key": "operator-key"}
    )
    assert response.status_code == 403
    assert response.json()["allowed"] is False
    assert response.json()["role"] == "operator"


def test_readonly_cannot_override():
    response = client.get(
        "/can-override-controller", headers={"x-api-key": "readonly-key"}
    )
    assert response.status_code == 403
    assert response.json()["allowed"] is False
    assert response.json()["role"] == "readonly"


def test_webhook_action_mapping():
    payload = {"event_type": "restart_service", "parameters": {"service_name": "nginx"}}
    response = client.post("/webhook", json=payload, headers={"x-api-key": API_KEY})
    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "restart_service"
    assert data["controller"] == "ansible_local"
    assert data["parameters"]["service_name"] == "nginx"
    assert data["controller_type"] == "ansible"


def test_webhook_controller_override_allowed():
    payload = {
        "event_type": "cleanup_disk",
        "controller_override": "dc1-ansible",
        "parameters": {"path": "/var/tmp"},
    }
    response = client.post("/webhook", json=payload, headers={"x-api-key": "admin-key"})
    assert response.status_code == 200
    data = response.json()
    assert data["controller"] == "dc1-ansible"
    assert data["role"] == "admin"


def test_webhook_controller_override_forbidden():
    payload = {
        "event_type": "cleanup_disk",
        "controller_override": "dc1-ansible",
        "parameters": {"path": "/var/tmp"},
    }
    response = client.post(
        "/webhook", json=payload, headers={"x-api-key": "operator-key"}
    )
    assert response.status_code == 403
    assert "not permitted" in response.json()["detail"]


def test_webhook_unknown_action():
    payload = {"event_type": "not_a_real_action"}
    response = client.post("/webhook", json=payload, headers={"x-api-key": API_KEY})
    assert response.status_code == 400
    assert response.json()["detail"] == "Unknown action/event_type"


def test_webhook_unknown_controller():
    payload = {
        "event_type": "restart_service",
        "controller_override": "not_a_real_controller",
    }
    response = client.post("/webhook", json=payload, headers={"x-api-key": "admin-key"})
    assert response.status_code == 400
    assert response.json()["detail"] == "Unknown controller"
