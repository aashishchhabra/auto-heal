"""
Tamper-evident, hash-chained audit log storage, plus optional best-effort
shipping of each entry to an external log platform (syslog and/or a
generic HTTP JSON sink), configured via config/audit.yaml.

"Immutable" here means tamper-EVIDENT, not tamper-PROOF: nothing in this
process stops someone with filesystem access from editing logs/audit.log
directly, but doing so breaks the SHA-256 hash chain in a way verify()
detects deterministically - the same technique AWS CloudTrail's log file
integrity validation and countless other audit systems use, without
requiring an external ledger or database. Real tamper-proofing (WORM
storage, an append-only external system, a dedicated SIEM) is the
deployer's job; shipping a copy to one is exactly what the sinks below
are for, which is why they matter as much as the hash chain itself.

Shipping is deliberately a side channel: AuditShipper.ship() catches and
logs every failure rather than raising. logs/audit.log (written by
AuditChain) is the durable, authoritative record; a downed syslog relay
or Elasticsearch cluster must never block a remediation action or the
request that triggered it.
"""

import hashlib
import json
import logging
import logging.handlers
import os
import socket
from threading import Lock
from typing import Any, Dict, Optional, Tuple

import requests
import yaml

from src.vault import resolve_vault_ref, VaultUnavailableError

logger = logging.getLogger("autoheal.audit")

GENESIS_HASH = "0" * 64
SERVICE_NAME = "auto-healer"


def _canonical(entry: Dict[str, Any]) -> str:
    """Deterministic JSON serialization - same entry always hashes the same way."""
    return json.dumps(entry, sort_keys=True, separators=(",", ":"), default=str)


def _hash_entry(entry_without_hash: Dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(entry_without_hash).encode("utf-8")).hexdigest()


def _read_last_line(path: str, chunk_size: int = 65536) -> Optional[str]:
    """
    Returns the last non-empty line of `path`, or None if it doesn't
    exist or is empty. Reads backward in bounded chunks rather than
    loading the whole file - an audit log can grow large over a
    deployment's lifetime, and this runs on every process start.
    """
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        file_size = f.tell()
        if file_size == 0:
            return None
        data = b""
        pos = file_size
        while pos > 0:
            read_size = min(chunk_size, pos)
            pos -= read_size
            f.seek(pos)
            data = f.read(read_size) + data
            stripped = data.rstrip(b"\n")
            if b"\n" in stripped:
                return stripped.rsplit(b"\n", 1)[-1].decode("utf-8")
            if pos == 0:
                # Whole file is one line (or empty after stripping).
                return stripped.decode("utf-8") if stripped else None
    return None


