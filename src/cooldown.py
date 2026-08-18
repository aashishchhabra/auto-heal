import json
import logging
import os
import time
from threading import Lock
from typing import Dict, Optional

logger = logging.getLogger("autoheal.cooldown")

# Safety cap on how long a stale cooldown record is kept even if nothing
# ever checks it again. Real cooldowns are expected to be minutes, not
# days - this just bounds the state file's growth over a long-running
# process without needing to know any particular action's cooldown_seconds
# at prune time.
MAX_COOLDOWN_RETENTION_SECONDS = 24 * 60 * 60


class CooldownTracker:
    """
    Tracks the last execution time of an action, keyed by
    (event_type, controller, optional per-action dedup parameter), so a
    flapping alert can't re-trigger the same remediation against the same
    target faster than the action's configured cooldown_seconds allows.

    Persisted to disk (atomic write: temp file + os.replace, same pattern
    as the approval queue) so the cooldown clock survives a process
    restart or pod reschedule - the whole point of a cooldown is to
    protect infrastructure from repeated remediation, and a restart in the
    middle of a flap shouldn't reset that protection.
    """

    def __init__(self, state_path: str):
        self.state_path = state_path
        self.lock = Lock()
        self._last_run: Dict[str, float] = {}
        self._load()

    @staticmethod
    def make_key(
        event_type: str, controller_name: str, dedup_value: Optional[str]
    ) -> str:
        return f"{event_type}|{controller_name}|{dedup_value or ''}"

    def _load(self):
        """Populate state from disk at startup, if a prior run left one."""
        if not os.path.exists(self.state_path):
            return
        try:
            with open(self.state_path) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error(
                f"Failed to load persisted cooldown state, starting empty: {e}"
            )
            return
        if isinstance(data, dict):
            self._last_run.update(data)
            logger.info(f"Loaded {len(data)} persisted cooldown record(s) from disk")

    def _prune_locked(self):
        """Caller must hold self.lock. Drops records past the safety cap."""
        cutoff = time.time() - MAX_COOLDOWN_RETENTION_SECONDS
        stale_keys = [k for k, ts in self._last_run.items() if ts < cutoff]
        for k in stale_keys:
            del self._last_run[k]

    def _save_locked(self):
        """
        Caller must hold self.lock. Writes to a temp file and renames it
        into place so a crash mid-write can't leave a truncated/corrupt
        state file behind.
        """
        self._prune_locked()
        tmp_path = f"{self.state_path}.tmp"
        try:
            with open(tmp_path, "w") as f:
                json.dump(self._last_run, f)
            os.replace(tmp_path, self.state_path)
        except OSError as e:
            logger.error(f"Failed to persist cooldown state: {e}")

    def seconds_remaining(self, key: str, cooldown_seconds: float) -> Optional[float]:
        """
        Returns how many seconds are left in the cooldown for `key`, or
        None if it's not currently in cooldown (never recorded, or the
        cooldown window has already elapsed). `cooldown_seconds` is
        supplied by the caller (from the action's current config) rather
        than stored per-record, so lowering an action's cooldown_seconds
        in config takes effect immediately for existing records.
        """
        if not cooldown_seconds:
            return None
        with self.lock:
            last_run = self._last_run.get(key)
        if last_run is None:
            return None
        remaining = cooldown_seconds - (time.time() - last_run)
        return remaining if remaining > 0 else None

    def record(self, key: str):
        """Mark `key` as having just executed, starting its cooldown now."""
        with self.lock:
            self._last_run[key] = time.time()
            self._save_locked()
