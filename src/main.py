import logging
from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field, ValidationError
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager
import datetime
import os
import sys
import json
from threading import Lock

from src.auth import APIKeyAuthMiddleware, get_role_from_api_key, has_permission
from src.actions import get_action_config, get_controller_config, discover_actions
from src.executor import ActionExecutor
import logging.handlers
from src.notifications import notification_sender


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

# Configure structured logging with file rotation
LOG_DIR = os.path.join(os.path.dirname(__file__), "../logs")
LOG_PATH = os.path.join(LOG_DIR, "autoheal.log")
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)
file_handler = logging.handlers.RotatingFileHandler(
    LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=5
)
file_handler.setFormatter(JsonFormatter())
logger.addHandler(file_handler)

# Configure file handler with rotation for logs/app.log
APP_LOG_PATH = os.path.join(LOG_DIR, "app.log")
file_handler = logging.handlers.RotatingFileHandler(
    APP_LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=5
)
file_handler.setFormatter(JsonFormatter())
logger.addHandler(file_handler)

app = FastAPI()
app.add_middleware(APIKeyAuthMiddleware)
executor = ActionExecutor()

AUDIT_LOG_PATH = os.path.join(os.path.dirname(__file__), "../logs/audit.log")


def write_audit_log(entry: dict):
    audit_entry = {
        "timestamp": datetime.datetime.now(datetime.UTC)
        .isoformat()
        .replace("+00:00", "Z"),
        "user": entry.get("user"),
        "role": entry.get("role"),
        "action": entry.get("action"),
        "controller": entry.get("controller"),
        "controller_type": entry.get("controller_type"),
        "parameters": entry.get("parameters"),
        "execution": entry.get("execution"),
        "client_ip": entry.get("client_ip"),
        "status": entry.get("execution", {}).get("success"),
        "error": entry.get("execution", {}).get("error"),
    }
    with open(AUDIT_LOG_PATH, "a") as f:
        f.write(json.dumps(audit_entry) + "\n")


# Replace deprecated @app.on_event("startup") with lifespan event
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("API server starting up")
    # Merge discovered actions with config/actions.yaml
    discovered = discover_actions()
    # Load existing actions config
    import yaml

    actions_path = os.path.join(os.path.dirname(__file__), "../config/actions.yaml")
    with open(actions_path) as f:
        config_actions = yaml.safe_load(f)
    # Merge, giving priority to config/actions.yaml
    merged = {**discovered, **config_actions}

    # Patch get_action_config to use merged actions
    def get_action_config_patched(event_type):
        return merged.get(event_type)

    import src.actions

    src.actions.get_action_config = get_action_config_patched
    yield
    # Place any shutdown logic here


app = FastAPI(lifespan=lifespan)


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
    dry_run: Optional[bool] = Field(
        default=False, description="If true, simulate execution (dry-run)"
    )
    approval_required: Optional[bool] = Field(
        default=False, description="If true, require approval before execution"
    )


# In-memory approval queue (thread-safe)
approval_queue = []
approval_lock = Lock()

# Approval entry structure:
# {
#   "id": <unique>,
#   "payload": <WebhookPayload dict>,
#   "status": "pending"|"approved"|"rejected",
#   "result": None|dict
# }
import uuid


def get_approval_entry(entry_id):
    with approval_lock:
        for entry in approval_queue:
            if entry["id"] == entry_id:
                return entry
    return None


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
    dry_run = getattr(payload, "dry_run", False)
    approval_required = getattr(payload, "approval_required", False)
    if approval_required:
        # Queue for approval, do not execute
        entry_id = str(uuid.uuid4())
        approval_entry = {
            "id": entry_id,
            "payload": raw_payload,
            "status": "pending",
            "result": None,
            "requested_by": api_key,
            "role": role,
            "controller": controller_name,
        }
        with approval_lock:
            approval_queue.append(approval_entry)
        logger.info(f"Action '{event_type}' queued for approval (id={entry_id})")
        return {
            "approval_id": entry_id,
            "status": "pending",
            "detail": "Action requires approval before execution.",
        }
    # Dry-run support
    exec_result = None
    if "playbook" in action_config:
        playbook_path = action_config["playbook"]
        logger.info(
            f"Executing playbook '{playbook_path}' on controller '{controller_name}' "
            f"with params {params} (dry_run={dry_run})"
        )
        exec_result = executor.run_playbook(playbook_path, params, dry_run=dry_run)
    elif "script" in action_config:
        script_path = action_config["script"]
        logger.info(
            f"Executing script '{script_path}' on controller '{controller_name}' "
            f"with params {params} (dry_run={dry_run})"
        )
        args = [str(v) for v in params.values()] if params else None
        exec_result = executor.run_script(script_path, args, dry_run=dry_run)
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
        "dry_run": dry_run,
    }
    write_audit_log(audit_entry)
    # Send notifications (Slack & Teams)
    status = "success" if exec_result.success else "failure"
    details = exec_result.as_dict().get("stdout") or exec_result.as_dict().get("error")
    notification_sender.send_slack_notification(
        event_type, controller_name, api_key, status, details=details
    )
    notification_sender.send_teams_notification(
        event_type, controller_name, api_key, status, details=details
    )
    return {
        "action": event_type,
        "controller": controller_name,
        "parameters": params,
        "role": role,
        "controller_type": controller_config.get("type"),
        "execution": exec_result.as_dict(),
        "dry_run": dry_run,
    }


# Standard error response schema
class ErrorResponse(BaseModel):
    detail: str
    code: int
    errors: Optional[Any] = None


