"""
Tests for fine-grained per-action/per-controller API key scoping
(Phase 12 Story 2) - both the auth.py primitives and their wiring into
/webhook and the approval workflow.
"""

from fastapi.testclient import TestClient

import src.auth as auth
import src.main as main
from src.main import app

client = TestClient(app)


def get_headers(api_key):
    return {"x-api-key": api_key}


# --- src/auth.py primitives ---------------------------------------------


def test_normalize_key_entry_plain_string_is_unrestricted():
    entry = auth._normalize_key_entry("operator")
    assert entry == {
        "role": "operator",
        "allowed_actions": None,
        "allowed_controllers": None,
    }


def test_normalize_key_entry_dict_shape():
    entry = auth._normalize_key_entry(
        {
            "role": "operator",
            "allowed_actions": ["restart_service"],
            "allowed_controllers": ["ansible_local"],
        }
    )
    assert entry == {
        "role": "operator",
        "allowed_actions": ["restart_service"],
        "allowed_controllers": ["ansible_local"],
    }


def test_normalize_key_entry_dict_missing_lists_is_unrestricted():
    entry = auth._normalize_key_entry({"role": "operator"})
    assert entry["allowed_actions"] is None
    assert entry["allowed_controllers"] is None


def test_normalize_key_entry_unknown_shape():
    entry = auth._normalize_key_entry(None)
    assert entry == {"role": None, "allowed_actions": None, "allowed_controllers": None}


def test_is_action_allowed_for_key_unrestricted(monkeypatch):
    monkeypatch.setattr(
        auth,
        "_load_auth_config",
        lambda: {"api_keys": {"k": "operator"}, "roles": {}},
    )
    assert auth.is_action_allowed_for_key("k", "anything") is True


def test_is_action_allowed_for_key_scoped(monkeypatch):
    monkeypatch.setattr(
        auth,
        "_load_auth_config",
        lambda: {
            "api_keys": {
                "k": {"role": "operator", "allowed_actions": ["restart_service"]}
            },
            "roles": {},
        },
    )
    assert auth.is_action_allowed_for_key("k", "restart_service") is True
    assert auth.is_action_allowed_for_key("k", "restart_deployment") is False


def test_is_action_allowed_for_key_empty_list_denies_all(monkeypatch):
    monkeypatch.setattr(
        auth,
        "_load_auth_config",
        lambda: {
            "api_keys": {"k": {"role": "operator", "allowed_actions": []}},
            "roles": {},
        },
    )
    assert auth.is_action_allowed_for_key("k", "restart_service") is False


def test_is_controller_allowed_for_key_scoped(monkeypatch):
    monkeypatch.setattr(
        auth,
        "_load_auth_config",
        lambda: {
            "api_keys": {
                "k": {"role": "operator", "allowed_controllers": ["ansible_local"]}
            },
            "roles": {},
        },
    )
    assert auth.is_controller_allowed_for_key("k", "ansible_local") is True
    assert auth.is_controller_allowed_for_key("k", "dc2-oc") is False


def test_get_role_from_api_key_works_for_both_shapes(monkeypatch):
    monkeypatch.setattr(
        auth,
        "_load_auth_config",
        lambda: {
            "api_keys": {"plain": "admin", "scoped": {"role": "operator"}},
            "roles": {},
        },
    )
    assert auth.get_role_from_api_key("plain") == "admin"
    assert auth.get_role_from_api_key("scoped") == "operator"


# --- /webhook wiring -------------------------------------------------------

SCOPED_CONFIG = {
    "roles": {
        "admin": {
            "permissions": [
                {"controller_override": True},
                {"execute_actions": True},
                {"audit_read": True},
                {"approvals_read": True},
                {"approve_actions": True},
            ]
        },
        "operator": {
            "permissions": [
                {"controller_override": True},
                {"execute_actions": True},
                {"audit_read": True},
                {"approvals_read": True},
                {"approve_actions": True},
            ]
        },
        "readonly": {
            "permissions": [
                {"controller_override": False},
                {"execute_actions": False},
                {"audit_read": True},
                {"approvals_read": True},
                {"approve_actions": False},
            ]
        },
    },
    "api_keys": {
        "admin-key": "admin",
        "readonly-key": "readonly",
        "scoped-restart-key": {
            "role": "operator",
            "allowed_actions": ["restart_service"],
            "allowed_controllers": ["ansible_local"],
        },
        "scoped-empty-key": {"role": "operator", "allowed_actions": []},
    },
}


def use_scoped_config(monkeypatch):
    monkeypatch.setattr(auth, "_load_auth_config", lambda: SCOPED_CONFIG)


def test_readonly_role_cannot_execute_actions(monkeypatch):
    use_scoped_config(monkeypatch)
    payload = {"event_type": "restart_service", "parameters": {"service_name": "nginx"}}
    resp = client.post("/webhook", json=payload, headers=get_headers("readonly-key"))
    assert resp.status_code == 403
    assert "Executing actions is not permitted" in resp.json()["detail"]


def test_unrestricted_key_can_execute_any_configured_action(monkeypatch):
    use_scoped_config(monkeypatch)
    payload = {"event_type": "restart_deployment", "parameters": {"deployment": "web"}}
    resp = client.post("/webhook", json=payload, headers=get_headers("admin-key"))
    assert resp.status_code == 200