class AuditChain:
    """
    Appends JSON-lines entries to `path`, each one cryptographically
    linked to the one before it via `sequence` (monotonic int),
    `prev_hash` (the previous entry's `entry_hash`), and `entry_hash`
    (SHA-256 of this entry's own fields + prev_hash). Editing, deleting,
    or reordering any past line changes its entry_hash and breaks every
    link after it - detectable by verify() without needing the original
    unmodified copy.

    Chain state (the last sequence/hash written) is deliberately NOT
    cached in memory across calls - it's re-derived from the file's own
    last line on every append, via a cheap bounded tail read rather than
    a whole-file scan. This costs one extra bounded read per write, but
    makes the chain self-healing if the file changes out from under this
    process in a way that isn't a normal append - external log rotation,
    a truncation, or (in tests) a fixture wiping the file between runs.
    A cached "last sequence was N" would otherwise keep incrementing
    from a link that no longer exists at the start of a rotated-away
    file, silently producing a chain that looks internally consistent
    but doesn't actually match what's on disk.

    If the last line can't be parsed as a chained entry - most commonly
    because it predates this feature, but also covering genuine
    corruption or a mid-write crash - a new chain segment simply starts
    back at sequence=1 with prev_hash=GENESIS_HASH, logged loudly rather
    than raised: refusing to write any further audit entries because of
    one unreadable prior line would fail every future action's audit
    trail, which is a worse outcome than a visible, explained segment
    boundary. verify() understands and reports these boundaries
    explicitly rather than treating them as tampering.
    """

    def __init__(self, path: str):
        self.path = path
        self._lock = Lock()

    def _current_state(self) -> Tuple[int, str]:
        last = _read_last_line(self.path)
        if last is None:
            return (0, GENESIS_HASH)
        try:
            parsed = json.loads(last)
            return (int(parsed["sequence"]), str(parsed["entry_hash"]))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            logger.warning(
                f"Last line of {self.path} isn't a valid hash-chained entry "
                f"({e}) - starting a new chain segment at sequence=1. This is "
                "expected once, right after upgrading from a pre-hash-chain "
                "audit.log; if it keeps happening, the file may be corrupted."
            )
            return (0, GENESIS_HASH)

    def append(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        """Adds chain fields to `entry`, writes it, and returns the finalized dict."""
        with self._lock:
            last_sequence, last_hash = self._current_state()
            sequence = last_sequence + 1
            chained = {**entry, "sequence": sequence, "prev_hash": last_hash}
            entry_hash = _hash_entry(chained)
            chained["entry_hash"] = entry_hash
            with open(self.path, "a") as f:
                f.write(json.dumps(chained) + "\n")
        return chained


def verify_chain(path: str) -> Dict[str, Any]:
    """
    Re-reads `path` front to back and checks every chained entry's
    entry_hash against a fresh recomputation, and that each entry's
    prev_hash/sequence correctly continue from the one before it.

    Lines with no `sequence`/`prev_hash`/`entry_hash` at all are treated
    as pre-chain legacy entries (counted, not verified - there's nothing
    to check them against).

    A line whose sequence resets to 1 with prev_hash == GENESIS_HASH is
    either the very first line of a brand new chain (normal, not
    reported) or a second independently-anchored segment immediately
    following at least one already-verified chained entry - the shape
    you'd get from concatenating rotated-out history
    (audit.log.1, audit.log.2, ...) back together for a compliance
    review. Only the latter is recorded in `segment_boundaries`, since
    it's the case worth an operator's attention; both are accepted as
    legitimate, not flagged as tampering. Anything else that doesn't
    line up - a lower sequence, a mismatched prev_hash, one missing from
    the middle - is: verify stops there and reports the first bad line.
    """
    result = {
        "ok": True,
        "entries_checked": 0,
        "legacy_entries": 0,
        "segment_boundaries": [],
        "first_broken_line": None,
        "detail": None,
    }
    if not os.path.exists(path):
        return result

    prev_sequence = None
    prev_hash = None
    with open(path) as f:
        for line_number, raw_line in enumerate(f, start=1):
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                entry = json.loads(raw_line)
            except json.JSONDecodeError as e:
                result["ok"] = False
                result["first_broken_line"] = line_number
                result["detail"] = f"Line {line_number} is not valid JSON: {e}"
                return result

            if not {"sequence", "prev_hash", "entry_hash"} <= entry.keys():
                result["legacy_entries"] += 1
                continue

            sequence = entry["sequence"]
            claimed_prev_hash = entry["prev_hash"]
            claimed_hash = entry["entry_hash"]
            recomputed = _hash_entry(
                {k: v for k, v in entry.items() if k != "entry_hash"}
            )
            if recomputed != claimed_hash:
                result["ok"] = False
                result["first_broken_line"] = line_number
                result["detail"] = (
                    f"Line {line_number} (sequence={sequence}): stored entry_hash "
                    "doesn't match its own content - entry was modified after "
                    "being written."
                )
                return result

            # A fresh restart mid-file (a real segment boundary) and the
            # very first line of a brand new chain look identical
            # (sequence=1, prev_hash=GENESIS_HASH) - only the former
            # actually has a prior segment to have broken away from, so
            # only that one gets reported. Otherwise every healthy,
            # never-rotated chain would show a "boundary" on line 1.
            is_new_segment = sequence == 1 and claimed_prev_hash == GENESIS_HASH
            is_continuation = (
                prev_sequence is not None
                and sequence == prev_sequence + 1
                and claimed_prev_hash == prev_hash
            )
            if is_new_segment:
                if prev_sequence is not None:
                    result["segment_boundaries"].append(line_number)
            elif not is_continuation:
                result["ok"] = False
                result["first_broken_line"] = line_number
                result["detail"] = (
                    f"Line {line_number} (sequence={sequence}): does not "
                    "continue from the previous chained entry - a line was "
                    "deleted, reordered, or inserted."
                )
                return result

            result["entries_checked"] += 1
            prev_sequence = sequence
            prev_hash = claimed_hash
    return result


def to_ecs(entry: Dict[str, Any]) -> Dict[str, Any]:
    """
    Maps one finalized audit entry (as returned by AuditChain.append) to
    an Elastic Common Schema (ECS) document -
    https://www.elastic.co/guide/en/ecs/current/index.html - so it's
    immediately useful to Elasticsearch/Kibana (and any other ECS-aware
    consumer: Logstash, Fluentd's ECS output, Splunk's CIM mapping is
    close enough to translate) without a bespoke index mapping on the
    receiving end. `event.sequence` and `event.hash` are real ECS
    fields defined for exactly this purpose (a per-source monotonic
    counter and an integrity hash of the raw event). Fields with no ECS
    equivalent are namespaced under `auto_healer.*`, ECS's documented
    convention for custom extensions, rather than invented as top-level
    fields that might collide with a future ECS version.
    """
    execution = entry.get("execution") or {}
    success = execution.get("success")
    outcome = "unknown" if success is None else ("success" if success else "failure")
    doc = {
        "@timestamp": entry.get("timestamp"),
        "event": {
            "kind": "event",
            "category": ["process"],
            "type": ["denied"] if entry.get("blocked_reason") else ["change"],
            "action": entry.get("action"),
            "outcome": outcome,
            "reason": entry.get("blocked_reason"),
            "sequence": entry.get("sequence"),
            "hash": entry.get("entry_hash"),
        },
        "user": {
            "name": entry.get("user"),
            "roles": [entry["role"]] if entry.get("role") else [],
        },
        "source": {"ip": entry["client_ip"]} if entry.get("client_ip") else None,
        "service": {"name": SERVICE_NAME, "type": SERVICE_NAME},
        "message": _summary_message(entry),
        "auto_healer": {
            "controller": entry.get("controller"),
            "controller_type": entry.get("controller_type"),
            "parameters": entry.get("parameters"),
            "execution": execution,
            "dry_run": entry.get("dry_run"),
            "approval_id": entry.get("approval_id"),
            "approval_status": entry.get("approval_status"),
            "approved_by": entry.get("approved_by"),
            "approver_role": entry.get("approver_role"),
            "prev_hash": entry.get("prev_hash"),
        },
    }
    return {k: v for k, v in doc.items() if v is not None}


def _summary_message(entry: Dict[str, Any]) -> str:
    action = entry.get("action") or "unknown-action"
    controller = entry.get("controller") or "unknown-controller"
    if entry.get("blocked_reason"):
        reason = entry["blocked_reason"]
        return f"action '{action}' on controller '{controller}' blocked ({reason})"
    outcome = "succeeded" if (entry.get("execution") or {}).get("success") else "failed"
    return f"action '{action}' on controller '{controller}' {outcome}"


class AuditShipper:
    """
    Best-effort mirror of each finalized audit entry to external log
    platforms, configured via config/audit.yaml (see that file for the
    full shape). Both sinks are opt-in and disabled by default - a
    deployment with no config/audit.yaml, or one with everything
    disabled, behaves exactly as if this class didn't exist.

    - syslog: RFC 3164 BSD syslog over UDP or TCP (stdlib
      logging.handlers.SysLogHandler), the lowest-common-denominator
      protocol nearly every log collector/SIEM can ingest directly
      (rsyslog, Logstash's syslog input, Graylog, Splunk, a Fluentd/Fluent
      Bit syslog listener). TLS isn't supported by the stdlib handler; if
      you need encryption in transit, either point this at a local relay
      (rsyslog/promtail) that forwards on your behalf, or use the http
      sink below instead, which is plain HTTPS.
    - http: a single JSON POST/PUT per entry to any HTTP endpoint - the
      most direct path to Elasticsearch itself (`POST <index>/_doc`),
      but equally usable for a Logstash/Fluent Bit HTTP input, Splunk
      HEC, Datadog's log intake, or a custom webhook. Header values
      support the same `vault:<path>#<field>` syntax used everywhere
      else in this codebase, for an API key/bearer token that
      shouldn't live in plaintext config.
    """

    def __init__(self, config_path: str):
        self.config_path = config_path
        self._config = self._load_config()
        self._syslog_handler = None
        self._syslog_handler_key = None

    def _load_config(self) -> dict:
        if not os.path.exists(self.config_path):
            return {}
        try:
            with open(self.config_path) as f:
                return yaml.safe_load(f) or {}
        except (yaml.YAMLError, OSError) as e:
            logger.error(
                f"Failed to load {self.config_path}, audit shipping disabled: {e}"
            )
            return {}

    def ship(self, entry: Dict[str, Any]) -> None:
        shipping = self._config.get("shipping") or {}
        syslog_cfg = shipping.get("syslog") or {}
        if syslog_cfg.get("enabled"):
            self._ship_syslog(entry, syslog_cfg)
        http_cfg = shipping.get("http") or {}
        if http_cfg.get("enabled"):
            self._ship_http(entry, http_cfg)

    def _get_syslog_handler(self, cfg: dict):
        key = (
            cfg.get("host", "localhost"),
            cfg.get("port", 514),
            cfg.get("protocol", "udp"),
        )
        if key == self._syslog_handler_key and self._syslog_handler is not None:
            return self._syslog_handler
        protocol = key[2]
        if protocol not in ("udp", "tcp"):
            raise ValueError(
                f"Unsupported syslog protocol '{protocol}' (only udp/tcp are "
                "supported - see AuditShipper's docstring for TLS options)"
            )
        socktype = socket.SOCK_STREAM if protocol == "tcp" else socket.SOCK_DGRAM
        facility = logging.handlers.SysLogHandler.facility_names.get(
            cfg.get("facility", "local0"), logging.handlers.SysLogHandler.LOG_LOCAL0
        )
        handler = logging.handlers.SysLogHandler(
            address=(key[0], key[1]), facility=facility, socktype=socktype
        )
        self._syslog_handler = handler
        self._syslog_handler_key = key
        return handler

    def _ship_syslog(self, entry: Dict[str, Any], cfg: dict) -> None:
        try:
            handler = self._get_syslog_handler(cfg)
            message = json.dumps(to_ecs(entry))
            record = logging.LogRecord(
                name="autoheal.audit",
                level=logging.INFO,
                pathname=__file__,
                lineno=0,
                msg=message,
                args=None,
                exc_info=None,
            )
            handler.emit(record)
        except Exception as e:
            logger.error(f"Failed to ship audit entry to syslog: {e}")

    def _ship_http(self, entry: Dict[str, Any], cfg: dict) -> None:
        url = cfg.get("url")
        if not url:
            logger.error("Audit HTTP shipping is enabled but has no 'url' configured")
            return
        try:
            headers = {"Content-Type": "application/json"}
            for name, value in (cfg.get("headers") or {}).items():
                headers[name] = resolve_vault_ref(value)
            resp = requests.request(
                cfg.get("method", "POST"),
                url,
                json=to_ecs(entry),
                headers=headers,
                timeout=cfg.get("timeout_seconds", 5),
            )
            if resp.status_code >= 300:
                logger.error(
                    f"Audit HTTP shipping got {resp.status_code} from {url}: "
                    f"{resp.text[:200]}"
                )
        except VaultUnavailableError as e:
            logger.error(
                f"Failed to resolve audit HTTP shipping header from Vault: {e}"
            )
        except requests.RequestException as e:
            logger.error(f"Failed to ship audit entry via HTTP to {url}: {e}")
