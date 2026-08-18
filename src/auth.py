import logging
import os
import yaml
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from src.vault import vault_client, VaultUnavailableError

logger = logging.getLogger("autoheal.auth")

PUBLIC_PATHS = {"/health", "/live", "/ready"}

AUTH_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "../config/auth.yaml")


def _load_auth_config() -> dict:
    with open(AUTH_CONFIG_PATH) as f:
        return yaml.safe_load(f)


def _resolve_api_keys(config: dict) -> dict:
    """
    Returns the {api_key: <role string or scope dict>} map - see
    _normalize_key_entry for the two value shapes a single entry can
    take. config["api_keys"] itself supports two shapes: a literal
    mapping (the default, unchanged from before Vault support existed),
    or {"vault_path": "<path>"} to resolve the whole map from a Vault
    KV v2 secret shaped the same way at request time.

    Fails CLOSED on Vault failure: if vault_path is configured but Vault
    is unreachable/misconfigured, this returns an empty map (no key
    authenticates) rather than falling back to a stale or partial set.
    Auth silently staying open because a secrets backend hiccupped is far
    worse than a legitimate caller getting a 401 they can retry.
    """
    api_keys = config.get("api_keys") or {}
    vault_path = api_keys.get("vault_path") if isinstance(api_keys, dict) else None
    if not vault_path:
        return api_keys
    try:
        return vault_client.get_secret(vault_path)
    except VaultUnavailableError as e:
        logger.error(
            f"Vault-backed api_keys unavailable ({e}); failing closed - "
            "all API keys rejected until Vault recovers"
        )
        return {}


class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    def get_valid_api_keys(self):
        return set(_resolve_api_keys(_load_auth_config()).keys())

    async def dispatch(self, request: Request, call_next):
        # Allow health/liveness/readiness probes without auth - these are
        # hit by kubelet/Docker healthchecks, which don't send API keys.
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)
        api_key = request.headers.get("x-api-key")
        valid_api_keys = self.get_valid_api_keys()
        if not api_key or api_key not in valid_api_keys:
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
        return await call_next(request)


def _normalize_key_entry(entry) -> dict:
    """
    Normalizes one api_keys value into {role, allowed_actions,
    allowed_controllers}. Two shapes are accepted:
      - a plain string: the role name, unrestricted - this key may
        execute any action against any controller its role otherwise
        permits. This is the original shape and stays the default; every
        existing config keeps working unchanged.
      - a dict: {"role": <name>, "allowed_actions": [...],
        "allowed_controllers": [...]}. Either list is optional - a
        missing/None list means unrestricted for that dimension, same as
        the plain-string shape. An empty list ([]) is NOT the same as
        omitted: it denies everything for that dimension.

    Anything else (unknown key, unexpected shape) normalizes to
    role=None with both lists None; APIKeyAuthMiddleware has already
    rejected unrecognized keys before any of this can matter.
    """
    if isinstance(entry, str):
        return {"role": entry, "allowed_actions": None, "allowed_controllers": None}
    if isinstance(entry, dict):
        return {
            "role": entry.get("role"),
            "allowed_actions": entry.get("allowed_actions"),
            "allowed_controllers": entry.get("allowed_controllers"),
        }
    return {"role": None, "allowed_actions": None, "allowed_controllers": None}


def get_key_scope(api_key: str) -> dict:
    """Returns {role, allowed_actions, allowed_controllers} for api_key."""
    entry = _resolve_api_keys(_load_auth_config()).get(api_key)
    return _normalize_key_entry(entry)


def get_role_from_api_key(api_key: str) -> str:
    return get_key_scope(api_key)["role"]


def is_action_allowed_for_key(api_key: str, event_type: str) -> bool:
    """
    True if this API key's scope permits triggering `event_type` at all -
    independent of whether its role has execute_actions permission in
    the first place, which callers must check separately.
    """
    allowed = get_key_scope(api_key)["allowed_actions"]
    return allowed is None or event_type in allowed


def is_controller_allowed_for_key(api_key: str, controller_name: str) -> bool:
    """
    True if this API key's scope permits targeting `controller_name` -
    independent of the separate controller_override role permission,
    which gates whether a role may pick a non-default controller at all.
    """
    allowed = get_key_scope(api_key)["allowed_controllers"]
    return allowed is None or controller_name in allowed


def has_permission(role: str, permission: str) -> bool:
    config = _load_auth_config()
    role_perms = config["roles"].get(role, {}).get("permissions", [])
    for perm in role_perms:
        if isinstance(perm, dict) and permission in perm:
            return perm[permission]
        if perm == permission:
            return True
    return False
