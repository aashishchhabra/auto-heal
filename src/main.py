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

from src.auth import (
    APIKeyAuthMiddleware,
    get_role_from_api_key,
    has_permission,
    is_action_allowed_for_key,
    is_controller_allowed_for_key,
)
from src.actions import get_action_config, get_controller_config, discover_actions
from src.executor import ActionExecutor
from src.cooldown import CooldownTracker
from src.ratelimit import RateLimiter
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

executor = ActionExecutor()

COOLDOWN_STATE_PATH = os.path.join(os.path.dirname(__file__), "../logs/cooldowns.json")
cooldown_tracker = CooldownTracker(COOLDOWN_STATE_PATH)

RATE_LIMIT_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "../config/rate_limits.yaml"
)
rate_limiter = RateLimiter(RATE_LIMIT_CONFIG_PATH)

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
        config_actions = yaml.safe_load(f) or {}
    # Merge, giving priority to the explicit entries in config/actions.yaml
    merged = {**discovered, **config_actions.get("actions", {})}

    import src.actions

    src.actions.set_merged_actions(merged)
    _load_approval_queue()
    yield
    # Place any shutdown logic here


app = FastAPI(lifespan=lifespan)
app.add_middleware(APIKeyAuthMiddleware)


@app.get("/health")
async def health(request: Request):
    logger.info(f"Health check from {request.client.host}")
    return {"status": "ok", "version": os.getenv("API_VERSION", "0.1.0")}


@app.get("/live")
async def liveness_probe():
    """Kubernetes/Swarm liveness probe endpoint (no auth)."""
    return {"status": "live", "version": os.getenv("API_VERSION", "0.1.0")}


@app.get("/ready")
async def readiness_probe():
    """Kubernetes/Swarm readiness probe endpoint (no auth)."""
    # Optionally, add checks for DB, config, etc. For now, always ready.
    return {"status": "ready", "version": os.getenv("API_VERSION", "0.1.0")}


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


# Approval queue. Kept in memory for fast reads, but persisted to disk on
# every mutation so pending (and recent) approvals survive a process
# restart or pod reschedule instead of silently vanishing.
approval_queue = []
approval_lock = Lock()

APPROVALS_STATE_PATH = os.path.join(os.path.dirname(__file__), "../logs/approvals.json")
# Approved/rejected entries beyond this count are dropped on save - their
# permanent record already lives in the audit log, so the queue only needs
# to keep recent history bounded rather than growing forever. Pending
# entries are never dropped.
MAX_PROCESSED_APPROVALS = 500

# Approval entry structure:
# {
#   "id": <unique>,
#   "payload": <WebhookPayload dict>,
#   "status": "pending"|"approved"|"rejected",
#   "result": None|dict,
#   "requested_by": <api key>,
#   "role": <requester role>,
#   "controller": <controller name>,
#   "approved_by": <api key>,      # set once processed
#   "approver_role": <role>,       # set once processed
# }
import uuid


def _load_approval_queue():
    """Populate approval_queue from disk at startup, if a prior run left one."""
    if not os.path.exists(APPROVALS_STATE_PATH):
        return
    try:
        with open(APPROVALS_STATE_PATH) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Failed to load persisted approval queue, starting empty: {e}")
        return
    if isinstance(data, list):
        with approval_lock:
            approval_queue.extend(data)
        logger.info(f"Loaded {len(data)} persisted approval(s) from disk")


def _prune_approval_queue_locked():
    """
    Caller must hold approval_lock. Drops the oldest processed entries
    beyond MAX_PROCESSED_APPROVALS, keeping every pending entry regardless
    of count - it's still actionable work, not history.
    """
    processed_positions = [
        i for i, e in enumerate(approval_queue) if e["status"] != "pending"
    ]
    excess = len(processed_positions) - MAX_PROCESSED_APPROVALS
    if excess > 0:
        drop = set(processed_positions[:excess])
        approval_queue[:] = [e for i, e in enumerate(approval_queue) if i not in drop]


def _save_approval_queue_locked():
    """
    Caller must hold approval_lock. Writes to a temp file and renames it
    into place so a crash mid-write can't leave a truncated/corrupt state
    file behind.
    """
    _prune_approval_queue_locked()
    tmp_path = f"{APPROVALS_STATE_PATH}.tmp"
    try:
        with open(tmp_path, "w") as f:
            json.dump(approval_queue, f)
        os.replace(tmp_path, APPROVALS_STATE_PATH)
    except OSError as e:
        logger.error(f"Failed to persist approval queue: {e}")