# Global exception handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    logger.error(
        json.dumps(
            {
                "event": "error",
                "type": "http_exception",
                "path": request.url.path,
                "client_ip": request.client.host if request.client else None,
                "status_code": exc.status_code,
                "detail": exc.detail,
            }
        )
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(detail=exc.detail, code=exc.status_code).model_dump(),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.error(
        json.dumps(
            {
                "event": "error",
                "type": "validation_error",
                "path": request.url.path,
                "client_ip": request.client.host if request.client else None,
                "errors": exc.errors(),
            }
        )
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=ErrorResponse(
            detail="Validation error", code=422, errors=exc.errors()
        ).model_dump(),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error(
        json.dumps(
            {
                "event": "error",
                "type": "unhandled_exception",
                "path": request.url.path,
                "client_ip": request.client.host if request.client else None,
                "error": str(exc),
            }
        )
    )
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(detail="Internal server error", code=500).model_dump(),
    )


class AuditQueryParams(BaseModel):
    start: Optional[str] = None  # ISO date string
    end: Optional[str] = None
    action: Optional[str] = None
    user: Optional[str] = None
    role: Optional[str] = None
    controller: Optional[str] = None
    limit: Optional[int] = 100


def filter_audit_entry(entry, params: AuditQueryParams):
    # Date filtering
    if params.start or params.end:
        ts = entry.get("timestamp")
        if ts:
            if params.start and ts < params.start:
                return False
            if params.end and ts > params.end:
                return False
    # Action, user, role, controller filtering
    if params.action and entry.get("action") != params.action:
        return False
    if params.user and entry.get("user") != params.user:
        return False
    if params.role and entry.get("role") != params.role:
        return False
    if params.controller and entry.get("controller") != params.controller:
        return False
    return True


@app.get("/audit", response_model=List[dict])
async def get_audit(
    request: Request,
    start: Optional[str] = None,
    end: Optional[str] = None,
    action: Optional[str] = None,
    user: Optional[str] = None,
    role: Optional[str] = None,
    controller: Optional[str] = None,
    limit: int = 100,
):
    api_key = request.headers.get("x-api-key")
    role_val = get_role_from_api_key(api_key)
    if not has_permission(role_val, "audit_read"):
        return JSONResponse(status_code=403, content={"detail": "Forbidden"})
    params = AuditQueryParams(
        start=start,
        end=end,
        action=action,
        user=user,
        role=role,
        controller=controller,
        limit=limit,
    )
    results = []
    with open(AUDIT_LOG_PATH, "r") as f:
        for line in reversed(list(f)):
            try:
                entry = json.loads(line)
                if filter_audit_entry(entry, params):
                    results.append(entry)
                    if len(results) >= params.limit:
                        break
            except Exception:
                continue
    return results


@app.get("/approvals")
def list_approvals():
    with approval_lock:
        return [
            {k: v for k, v in entry.items() if k != "result"}
            for entry in approval_queue
        ]


@app.post("/approvals/{approval_id}/approve")
def approve_approval(approval_id: str):
    entry = get_approval_entry(approval_id)
    if not entry:
        return JSONResponse(status_code=404, content={"detail": "Approval not found"})
    if entry["status"] != "pending":
        return JSONResponse(
            status_code=400, content={"detail": f"Already {entry['status']}"}
        )
    # Execute the action now
    payload = WebhookPayload(**entry["payload"])
    event_type = payload.event_type
    action_config = get_action_config(event_type)
    controller_name = payload.controller_override or action_config.get(
        "default_controller"
    )
    controller_config = get_controller_config(controller_name)
    params = action_config.get("parameters", {}).copy()
    params.update(payload.parameters or {})
    dry_run = getattr(payload, "dry_run", False)
    exec_result = None
    if "playbook" in action_config:
        playbook_path = action_config["playbook"]
        exec_result = executor.run_playbook(playbook_path, params, dry_run=dry_run)
    elif "script" in action_config:
        script_path = action_config["script"]
        args = [str(v) for v in params.values()] if params else None
        exec_result = executor.run_script(script_path, args, dry_run=dry_run)
    else:
        entry["status"] = "rejected"
        entry["result"] = {"error": "No playbook or script defined for action"}
        return JSONResponse(
            status_code=400,
            content={"detail": "No playbook or script defined for action"},
        )
    entry["status"] = "approved"
    entry["result"] = exec_result.as_dict()
    # Write audit log
    audit_entry = {
        "user": entry["requested_by"],
        "role": entry["role"],
        "action": event_type,
        "controller": controller_name,
        "controller_type": controller_config.get("type"),
        "parameters": params,
        "execution": exec_result.as_dict(),
        "client_ip": None,
        "dry_run": dry_run,
        "approval_id": approval_id,
        "approval_status": "approved",
    }
    write_audit_log(audit_entry)
    return {"status": "approved", "result": exec_result.as_dict()}


@app.post("/approvals/{approval_id}/reject")
def reject_approval(approval_id: str):
    entry = get_approval_entry(approval_id)
    if not entry:
        return JSONResponse(status_code=404, content={"detail": "Approval not found"})
    if entry["status"] != "pending":
        return JSONResponse(
            status_code=400, content={"detail": f"Already {entry['status']}"}
        )
    entry["status"] = "rejected"
    entry["result"] = {"error": "Rejected by approver"}
    # Write audit log
    audit_entry = {
        "user": entry["requested_by"],
        "role": entry["role"],
        "action": entry["payload"].get("event_type"),
        "controller": entry["controller"],
        "controller_type": None,
        "parameters": entry["payload"].get("parameters"),
        "execution": {"success": False, "error": "Rejected by approver"},
        "client_ip": None,
        "dry_run": entry["payload"].get("dry_run", False),
        "approval_id": approval_id,
        "approval_status": "rejected",
    }
    write_audit_log(audit_entry)
    return {"status": "rejected"}
