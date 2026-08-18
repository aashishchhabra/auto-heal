import logging
import os
import time
from threading import Lock
from typing import Any, Dict, Optional, Tuple

import requests

logger = logging.getLogger("autoheal.vault")

DEFAULT_CACHE_TTL_SECONDS = 300
DEFAULT_TIMEOUT_SECONDS = 5


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
    API, using a static token. This is deliberately narrow - one auth
    method, one secrets engine version - matching what this codebase
    actually needs rather than wrapping the full Vault API surface.
    AppRole/Kubernetes auth and dynamic secrets are a documented future
    extension, not built here.

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
    ):
        self.addr = addr if addr is not None else os.environ.get("VAULT_ADDR")
        self.token = token if token is not None else os.environ.get("VAULT_TOKEN")
        self.namespace = (
            namespace if namespace is not None else os.environ.get("VAULT_NAMESPACE")
        )
        self.cache_ttl_seconds = cache_ttl_seconds
        self.timeout_seconds = timeout_seconds
        self._cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._lock = Lock()

    @property
    def is_configured(self) -> bool:
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
        headers = {"X-Vault-Token": self.token}
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
        """Drop cached data for `path`, or everything if path is None."""
        with self._lock:
            if path is None:
                self._cache.clear()
            else:
                self._cache.pop(path, None)


# Module-level singleton, configured from environment variables at import
# time - mirrors how the rest of the app wires up shared state (executor,
# cooldown_tracker, rate_limiter in src/main.py). Everything is a no-op
# (VaultUnavailableError on first use) until VAULT_ADDR/VAULT_TOKEN are
# actually set, so importing this module has zero effect on deployments
# that don't use Vault.
vault_client = VaultClient()
