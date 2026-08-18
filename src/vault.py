import logging
import os
import time
from threading import Lock
from typing import Any, Dict, Optional, Tuple

import requests

logger = logging.getLogger("autoheal.vault")

DEFAULT_CACHE_TTL_SECONDS = 300
DEFAULT_TIMEOUT_SECONDS = 5
DEFAULT_K8S_MOUNT_PATH = "kubernetes"
DEFAULT_K8S_JWT_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/token"
DEFAULT_TOKEN_REFRESH_BUFFER_SECONDS = 30


class VaultUnavailableError(Exception):
    """
    Raised when Vault isn't configured, is unreachable, or returns
    something that can't be used. Callers that read security-sensitive
    config (API keys, SSH private keys) must treat this as a reason to
    fail closed, not fall back to some stale or partial default.
    """


class VaultClient:
    """
    Minimal HashiCorp Vault client for reading KV v2 secrets over its HTTP
    API. This is deliberately narrow - one secrets engine version, two
    auth methods - matching what this codebase actually needs rather than
    wrapping the full Vault API surface. AppRole auth, AWS Secrets
    Manager, and dynamic secrets are a documented future extension, not
    built here.

    Two auth methods are supported, selected by `auth_method`
    ("token", the default, or "kubernetes"):
    - "token": a static `VAULT_TOKEN` is sent on every request, exactly
      as before. Simple, but the token is a long-lived credential that
      has to be provisioned and rotated out-of-band.
    - "kubernetes": Vault's Kubernetes auth method
      (https://developer.hashicorp.com/vault/docs/auth/kubernetes). The
      pod's own mounted ServiceAccount JWT is exchanged for a short-lived
      Vault token via `POST /v1/auth/<mount>/login`, the same
      ServiceAccount already used by `type: kubeapi` controllers for
      in-cluster Kubernetes API access. There is no static Vault
      credential to leak or rotate; the client transparently re-logs-in
      before the issued token expires.

    Reads are cached with a short TTL, since callers like src.auth check
    secrets on every single request - unlike a plain local YAML file, an
    HTTP round trip to Vault on every request would be both slow and
    needlessly hard on Vault itself.
    """

    def __init__(
        self,
        addr: Optional[str] = None,
        token: Optional[str] = None,
        namespace: Optional[str] = None,
        cache_ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        auth_method: Optional[str] = None,
        role: Optional[str] = None,
        mount_path: Optional[str] = None,
        jwt_path: Optional[str] = None,
        token_refresh_buffer_seconds: float = DEFAULT_TOKEN_REFRESH_BUFFER_SECONDS,
    ):
        self.addr = addr if addr is not None else os.environ.get("VAULT_ADDR")
        self.token = token if token is not None else os.environ.get("VAULT_TOKEN")
        self.namespace = (
            namespace if namespace is not None else os.environ.get("VAULT_NAMESPACE")
        )
        self.cache_ttl_seconds = cache_ttl_seconds
        self.timeout_seconds = timeout_seconds
        self.auth_method = (
            (
                auth_method
                if auth_method is not None
                else os.environ.get("VAULT_AUTH_METHOD", "token")
            )
            .strip()
            .lower()
        )
        self.role = role if role is not None else os.environ.get("VAULT_K8S_ROLE")
        self.mount_path = (
            mount_path
            if mount_path is not None
            else os.environ.get("VAULT_K8S_MOUNT_PATH", DEFAULT_K8S_MOUNT_PATH)
        )
        self.jwt_path = (
            jwt_path
            if jwt_path is not None
            else os.environ.get("VAULT_K8S_JWT_PATH", DEFAULT_K8S_JWT_PATH)
        )
        self.token_refresh_buffer_seconds = token_refresh_buffer_seconds
        self._cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._lock = Lock()
        self._auth_lock = Lock()
        self._k8s_token: Optional[str] = None
        self._k8s_token_expires_at: float = 0.0

    @property
    def is_configured(self) -> bool:
        if self.auth_method == "kubernetes":
            return bool(self.addr and self.role)
        return bool(self.addr and self.token)

    def get_secret(self, path: str) -> Dict[str, Any]:
        """
        Returns the `data.data` object of a KV v2 secret at `path` (the
        full mount-relative path, including the "data/" segment KV v2
        requires - e.g. "secret/data/auto-healer/api-keys"). Raises
        VaultUnavailableError if Vault isn't configured, unreachable, or
        the response can't be parsed as expected. Never returns stale
        data past cache_ttl_seconds; never silently returns partial data.
        """
        if not self.is_configured:
            if self.auth_method == "kubernetes":
                raise VaultUnavailableError(
                    "Vault is not configured (VAULT_ADDR/VAULT_K8S_ROLE not set)"
                )
            raise VaultUnavailableError(
                "Vault is not configured (VAULT_ADDR/VAULT_TOKEN not set)"
            )

        with self._lock:
            cached = self._cache.get(path)
        if cached is not None:
            fetched_at, data = cached
            if time.time() - fetched_at < self.cache_ttl_seconds:
                return data

        url = f"{self.addr.rstrip('/')}/v1/{path.lstrip('/')}"
        headers = {"X-Vault-Token": self._resolve_token()}
        if self.namespace:
            headers["X-Vault-Namespace"] = self.namespace
        try:
            resp = requests.get(url, headers=headers, timeout=self.timeout_seconds)
        except requests.RequestException as e:
            raise VaultUnavailableError(
                f"Failed to reach Vault at {self.addr}: {e}"
            ) from e

        if resp.status_code != 200:
            raise VaultUnavailableError(
                f"Vault returned {resp.status_code} for '{path}': {resp.text[:200]}"
            )
        try:
            body = resp.json()
            data = body["data"]["data"]
        except (ValueError, KeyError, TypeError) as e:
            raise VaultUnavailableError(
                f"Unexpected response shape from Vault for '{path}': {e}"
            ) from e

        with self._lock:
            self._cache[path] = (time.time(), data)
        return data

    def invalidate(self, path: Optional[str] = None):
        """
        Drop cached secret data for `path`, or everything (secrets and,
        if using Kubernetes auth, the cached Vault token) if path is
        None.
        """
        with self._lock:
            if path is None:
                self._cache.clear()
            else:
                self._cache.pop(path, None)
        if path is None:
            with self._auth_lock:
                self._k8s_token = None
                self._k8s_token_expires_at = 0.0

    def _resolve_token(self) -> str:
        """
        Returns the Vault token to send on the next request. For the
        static "token" auth method this is just the configured token;
        for "kubernetes" it's a short-lived token obtained (and
        transparently refreshed) via Kubernetes auth login.
        """
        if self.auth_method == "kubernetes":
            return self._ensure_kubernetes_token()
        return self.token

    def _ensure_kubernetes_token(self) -> str:
        with self._auth_lock:
            if self._k8s_token and time.time() < self._k8s_token_expires_at:
                return self._k8s_token
            self._k8s_token, self._k8s_token_expires_at = self._login_kubernetes()
            return self._k8s_token

    def _login_kubernetes(self) -> Tuple[str, float]:
        """
        Exchanges the pod's mounted ServiceAccount JWT for a Vault token
        via the Kubernetes auth method, and returns (token, expires_at)
        where expires_at is a time.time()-comparable deadline set a
        `token_refresh_buffer_seconds` margin before the token's actual
        lease expiry, so callers refresh proactively instead of racing
        an in-flight request against expiry. A `lease_duration` of 0
        (Vault's convention for a non-expiring token) is treated as
        never-expiring.
        """
        try:
            with open(self.jwt_path, "r") as f:
                jwt = f.read().strip()
        except OSError as e:
            raise VaultUnavailableError(
                "Failed to read Kubernetes service account token from "
                f"'{self.jwt_path}': {e}"
            ) from e
        if not jwt:
            raise VaultUnavailableError(
                f"Kubernetes service account token at '{self.jwt_path}' is empty"
            )

        url = f"{self.addr.rstrip('/')}/v1/auth/{self.mount_path.strip('/')}/login"
        headers = {}
        if self.namespace:
            headers["X-Vault-Namespace"] = self.namespace
        try:
            resp = requests.post(
                url,
                json={"role": self.role, "jwt": jwt},
                headers=headers,
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as e:
            raise VaultUnavailableError(
                f"Failed to reach Vault Kubernetes auth endpoint at {url}: {e}"
            ) from e

        if resp.status_code != 200:
            raise VaultUnavailableError(
                "Vault Kubernetes auth login returned "
                f"{resp.status_code} for role '{self.role}': {resp.text[:200]}"
            )
        try:
            body = resp.json()
            auth = body["auth"]
            client_token = auth["client_token"]
            lease_duration = auth["lease_duration"]
        except (ValueError, KeyError, TypeError) as e:
            raise VaultUnavailableError(
                f"Unexpected response shape from Vault Kubernetes auth login: {e}"
            ) from e

        if lease_duration <= 0:
            expires_at = float("inf")
        else:
            expires_at = time.time() + max(
                lease_duration - self.token_refresh_buffer_seconds, 1
            )
        logger.info(
            f"Vault Kubernetes auth: obtained token for role '{self.role}' "
            f"via mount '{self.mount_path}' (ttl={lease_duration}s)"
        )
        return client_token, expires_at


# Module-level singleton, configured from environment variables at import
# time - mirrors how the rest of the app wires up shared state (executor,
# cooldown_tracker, rate_limiter in src/main.py). Everything is a no-op
# (VaultUnavailableError on first use) until either VAULT_ADDR/VAULT_TOKEN
# (auth_method=token, the default) or VAULT_ADDR/VAULT_AUTH_METHOD=kubernetes/
# VAULT_K8S_ROLE are actually set, so importing this module has zero effect
# on deployments that don't use Vault.
vault_client = VaultClient()