def _find_approval_entry_locked(entry_id):
    """Caller must hold approval_lock."""
    for entry in approval_queue:
        if entry["id"] == entry_id:
            return entry
    return None


def get_approval_entry(entry_id):
    with approval_lock:
        return _find_approval_entry_locked(entry_id)


def cooldown_key_for(
    action_config: dict, event_type: str, controller_name: str, params: dict
) -> str:
    """
    Cooldown is scoped to (event_type, controller, optional dedup value)
    so e.g. restarting nginx on host A doesn't block restarting nginx on
    host B. The dedup value comes from whichever parameter an action
    names via `cooldown_key_param` in config/actions.yaml (e.g.
    "service_name"); actions that don't configure one are deduped just by
    (event_type, controller).
    """
    dedup_param = action_config.get("cooldown_key_param")
    dedup_value = params.get(dedup_param) if dedup_param else None
    return cooldown_tracker.make_key(
        event_type,
        controller_name,
        str(dedup_value) if dedup_value is not None else None,
    )


def cooldown_block_audit_entry(
    event_type: str, controller_name: str, params: dict, api_key, role, dry_run: bool
) -> dict:
    return {
        "user": api_key,
        "role": role,
        "action": event_type,
        "controller": controller_name,
        "controller_type": None,
        "parameters": params,
        "execution": {"success": False, "error": "blocked-by-cooldown"},
        "client_ip": None,
        "dry_run": dry_run,
        "blocked_reason": "cooldown",
    }


def cooldown_block_response(event_type: str, controller_name: str, remaining: float):
    detail = (
        f"Action '{event_type}' on controller '{controller_name}' is in cooldown "
        f"for {remaining:.0f} more second(s)"
    )
    return JSONResponse(
        status_code=409,
        content={"detail": detail, "cooldown_remaining_seconds": round(remaining, 1)},
    )


def rate_limit_block_audit_entry(
    event_type: Optional[str], api_key, role, params: Optional[dict]
) -> dict:
    return {
        "user": api_key,
        "role": role,
        "action": event_type,
        "controller": None,
        "controller_type": None,
        "parameters": params,
        "execution": {"success": False, "error": "blocked-by-rate-limit"},
        "client_ip": None,
        "dry_run": None,
        "blocked_reason": "rate_limit",
    }


def rate_limit_block_response(retry_after: float):
    detail = f"Rate limit exceeded, retry in {retry_after:.0f} second(s)"
    return JSONResponse(
        status_code=429,
        content={"detail": detail, "retry_after_seconds": round(retry_after, 1)},
        headers={"Retry-After": str(int(retry_after) + 1)},
    )


def is_local_controller(controller_config: dict) -> bool:
    """
    True for controllers Auto-Healer should run against directly on this
    host (type: local, or an ansible controller whose host is this
    machine). Everything else is reached over SSH via executor.run_remote.
    """
    if controller_config.get("type") == "local":
        return True
    return controller_config.get("host") in (None, "", "localhost", "127.0.0.1")


NO_EXECUTABLE_ERROR = "No playbook, script, command, or kube_action defined for action"


