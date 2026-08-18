import logging
import os
import time
from collections import deque
from threading import Lock
from typing import Deque, Dict, Optional

import yaml

logger = logging.getLogger("autoheal.ratelimit")

DEFAULT_REQUESTS_PER_MINUTE = 60
WINDOW_SECONDS = 60


class RateLimiter:
    """
    In-memory sliding-window rate limiter for /webhook. Unlike
    CooldownTracker, this is intentionally NOT persisted across restarts:
    it protects the API itself from abuse/flooding, not infrastructure
    from repeated remediation, so a restart naturally resetting counters
    is fine - there's no safety property to preserve across it.

    Config (config/rate_limits.yaml) is read once at construction, not
    re-read per request - unlike config/auth.yaml and config/actions.yaml
    elsewhere in this codebase, which are re-parsed from disk on every
    single check. That pattern is harmless at low request volume but
    directly counterproductive for a rate limiter, which exists to be
    cheap to check on every request.
    """

    def __init__(self, config_path: str):
        self.config = self._load_config(config_path)
        self.lock = Lock()
        self._hits: Dict[str, Deque[float]] = {}

    @staticmethod
    def _load_config(config_path: str) -> dict:
        if not os.path.exists(config_path):
            return {}
        try:
            with open(config_path) as f:
                return yaml.safe_load(f) or {}
        except (yaml.YAMLError, OSError) as e:
            logger.error(f"Failed to load rate limit config, using defaults: {e}")
            return {}

    def limit_for_role(self, role: Optional[str]) -> int:
        """The per-minute limit for a caller with this role."""
        per_role = self.config.get("per_role") or {}
        if role and role in per_role:
            return per_role[role].get(
                "requests_per_minute", DEFAULT_REQUESTS_PER_MINUTE
            )
        return (self.config.get("default") or {}).get(
            "requests_per_minute", DEFAULT_REQUESTS_PER_MINUTE
        )

    def limit_for_action(self, event_type: str) -> Optional[int]:
        """
        The per-minute limit for this action across all callers, or None
        if the action has no configured limit (unlimited by this check).
        """
        per_action = self.config.get("per_action") or {}
        entry = per_action.get(event_type)
        return entry.get("requests_per_minute") if entry else None

    def check(
        self, key: str, limit: Optional[int], window_seconds: int = WINDOW_SECONDS
    ) -> Optional[float]:
        """
        Atomically checks and records one call against `key`. Returns
        None if it's allowed (and the call IS recorded), or the number of
        seconds until the caller should retry if it's over `limit` calls
        per `window_seconds` (in which case nothing is recorded - a
        blocked call doesn't itself count against the window).
        """
        if not limit or limit <= 0:
            return None
        now = time.time()
        with self.lock:
            hits = self._hits.setdefault(key, deque())
            cutoff = now - window_seconds
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= limit:
                retry_after = hits[0] + window_seconds - now
                return max(retry_after, 0.1)
            hits.append(now)
            return None
