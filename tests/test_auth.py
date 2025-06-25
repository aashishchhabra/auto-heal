import os
import sys
from fastapi.testclient import TestClient
from src.main import app

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert data["version"] == os.getenv("API_VERSION", "0.1.0")


def test_auth_required():
    response = client.get("/some-protected-endpoint")
    assert response.status_code == 401
    assert response.json()["detail"] == "Unauthorized"


def test_protected_requires_auth():
    response = client.get("/protected")
    assert response.status_code == 401
    assert response.json()["detail"] == "Unauthorized"


def test_protected_with_valid_api_key():
    response = client.get("/protected", headers={"x-api-key": "admin-key"})
    assert response.status_code == 200
    assert response.json()["message"] == "You have accessed a protected endpoint!"
