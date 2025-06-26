import os
from fastapi.testclient import TestClient
from src.main import app


def test_liveness_probe():
    client = TestClient(app)
    response = client.get("/live")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "live"
    assert data["version"] == os.getenv("API_VERSION", "0.1.0")


def test_readiness_probe():
    client = TestClient(app)
    response = client.get("/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["version"] == os.getenv("API_VERSION", "0.1.0")
