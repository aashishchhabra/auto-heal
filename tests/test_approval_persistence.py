import json
import os

import pytest
from fastapi.testclient import TestClient

import src.main as main
from src.main import app


@pytest.fixture(autouse=True)
def isolate_approval_queue(tmp_path, monkeypatch):
    # Point persistence at a scratch file and start each test with an
    # empty in-memory queue, so these tests don't read/write the real
    # logs/approvals.json or leak entries into other test files that
    # share the same module-level approval_queue list.
    state_path = tmp_path / "approvals.json"
    monkeypatch.setattr(main, "APPROVALS_STATE_PATH", str(state_path))
    original = list(main.approval_queue)
    main.approval_queue.clear()
    yield state_path
    main.approval_queue.clear()
    main.approval_queue.extend(original)


def get_headers(api_key="admin-key"):
    return {"x-api-key": api_key}


def test_save_and_load_round_trip(isolate_approval_queue):
    entry = {
        "id": "abc-123",
        "payload": {"event_type": "restart_service"},
        "status": "pending",
        "result": None,
        "requested_by": "admin-key",
        "role": "admin",
        "controller": "ansible_local",
    }
    with main.approval_lock:
        main.approval_queue.append(entry)
        main._save_approval_queue_locked()

    assert os.path.exists(isolate_approval_queue)
    with open(isolate_approval_queue) as f:
        on_disk = json.load(f)
    assert on_disk == [entry]

    # Simulate a fresh process: clear memory, reload from disk.
    main.approval_queue.clear()
    main._load_approval_queue()
    assert main.approval_queue == [entry]


def test_load_missing_file_leaves_queue_empty(isolate_approval_queue):
    assert not os.path.exists(isolate_approval_queue)
    main._load_approval_queue()
    assert main.approval_queue == []


def test_load_corrupt_file_logs_and_leaves_queue_empty(isolate_approval_queue):
    with open(isolate_approval_queue, "w") as f:
        f.write("{not valid json")
    main._load_approval_queue()
    assert main.approval_queue == []


def test_save_is_atomic_no_leftover_tmp_file(isolate_approval_queue):
    with main.approval_lock:
        main.approval_queue.append({"id": "x", "status": "pending"})
        main._save_approval_queue_locked()
    assert os.path.exists(isolate_approval_queue)
    assert not os.path.exists(f"{isolate_approval_queue}.tmp")


def test_prune_keeps_all_pending_drops_oldest_processed(monkeypatch):
    monkeypatch.setattr(main, "MAX_PROCESSED_APPROVALS", 2)
    main.approval_queue.extend(
        [
            {"id": "p1", "status": "pending"},
            {"id": "old-approved", "status": "approved"},
            {"id": "old-rejected", "status": "rejected"},
            {"id": "p2", "status": "pending"},
            {"id": "recent-approved", "status": "approved"},
            {"id": "recent-rejected", "status": "rejected"},
        ]
    )
    with main.approval_lock:
        main._prune_approval_queue_locked()
    ids = [e["id"] for e in main.approval_queue]
    # Both pending entries survive no matter what.
    assert "p1" in ids
    assert "p2" in ids
    # Only the 2 most recent processed entries survive.
    assert "old-approved" not in ids
    assert "old-rejected" not in ids
    assert "recent-approved" in ids
    assert "recent-rejected" in ids
    assert len(ids) == 4


def test_webhook_approval_request_persists_to_disk(isolate_approval_queue):
    client = TestClient(app)
    payload = {
        "event_type": "restart_service",
        "parameters": {"service_name": "nginx"},
        "approval_required": True,
    }
    resp = client.post("/webhook", json=payload, headers=get_headers())
    approval_id = resp.json()["approval_id"]

    with open(isolate_approval_queue) as f:
        on_disk = json.load(f)
    assert any(e["id"] == approval_id and e["status"] == "pending" for e in on_disk)


def test_approve_persists_result_to_disk(monkeypatch, isolate_approval_queue):
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
    payload = {
        "event_type": "restart_service",
        "parameters": {"service_name": "nginx"},
        "approval_required": True,
    }
    resp = client.post("/webhook", json=payload, headers=get_headers("admin-key"))
    approval_id = resp.json()["approval_id"]
    client.post(
        f"/approvals/{approval_id}/approve", headers=get_headers("operator-key")
    )

    with open(isolate_approval_queue) as f:
        on_disk = json.load(f)
    persisted = next(e for e in on_disk if e["id"] == approval_id)
    assert persisted["status"] == "approved"
    assert persisted["approved_by"] == "operator-key"
    assert persisted["result"]["success"] is True


def test_approval_queue_survives_reload_simulating_restart(monkeypatch):
    # A pending approval queued before a restart must still be there -
    # and still actionable - after the process comes back up and reloads.
    client = TestClient(app)
    payload = {
        "event_type": "restart_service",
        "parameters": {"service_name": "nginx"},
        "approval_required": True,
    }
    resp = client.post("/webhook", json=payload, headers=get_headers("admin-key"))
    approval_id = resp.json()["approval_id"]

    # Simulate the process restarting: drop the in-memory queue, reload.
    main.approval_queue.clear()
    main._load_approval_queue()

    found = [e for e in main.approval_queue if e["id"] == approval_id]
    assert found and found[0]["status"] == "pending"

    resp2 = client.get("/approvals", headers=get_headers("admin-key"))
    assert any(a["id"] == approval_id for a in resp2.json())
