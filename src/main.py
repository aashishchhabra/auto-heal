import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from src.auth import APIKeyAuthMiddleware, get_role_from_api_key, has_permission
from src.actions import get_action_config, get_controller_config
from src.executor import ActionExecutor
import os
import sys
import json
import datetime
from pydantic import BaseModel, Field, ValidationError
from typing import Optional, Dict, Any


# Configure structured logging
class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "level": record.levelname,
            "time": self.formatTime(record, self.datefmt),
            "message": record.getMessage(),
            "name": record.name,
        }
        if record.exc_info:
            log_record["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(log_record)


handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(JsonFormatter())
logging.basicConfig(level=logging.INFO, handlers=[handler])
logger = logging.getLogger("autoheal")

app = FastAPI()
app.add_middleware(APIKeyAuthMiddleware)
executor = ActionExecutor()

AUDIT_LOG_PATH = os.path.join(os.path.dirname(__file__), "../logs/audit.log")


def write_audit_log(entry: dict):
    entry["timestamp"] = datetime.datetime.utcnow().isoformat() + "Z"
    with open(AUDIT_LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")


@app.on_event("startup")
def on_startup():
    logger.info("API server starting up")


@app.get("/health")
async def health(request: Request):
    logger.info(f"Health check from {request.client.host}")
    return {"status": "ok", "version": os.getenv("API_VERSION", "0.1.0")}


@app.get("/protected")
async def protected():
    return {"message": "You have accessed a protected endpoint!"}


@app.get("/can-override-controller")
async def can_override_controller(request: Request):
    api_key = request.headers.get("x-api-key")
    role = get_role_from_api_key(api_key)
    allowed = has_permission(role, "controller_override")
    if allowed:
        return {"allowed": True, "role": role}
    return JSONResponse(
        status_code=403, content={"allowed": False, "role": role, "detail": "Forbidden"}
    )


class WebhookPayload(BaseModel):
    event_type: str = Field(..., description="Action/event type to trigger")
    controller_override: Optional[str] = Field(
        None, description="Override controller name"
    )
    parameters: Optional[Dict[str, Any]] = Field(
        default_factory=dict, description="Action parameters"
    )


@app.post("/webhook")
async def webhook(request: Request):
    try:
        raw_payload = await request.json()
        payload = WebhookPayload(**raw_payload)
    except ValidationError as ve:
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid payload", "errors": ve.errors()},
        )
    except Exception:
        return JSONResponse(
            status_code=400, content={"detail": "Malformed JSON payload"}
        )
    api_key = request.headers.get("x-api-key")
    role = get_role_from_api_key(api_key)
    event_type = payload.event_type
    action_config = get_action_config(event_type)
    if not action_config:
        return JSONResponse(
            status_code=400, content={"detail": "Unknown action/event_type"}
        )
    # Controller override logic
    controller_override = payload.controller_override
    controller_name = controller_override or action_config.get("default_controller")
    if controller_override:
        if not has_permission(role, "controller_override"):
            return JSONResponse(
                status_code=403,
                content={"detail": "Controller override not permitted for your role"},
            )
    controller_config = get_controller_config(controller_name)
    if not controller_config:
        return JSONResponse(status_code=400, content={"detail": "Unknown controller"})
    # Parameter merging
    params = action_config.get("parameters", {}).copy()
    params.update(payload.parameters or {})
    # Execute action
    exec_result = None
    if "playbook" in action_config:
        playbook_path = action_config["playbook"]
        logger.info(
            f"Executing playbook '{playbook_path}' on controller '{controller_name}' "
            f"with params {params}"
        )
        exec_result = executor.run_playbook(playbook_path, params)
    elif "script" in action_config:
        script_path = action_config["script"]
        logger.info(
            f"Executing script '{script_path}' on controller '{controller_name}' "
            f"with params {params}"
        )
        args = [str(v) for v in params.values()] if params else None
        exec_result = executor.run_script(script_path, args)
    else:
        logger.error(f"No executable defined for action '{event_type}'")
        return JSONResponse(
            status_code=400,
            content={"detail": "No playbook or script defined for action"},
        )
    logger.info(f"Execution result: {exec_result.as_dict()}")
    # Write audit log
    audit_entry = {
        "user": api_key,
        "role": role,
        "action": event_type,
        "controller": controller_name,
        "controller_type": controller_config.get("type"),
        "parameters": params,
        "execution": exec_result.as_dict(),
        "client_ip": request.client.host if request.client else None,
    }
    write_audit_log(audit_entry)
    return {
        "action": event_type,
        "controller": controller_name,
        "parameters": params,
        "role": role,
        "controller_type": controller_config.get("type"),
        "execution": exec_result.as_dict(),
    }
