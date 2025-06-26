from src.main import WebhookPayload
import uuid


def test_webhookpayload_approval_required():
    payload = WebhookPayload(
        event_type="restart_service",
        parameters={"service_name": "nginx"},
        approval_required=True,
    )
    assert payload.event_type == "restart_service"
    assert payload.parameters["service_name"] == "nginx"
    assert payload.approval_required is True


def test_approval_entry_structure():
    # Simulate creation of an approval entry
    entry_id = str(uuid.uuid4())
    payload = {
        "event_type": "restart_service",
        "parameters": {"service_name": "nginx"},
        "approval_required": True,
    }
    approval_entry = {
        "id": entry_id,
        "payload": payload,
        "status": "pending",
        "result": None,
        "requested_by": "admin-key",
        "role": "admin",
        "controller": "ansible_local",
    }
    assert approval_entry["status"] == "pending"
    assert approval_entry["result"] is None
    assert approval_entry["payload"]["approval_required"] is True
    assert approval_entry["controller"] == "ansible_local"


def test_approval_entry_status_transitions():
    # Simulate status transitions
    entry = {"status": "pending", "result": None}
    # Approve
    entry["status"] = "approved"
    entry["result"] = {"success": True}
    assert entry["status"] == "approved"
    assert entry["result"]["success"] is True
    # Reject
    entry["status"] = "rejected"
    entry["result"] = {"error": "Rejected by approver"}
    assert entry["status"] == "rejected"
    assert entry["result"]["error"] == "Rejected by approver"
