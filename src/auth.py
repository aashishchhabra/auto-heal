import os
import yaml
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    def get_valid_api_keys(self):
        with open(os.path.join(os.path.dirname(__file__), "../config/auth.yaml")) as f:
            config = yaml.safe_load(f)
        return set(config["api_keys"].keys())

    async def dispatch(self, request: Request, call_next):
        # Allow health endpoint without auth
        if request.url.path == "/health":
            return await call_next(request)
        api_key = request.headers.get("x-api-key")
        valid_api_keys = self.get_valid_api_keys()
        if not api_key or api_key not in valid_api_keys:
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
        return await call_next(request)


def get_role_from_api_key(api_key: str) -> str:
    with open(os.path.join(os.path.dirname(__file__), "../config/auth.yaml")) as f:
        config = yaml.safe_load(f)
    return config["api_keys"].get(api_key)


def has_permission(role: str, permission: str) -> bool:
    with open(os.path.join(os.path.dirname(__file__), "../config/auth.yaml")) as f:
        config = yaml.safe_load(f)
    role_perms = config["roles"].get(role, {}).get("permissions", [])
    for perm in role_perms:
        if isinstance(perm, dict) and permission in perm:
            return perm[permission]
        if perm == permission:
            return True
    return False