def test_scoped_key_allowed_action_and_controller_succeeds(monkeypatch):
    use_scoped_config(monkeypatch)
    payload = {"event_type": "restart_service", "parameters": {"service_name": "nginx"}}
    resp = client.post(
        "/webhook", json=payload, headers=get_headers("scoped-restart-key")
    )
    assert resp.status_code == 200
    assert resp.json()["controller"] == "ansible_local"


def test_scoped_key_disallowed_action_rejected(monkeypatch):
    use_scoped_config(monkeypatch)
    payload = {"event_type": "restart_deployment", "parameters": {"deployment": "web"}}
    resp = client.post(
        "/webhook", json=payload, headers=get_headers("scoped-restart-key")
    )
    assert resp.status_code == 403
    assert "restart_deployment" in resp.json()["detail"]
    assert "not permitted for your API key" in resp.json()["detail"]


def test_scoped_key_disallowed_controller_rejected_on_override(monkeypatch):
    use_scoped_config(monkeypatch)
    payload = {
        "event_type": "restart_service",
        "controller_override": "dc1-ansible",
        "parameters": {"service_name": "nginx"},
    }
    resp = client.post(
        "/webhook", json=payload, headers=get_headers("scoped-restart-key")
    )
    assert resp.status_code == 403
    assert "dc1-ansible" in resp.json()["detail"]
    assert "not permitted for your API key" in resp.json()["detail"]


def test_scoped_key_disallowed_controller_rejected_on_default(monkeypatch):
    # allowed_actions is unrestricted (None) but allowed_controllers is
    # not, and restart_deployment's default controller (dc2-oc) isn't in
    # it - the default controller is scoped too, not just overrides.
    monkeypatch.setattr(
        auth,
        "_load_auth_config",
        lambda: {
            **SCOPED_CONFIG,
            "api_keys": {
                **SCOPED_CONFIG["api_keys"],
                "controller-scoped-key": {
                    "role": "operator",
                    "allowed_controllers": ["ansible_local"],
                },
            },
        },
    )
    payload = {"event_type": "restart_deployment", "parameters": {"deployment": "web"}}
    resp = client.post(
        "/webhook", json=payload, headers=get_headers("controller-scoped-key")
    )
    assert resp.status_code == 403
    assert "dc2-oc" in resp.json()["detail"]


def test_empty_allowed_actions_denies_everything(monkeypatch):
    use_scoped_config(monkeypatch)
    payload = {"event_type": "restart_service", "parameters": {"service_name": "nginx"}}
    resp = client.post(
        "/webhook", json=payload, headers=get_headers("scoped-empty-key")
    )
    assert resp.status_code == 403


# --- Approval workflow wiring ----------------------------------------------


def test_queue_time_scoping_blocks_disallowed_action(monkeypatch):
    use_scoped_config(monkeypatch)
    payload = {
        "event_type": "restart_deployment",
        "parameters": {"deployment": "web"},
        "approval_required": True,
    }
    resp = client.post(
        "/webhook", json=payload, headers=get_headers("scoped-restart-key")
    )
    assert resp.status_code == 403
    # Never queued - confirm nothing pending shows up for an admin.
    pending = client.get("/approvals", headers=get_headers("admin-key")).json()
    assert not any(
        e["payload"]["event_type"] == "restart_deployment"
        and e.get("requested_by") == "scoped-restart-key"
        for e in pending
    )


def test_queue_time_scoping_allows_permitted_action(monkeypatch):
    use_scoped_config(monkeypatch)
    payload = {
        "event_type": "restart_service",
        "parameters": {"service_name": "nginx"},
        "approval_required": True,
    }
    resp = client.post(
        "/webhook", json=payload, headers=get_headers("scoped-restart-key")
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"


def test_approve_time_reverifies_requester_scope(monkeypatch):
    # Queue while the key is still permitted...
    use_scoped_config(monkeypatch)
    payload = {
        "event_type": "restart_service",
        "parameters": {"service_name": "nginx"},
        "approval_required": True,
    }
    resp = client.post(
        "/webhook", json=payload, headers=get_headers("scoped-restart-key")
    )
    assert resp.status_code == 200
    approval_id = resp.json()["approval_id"]

    # ...then narrow the key's scope before it gets approved, simulating
    # config/auth.yaml changing while the request sat pending.
    narrowed_config = {
        **SCOPED_CONFIG,
        "api_keys": {
            **SCOPED_CONFIG["api_keys"],
            "scoped-restart-key": {
                "role": "operator",
                "allowed_actions": [],  # now permits nothing
            },
        },
    }
    monkeypatch.setattr(auth, "_load_auth_config", lambda: narrowed_config)

    approve_resp = client.post(
        f"/approvals/{approval_id}/approve", headers=get_headers("admin-key")
    )
    assert approve_resp.status_code == 403
    assert "no longer permitted" in approve_resp.json()["detail"]

    # The entry is rejected, not left dangling pending.
    with main.approval_lock:
        entry = main._find_approval_entry_locked(approval_id)
    assert entry["status"] == "rejected"
    assert "no longer permitted" in entry["result"]["error"]


def test_approve_time_succeeds_when_scope_unchanged(monkeypatch):
    use_scoped_config(monkeypatch)
    payload = {
        "event_type": "restart_service",
        "parameters": {"service_name": "nginx"},
        "approval_required": True,
    }
    resp = client.post(
        "/webhook", json=payload, headers=get_headers("scoped-restart-key")
    )
    approval_id = resp.json()["approval_id"]

    approve_resp = client.post(
        f"/approvals/{approval_id}/approve", headers=get_headers("admin-key")
    )
    assert approve_resp.status_code == 200
    assert approve_resp.json()["status"] == "approved"
