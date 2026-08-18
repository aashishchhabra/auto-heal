import time
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.vault import VaultClient, VaultUnavailableError


def make_client(**overrides):
    kwargs = {"addr": "https://vault.example.com", "token": "test-token"}
    kwargs.update(overrides)
    return VaultClient(**kwargs)


def test_unconfigured_client_raises():
    client = VaultClient(addr=None, token=None)
    assert client.is_configured is False
    with pytest.raises(VaultUnavailableError):
        client.get_secret("secret/data/x")


def test_missing_token_is_unconfigured():
    client = VaultClient(addr="https://vault.example.com", token=None)
    assert client.is_configured is False


def test_successful_fetch_returns_data():
    client = make_client()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": {"data": {"admin-key": "admin"}}}
    with patch("requests.get", return_value=mock_resp) as mock_get:
        data = client.get_secret("secret/data/auto-healer/api-keys")
    assert data == {"admin-key": "admin"}
    called_url = mock_get.call_args[0][0]
    assert called_url == "https://vault.example.com/v1/secret/data/auto-healer/api-keys"
    assert mock_get.call_args[1]["headers"]["X-Vault-Token"] == "test-token"


def test_namespace_header_sent_when_configured():
    client = make_client(namespace="team-a")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": {"data": {}}}
    with patch("requests.get", return_value=mock_resp) as mock_get:
        client.get_secret("secret/data/x")
    assert mock_get.call_args[1]["headers"]["X-Vault-Namespace"] == "team-a"


def test_non_200_response_raises():
    client = make_client()
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_resp.text = "permission denied"
    with patch("requests.get", return_value=mock_resp):
        with pytest.raises(VaultUnavailableError):
            client.get_secret("secret/data/x")


def test_network_error_raises():
    client = make_client()
    with patch("requests.get", side_effect=requests.ConnectionError("refused")):
        with pytest.raises(VaultUnavailableError):
            client.get_secret("secret/data/x")


def test_malformed_response_raises():
    client = make_client()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"unexpected": "shape"}
    with patch("requests.get", return_value=mock_resp):
        with pytest.raises(VaultUnavailableError):
            client.get_secret("secret/data/x")


def test_result_is_cached_within_ttl():
    client = make_client(cache_ttl_seconds=60)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": {"data": {"k": "v"}}}
    with patch("requests.get", return_value=mock_resp) as mock_get:
        client.get_secret("secret/data/x")
        client.get_secret("secret/data/x")
    assert mock_get.call_count == 1


def test_cache_expires_after_ttl(monkeypatch):
    client = make_client(cache_ttl_seconds=10)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": {"data": {"k": "v"}}}
    base = time.time()
    monkeypatch.setattr(time, "time", lambda: base)
    with patch("requests.get", return_value=mock_resp) as mock_get:
        client.get_secret("secret/data/x")
        monkeypatch.setattr(time, "time", lambda: base + 11)
        client.get_secret("secret/data/x")
    assert mock_get.call_count == 2


def test_different_paths_cached_independently():
    client = make_client()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": {"data": {"k": "v"}}}
    with patch("requests.get", return_value=mock_resp) as mock_get:
        client.get_secret("secret/data/a")
        client.get_secret("secret/data/b")
        client.get_secret("secret/data/a")
    assert mock_get.call_count == 2


def test_invalidate_specific_path():
    client = make_client()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": {"data": {"k": "v"}}}
    with patch("requests.get", return_value=mock_resp) as mock_get:
        client.get_secret("secret/data/a")
        client.invalidate("secret/data/a")
        client.get_secret("secret/data/a")
    assert mock_get.call_count == 2


def test_invalidate_all():
    client = make_client()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": {"data": {"k": "v"}}}
    with patch("requests.get", return_value=mock_resp) as mock_get:
        client.get_secret("secret/data/a")
        client.get_secret("secret/data/b")
        client.invalidate()
        client.get_secret("secret/data/a")
        client.get_secret("secret/data/b")
    assert mock_get.call_count == 4