def execute_action(
    action_config: dict, controller_config: dict, params: dict, dry_run: bool
):
    """
    Dispatch an action to the right ActionExecutor method based on the
    controller it's targeting. Returns None if the action defines none of
    playbook/script/command/kube_action. Shared by /webhook and the
    approval-execution path so the two can't drift.
    """
    controller_name = (
        controller_config.get("host")
        or controller_config.get("api_server")
        or ("in-cluster" if controller_config.get("in_cluster") else "local")
    )
    if controller_config.get("type") == "kubeapi":
        logger.info(
            f"Executing kube_action '{action_config.get('kube_action')}' via "
            f"controller '{controller_name}' with params {params} (dry_run={dry_run})"
        )
        return executor.run_kube_action(
            controller_config, action_config, params, dry_run=dry_run
        )
    if not is_local_controller(controller_config):
        logger.info(
            f"Executing action remotely via controller '{controller_name}' "
            f"with params {params} (dry_run={dry_run})"
        )
        return executor.run_remote(
            controller_config, action_config, params, dry_run=dry_run
        )
    if "playbook" in action_config:
        logger.info(
            f"Executing playbook '{action_config['playbook']}' locally "
            f"with params {params} (dry_run={dry_run})"
        )
        return executor.run_playbook(action_config["playbook"], params, dry_run=dry_run)
    if "script" in action_config:
        args = [str(v) for v in params.values()] if params else None
        logger.info(
            f"Executing script '{action_config['script']}' locally "
            f"with args {args} (dry_run={dry_run})"
        )
        return executor.run_script(action_config["script"], args, dry_run=dry_run)
    if "command" in action_config:
        logger.info(
            f"Executing command '{action_config['command']}' locally "
            f"with params {params} (dry_run={dry_run})"
        )
        return executor.run_command(action_config["command"], params, dry_run=dry_run)
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

    # Caller-level rate limit: checked before anything else, including
    # whether event_type is even a real action, so garbage/typo payloads
    # can't be used to bypass throttling.
    caller_retry_after = rate_limiter.check(
        f"caller:{api_key}", rate_limiter.limit_for_role(role)
    )
    if caller_retry_after is not None:
        write_audit_log(
            rate_limit_block_audit_entry(event_type, api_key, role, payload.parameters)
        )
        return rate_limit_block_response(caller_retry_after)

    action_config = get_action_config(event_type)
    if not action_config:
        return JSONResponse(
            status_code=400, content={"detail": "Unknown action/event_type"}
        )

    # Action-level rate limit: protects a specific sensitive action across
    # all callers, independent of any single caller's own limit.
    action_retry_after = rate_limiter.check(
        f"action:{event_type}", rate_limiter.limit_for_action(event_type)
    )
    if action_retry_after is not None:
        write_audit_log(
            rate_limit_block_audit_entry(event_type, api_key, role, payload.parameters)
        )
        return rate_limit_block_response(action_retry_after)

    # Role-level gate: can this role trigger actions at all? (readonly
    # cannot - it's audit_read/approvals_read only.) Checked after both
    # rate limits so a role mismatch still consumes the caller's rate
    # budget rather than offering an unlimited free 403 to spam.
    if not has_permission(role, "execute_actions"):
        return JSONResponse(
            status_code=403,
            content={"detail": "Executing actions is not permitted for your role"},
        )
    # Key-level gate: this specific API key may be scoped to a subset of
    # actions on top of whatever its role permits (see config/auth.yaml).
    if not is_action_allowed_for_key(api_key, event_type):
        return JSONResponse(
            status_code=403,
            content={
                "detail": f"Action '{event_type}' is not permitted for your API key"
            },
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
    if not is_controller_allowed_for_key(api_key, controller_name):
        detail = f"Controller '{controller_name}' is not permitted for your API key"
        return JSONResponse(status_code=403, content={"detail": detail})
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
            _save_approval_queue_locked()
        logger.info(f"Action '{event_type}' queued for approval (id={entry_id})")
        return {
            "approval_id": entry_id,
            "status": "pending",
            "detail": "Action requires approval before execution.",
        }
    # Cooldown: skip entirely for dry_run, which never touches real
    # infrastructure and so has nothing to protect against.
    cooldown_seconds = action_config.get("cooldown_seconds", 0)
    cd_key = cooldown_key_for(action_config, event_type, controller_name, params)
    if not dry_run and cooldown_seconds:
        remaining = cooldown_tracker.seconds_remaining(cd_key, cooldown_seconds)
        if remaining is not None:
            write_audit_log(
                cooldown_block_audit_entry(
                    event_type, controller_name, params, api_key, role, dry_run
                )
            )
            return cooldown_block_response(event_type, controller_name, remaining)

    # Dry-run support
    exec_result = execute_action(action_config, controller_config, params, dry_run)
    if exec_result is None:
        logger.error(f"No executable defined for action '{event_type}'")
        return JSONResponse(
            status_code=400,
            content={"detail": NO_EXECUTABLE_ERROR},
        )
    if not dry_run and cooldown_seconds:
        # Record on any real attempt, success or failure - a failing
        # target retried in a tight loop is exactly the flapping scenario
        # cooldown exists to prevent, not just a repeated success.
        cooldown_tracker.record(cd_key)
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
def list_approvals(request: Request):
    api_key = request.headers.get("x-api-key")
    role = get_role_from_api_key(api_key)
    if not has_permission(role, "approvals_read"):
        return JSONResponse(status_code=403, content={"detail": "Forbidden"})
    with approval_lock:
        return [
            {k: v for k, v in entry.items() if k != "result"}
            for entry in approval_queue
        ]


@app.post("/approvals/{approval_id}/approve")
def approve_approval(approval_id: str, request: Request):
    api_key = request.headers.get("x-api-key")
    approver_role = get_role_from_api_key(api_key)
    if not has_permission(approver_role, "approve_actions"):
        return JSONResponse(
            status_code=403,
            content={"detail": "Approving actions is not permitted for your role"},
        )
    with approval_lock:
        entry = _find_approval_entry_locked(approval_id)
        if not entry:
            return JSONResponse(
                status_code=404, content={"detail": "Approval not found"}
            )
        if entry["status"] != "pending":
            return JSONResponse(
                status_code=400, content={"detail": f"Already {entry['status']}"}
            )
        if entry["requested_by"] == api_key:
            return JSONResponse(
                status_code=403,
                content={"detail": "You cannot approve your own request"},
            )
        payload = WebhookPayload(**entry["payload"])
        event_type = payload.event_type
        action_config = get_action_config(event_type)
        controller_name = payload.controller_override or action_config.get(
            "default_controller"
        )
        controller_config = get_controller_config(controller_name)
        # Re-validate the ORIGINAL REQUESTER's permission to execute
        # this action/controller, not the approver's - approving a
        # request certifies sign-off on something the requester was
        # themselves allowed to ask for, it doesn't grant new rights.
        # Re-checked here (not just at queue time in /webhook) in case
        # config/auth.yaml changed while this entry sat pending.
        requester_key = entry["requested_by"]
        requester_role = entry["role"]
        if (
            not has_permission(requester_role, "execute_actions")
            or not is_action_allowed_for_key(requester_key, event_type)
            or not is_controller_allowed_for_key(requester_key, controller_name)
        ):
            reason = (
                "Requester is no longer permitted to execute this action/controller"
            )
            entry["status"] = "rejected"
            entry["result"] = {"error": reason}
            _save_approval_queue_locked()
            return JSONResponse(status_code=403, content={"detail": reason})
        params = action_config.get("parameters", {}).copy()
        params.update(payload.parameters or {})
        dry_run = getattr(payload, "dry_run", False)
        cooldown_seconds = action_config.get("cooldown_seconds", 0)
        cd_key = cooldown_key_for(action_config, event_type, controller_name, params)
        if not dry_run and cooldown_seconds:
            remaining = cooldown_tracker.seconds_remaining(cd_key, cooldown_seconds)
            if remaining is not None:
                # Leave the entry pending - the cooldown will clear on its
                # own and the approver can retry, nothing was consumed.
                write_audit_log(
                    cooldown_block_audit_entry(
                        event_type,
                        controller_name,
                        params,
                        api_key,
                        approver_role,
                        dry_run,
                    )
                )
                return cooldown_block_response(event_type, controller_name, remaining)
        # Claim it immediately, while still holding the lock, so a
        # concurrent approve/reject on the same entry can't also pass the
        # pending check and double-execute it.
        entry["status"] = "approved"
        entry["approved_by"] = api_key
        entry["approver_role"] = approver_role
        _save_approval_queue_locked()

    # Execute outside the lock - this can take a while (SSH, ansible-playbook)
    # and shouldn't block /approvals reads or other approve/reject calls.
    exec_result = execute_action(action_config, controller_config, params, dry_run)
    if exec_result is None:
        with approval_lock:
            entry["status"] = "rejected"
            entry["result"] = {"error": NO_EXECUTABLE_ERROR}
            _save_approval_queue_locked()
        return JSONResponse(
            status_code=400,
            content={"detail": NO_EXECUTABLE_ERROR},
        )
    if not dry_run and cooldown_seconds:
        cooldown_tracker.record(cd_key)
    with approval_lock:
        entry["result"] = exec_result.as_dict()
        _save_approval_queue_locked()
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
        "approved_by": api_key,
        "approver_role": approver_role,
    }
    write_audit_log(audit_entry)
    return {"status": "approved", "result": exec_result.as_dict()}


@app.post("/approvals/{approval_id}/reject")
def reject_approval(approval_id: str, request: Request):
    api_key = request.headers.get("x-api-key")
    approver_role = get_role_from_api_key(api_key)
    if not has_permission(approver_role, "approve_actions"):
        return JSONResponse(
            status_code=403,
            content={"detail": "Rejecting actions is not permitted for your role"},
        )
    with approval_lock:
        entry = _find_approval_entry_locked(approval_id)
        if not entry:
            return JSONResponse(
                status_code=404, content={"detail": "Approval not found"}
            )
        if entry["status"] != "pending":
            return JSONResponse(
                status_code=400, content={"detail": f"Already {entry['status']}"}
            )
        if entry["requested_by"] == api_key:
            return JSONResponse(
                status_code=403,
                content={"detail": "You cannot reject your own request"},
            )
        entry["status"] = "rejected"
        entry["result"] = {"error": "Rejected by approver"}
        entry["approved_by"] = api_key
        entry["approver_role"] = approver_role
        _save_approval_queue_locked()
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
        "approved_by": api_key,
        "approver_role": approver_role,
    }
    write_audit_log(audit_entry)
    return {"status": "rejected"}
