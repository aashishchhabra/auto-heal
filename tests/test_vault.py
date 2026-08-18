import time
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.vault import VaultClient, VaultUnavailableError


def make_client(**overrides):
    kwargs = {"addr": "https://vault.example.com", "token": "test-token"}
    kwargs.update(overrides)
    return VaultClient(**kwargs)


def make_k8s_client(tmp_path, jwt="sa-jwt-contents", **overrides):
    jwt_path = tmp_path / "token"
    if jwt is not None:
        jwt_path.write_text(jwt)
    kwargs = {
        "addr": "https://vault.example.com",
        "auth_method": "kubernetes",
        "role": "auto-healer",
        "jwt_path": str(jwt_path),
    }
    kwargs.update(overrides)
    return VaultClient(**kwargs)


def login_response(token="k8s-issued-token", lease_duration=3600):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "auth": {"client_token": token, "lease_duration": lease_duration}
    }
    return resp


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


# --- Kubernetes auth method ---------------------------------------------


def test_kubernetes_auth_configured_with_addr_and_role_only(tmp_path):
    client = make_k8s_client(tmp_path)
    assert client.is_configured is True


def test_kubernetes_auth_missing_role_is_unconfigured(tmp_path):
    client = make_k8s_client(tmp_path, role=None)
    assert client.is_configured is False


def test_kubernetes_auth_unconfigured_raises_role_specific_message(tmp_path):
    client = make_k8s_client(tmp_path, role=None)
    with pytest.raises(VaultUnavailableError, match="VAULT_K8S_ROLE"):
        client.get_secret("secret/data/x")


def test_kubernetes_auth_logs_in_and_uses_issued_token_for_secret_read(tmp_path):
    client = make_k8s_client(tmp_path)
    secret_resp = MagicMock()
    secret_resp.status_code = 200
    secret_resp.json.return_value = {"data": {"data": {"k": "v"}}}
    with patch("requests.post", return_value=login_response()) as mock_post:
        with patch("requests.get", return_value=secret_resp) as mock_get:
            data = client.get_secret("secret/data/x")
    assert data == {"k": "v"}
    login_url = mock_post.call_args[0][0]
    assert login_url == "https://vault.example.com/v1/auth/kubernetes/login"
    assert mock_post.call_args[1]["json"] == {
        "role": "auto-healer",
        "jwt": "sa-jwt-contents",
    }
    assert mock_get.call_args[1]["headers"]["X-Vault-Token"] == "k8s-issued-token"


def test_kubernetes_auth_custom_mount_path_used_in_login_url(tmp_path):
    client = make_k8s_client(tmp_path, mount_path="oidc-k8s")
    with patch("requests.post", return_value=login_response()) as mock_post:
        client._resolve_token()
    assert (
        mock_post.call_args[0][0] == "https://vault.example.com/v1/auth/oidc-k8s/login"
    )


def test_kubernetes_auth_namespace_header_sent_on_login(tmp_path):
    client = make_k8s_client(tmp_path, namespace="team-a")
    with patch("requests.post", return_value=login_response()) as mock_post:
        client._resolve_token()
    assert mock_post.call_args[1]["headers"]["X-Vault-Namespace"] == "team-a"


def test_kubernetes_auth_missing_jwt_file_raises(tmp_path):
    client = make_k8s_client(tmp_path, jwt=None)
    with pytest.raises(VaultUnavailableError, match="Failed to read"):
        client._resolve_token()


def test_kubernetes_auth_empty_jwt_file_raises(tmp_path):
    client = make_k8s_client(tmp_path, jwt="   ")
    with pytest.raises(VaultUnavailableError, match="empty"):
        client._resolve_token()


def test_kubernetes_auth_login_non_200_raises(tmp_path):
    client = make_k8s_client(tmp_path)
    resp = MagicMock()
    resp.status_code = 403
    resp.text = "permission denied"
    with patch("requests.post", return_value=resp):
        with pytest.raises(VaultUnavailableError, match="403"):
            client._resolve_token()


def test_kubernetes_auth_login_network_error_raises(tmp_path):
    client = make_k8s_client(tmp_path)
    with patch("requests.post", side_effect=requests.ConnectionError("refused")):
        with pytest.raises(VaultUnavailableError):
            client._resolve_token()


def test_kubernetes_auth_login_malformed_response_raises(tmp_path):
    client = make_k8s_client(tmp_path)
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"unexpected": "shape"}
    with patch("requests.post", return_value=resp):
        with pytest.raises(VaultUnavailableError):
            client._resolve_token()


def test_kubernetes_auth_token_reused_within_lease(tmp_path):
    client = make_k8s_client(tmp_path)
    with patch(
        "requests.post", return_value=login_response(lease_duration=3600)
    ) as mock_post:
        client._resolve_token()
        client._resolve_token()
    assert mock_post.call_count == 1


def test_kubernetes_auth_token_refreshed_near_expiry(tmp_path, monkeypatch):
    client = make_k8s_client(tmp_path)
    base = time.time()
    monkeypatch.setattr(time, "time", lambda: base)
    with patch(
        "requests.post", return_value=login_response(lease_duration=60)
    ) as mock_post:
        token1 = client._resolve_token()
        # lease_duration=60, refresh buffer=30 => expires_at = base + 30.
        # Advance past that so the next call must re-login.
        monkeypatch.setattr(time, "time", lambda: base + 31)
        token2 = client._resolve_token()
    assert mock_post.call_count == 2
    assert token1 == token2 == "k8s-issued-token"


def test_kubernetes_auth_zero_lease_duration_never_expires(tmp_path, monkeypatch):
    client = make_k8s_client(tmp_path)
    base = time.time()
    monkeypatch.setattr(time, "time", lambda: base)
    with patch(
        "requests.post", return_value=login_response(lease_duration=0)
    ) as mock_post:
        client._resolve_token()
        monkeypatch.setattr(time, "time", lambda: base + 10_000_000)
        client._resolve_token()
    assert mock_post.call_count == 1


def test_kubernetes_auth_invalidate_all_forces_relogin(tmp_path):
    client = make_k8s_client(tmp_path)
    with patch("requests.post", return_value=login_response()) as mock_post:
        client._resolve_token()
        client.invalidate()
        client._resolve_token()
    assert mock_post.call_count == 2


def test_kubernetes_auth_invalidate_path_does_not_force_relogin(tmp_path):
    client = make_k8s_client(tmp_path)
    with patch("requests.post", return_value=login_response()) as mock_post:
        client._resolve_token()
        client.invalidate("secret/data/x")
        client._resolve_token()
    assert mock_post.call_count == 1
