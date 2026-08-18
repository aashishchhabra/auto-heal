from unittest.mock import MagicMock

from fastapi.testclient import TestClient

import src.auth as auth
from src.main import app
from src.vault import VaultUnavailableError

client = TestClient(app)


def test_resolve_api_keys_literal_map_unchanged():
    config = {"api_keys": {"admin-key": "admin"}}
    assert auth._resolve_api_keys(config) == {"admin-key": "admin"}


def test_resolve_api_keys_empty_config():
    assert auth._resolve_api_keys({}) == {}


def test_resolve_api_keys_from_vault(monkeypatch):
    config = {"api_keys": {"vault_path": "secret/data/auto-healer/api-keys"}}
    fake_client = MagicMock()
    fake_client.get_secret.return_value = {"vault-admin-key": "admin"}
    monkeypatch.setattr(auth, "vault_client", fake_client)

    result = auth._resolve_api_keys(config)

    assert result == {"vault-admin-key": "admin"}
    fake_client.get_secret.assert_called_once_with("secret/data/auto-healer/api-keys")


def test_resolve_api_keys_fails_closed_on_vault_error(monkeypatch):
    config = {"api_keys": {"vault_path": "secret/data/auto-healer/api-keys"}}
    fake_client = MagicMock()
    fake_client.get_secret.side_effect = VaultUnavailableError("unreachable")
    monkeypatch.setattr(auth, "vault_client", fake_client)

    result = auth._resolve_api_keys(config)

    assert result == {}


def test_middleware_denies_all_keys_when_vault_backed_and_unreachable(monkeypatch):
    fake_client = MagicMock()
    fake_client.get_secret.side_effect = VaultUnavailableError("unreachable")
    monkeypatch.setattr(auth, "vault_client", fake_client)
    monkeypatch.setattr(
        auth,
        "_load_auth_config",
        lambda: {
            "api_keys": {"vault_path": "secret/data/auto-healer/api-keys"},
            "roles": {"admin": {"permissions": []}},
        },
    )

    # Even a key that would be valid under the real (non-Vault) config
    # must be rejected once auth is Vault-backed and Vault is down.
    resp = client.get("/protected", headers={"x-api-key": "admin-key"})
    assert resp.status_code == 401


def test_middleware_accepts_key_resolved_from_vault(monkeypatch):
    fake_client = MagicMock()
    fake_client.get_secret.return_value = {"vault-issued-key": "admin"}
    monkeypatch.setattr(auth, "vault_client", fake_client)
    monkeypatch.setattr(
        auth,
        "_load_auth_config",
        lambda: {
            "api_keys": {"vault_path": "secret/data/auto-healer/api-keys"},
            "roles": {"admin": {"permissions": []}},
        },
    )

    resp = client.get("/protected", headers={"x-api-key": "vault-issued-key"})
    assert resp.status_code == 200

    # A key that's valid under the real static config is NOT valid here -
    # the vault_path config fully replaces the literal map, it doesn't
    # merge with it.
    resp2 = client.get("/protected", headers={"x-api-key": "admin-key"})
    assert resp2.status_code == 401
