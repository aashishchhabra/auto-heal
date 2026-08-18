"""
Multi-channel notifications for Auto-Healer: Slack, Teams, email, and the
two standard on-call escalation platforms, PagerDuty (Events API v2) and
Opsgenie (Alert API). All channels are opt-in via config/notifications.yaml
and disabled by default.

notify() is the single entry point everything else should call - it
computes an effective severity for the event, applies deduplication (so a
flapping action doesn't turn into a notification storm on top of the
already-throttled webhook calls that caused it), and fans out to whichever
channels this severity is routed to. Each channel's own send_*
method remains directly callable too (existing behavior, and how the test
suite exercises them individually) - notify() is a coordinator on top, not
a replacement.

Every send is best-effort: a channel misconfigured, unreachable, or
rejecting the request logs an error and returns False. Nothing here ever
raises into the caller - a broken PagerDuty integration must never block
the action whose outcome it's trying to report.
"""

import logging
import os
import smtplib
import time
from email.mime.text import MIMEText
from threading import Lock
from typing import Optional

import requests
import yaml

from src.vault import resolve_vault_ref, VaultUnavailableError

logger = logging.getLogger("autoheal.notifications")

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "../config/notifications.yaml")

SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}
DEFAULT_DEDUP_WINDOW_SECONDS = 300
PAGERDUTY_EVENTS_URL = "https://events.pagerduty.com/v2/enqueue"
OPSGENIE_ALERTS_URL = "https://api.opsgenie.com/v2/alerts"
SEVERITY_TO_PAGERDUTY = {"info": "info", "warning": "warning", "critical": "critical"}
SEVERITY_TO_OPSGENIE_PRIORITY = {"info": "P5", "warning": "P3", "critical": "P1"}


class NotificationSender:
    def __init__(self):
        self.config = self._load_config()
        # Slack
        self.slack_enabled = self.config.get("slack", {}).get("enabled", False)
        self.slack_url = self.config.get("slack", {}).get("webhook_url")
        self.slack_channel = self.config.get("slack", {}).get("channel")
        self.slack_username = self.config.get("slack", {}).get(
            "username", "AutoHealerBot"
        )
        self.slack_notify_on = self.config.get("slack", {}).get(
            "notify_on", ["success", "failure"]
        )
        # Teams
        self.teams_enabled = self.config.get("teams", {}).get("enabled", False)
        self.teams_url = self.config.get("teams", {}).get("webhook_url")
        self.teams_channel = self.config.get("teams", {}).get("channel")
        self.teams_notify_on = self.config.get("teams", {}).get(
            "notify_on", ["success", "failure"]
        )
        # Email (SMTP - stdlib only, no new dependency)
        email_cfg = self.config.get("email", {}) or {}
        self.email_enabled = email_cfg.get("enabled", False)
        self.email_smtp_host = email_cfg.get("smtp_host")
        self.email_smtp_port = email_cfg.get("smtp_port", 587)
        self.email_use_tls = email_cfg.get("use_tls", True)
        self.email_username = email_cfg.get("username")
        self.email_password = email_cfg.get("password")
        self.email_from = email_cfg.get("from_addr")
        self.email_to = email_cfg.get("to_addrs") or []
        self.email_notify_on = email_cfg.get("notify_on", ["success", "failure"])
        # PagerDuty (Events API v2) - pages a human, so success is
        # deliberately NOT in the default notify_on the way it is for
        # Slack/Teams/email; a team that wants "page on success too" has
        # to opt into that explicitly.
        pagerduty_cfg = self.config.get("pagerduty", {}) or {}
        self.pagerduty_enabled = pagerduty_cfg.get("enabled", False)
        self.pagerduty_routing_key = pagerduty_cfg.get("routing_key")
        self.pagerduty_notify_on = pagerduty_cfg.get("notify_on", ["failure"])
        # Opsgenie (Alert API) - same reasoning as PagerDuty.
        opsgenie_cfg = self.config.get("opsgenie", {}) or {}
        self.opsgenie_enabled = opsgenie_cfg.get("enabled", False)
        self.opsgenie_api_key = opsgenie_cfg.get("api_key")
        self.opsgenie_notify_on = opsgenie_cfg.get("notify_on", ["failure"])

        # Severity-based routing: {severity: [channel names]}. Empty/unset
        # means "no restriction" - every enabled channel gets every
        # notification, exactly the original (pre-routing) behavior.
        self.routing = self.config.get("routing") or {}

        # Deduplication: suppresses re-sending the same (action, controller,
        # status) notification within a window - independent of, and in
        # addition to, the cooldowns/rate limits that already throttle the
        # underlying webhook calls. In-memory only (like RateLimiter, not
        # persisted like CooldownTracker) since this is a noise concern, not
        # a safety one - losing dedup state on restart just means one extra
        # notification, not a missed safety check.
        dedup_cfg = self.config.get("dedup") or {}
        self.dedup_enabled = dedup_cfg.get("enabled", True)
        self.dedup_window_seconds = dedup_cfg.get(
            "window_seconds", DEFAULT_DEDUP_WINDOW_SECONDS
        )
        self._dedup_lock = Lock()
        self._dedup_seen = {}

        # Optional per-channel (or "default") message templates - a plain
        # str.format() string with fields: action, controller, user,
        # status, severity, details. Unconfigured channels keep their
        # existing built-in formatting exactly as before this existed.
        self.templates = self.config.get("templates") or {}

    def _load_config(self):
        if not os.path.exists(CONFIG_PATH):
            return {}
        with open(CONFIG_PATH) as f:
            return yaml.safe_load(f) or {}

    # ---------------------------------------------------------------
    # Coordination: severity, dedup, routing
    # ---------------------------------------------------------------

    @staticmethod
    def _effective_severity(base_severity: Optional[str], status: str) -> str:
        """
        `base_severity` is whatever the action itself declares (its
        `severity:` field in actions.yaml, or None). A failed execution is
        always bumped to at least "warning" - even a nominally low-severity
        action failing to auto-remediate is more worth a human's attention
        than one that succeeded.
        """
        base = base_severity if base_severity in SEVERITY_RANK else "info"
        if status == "failure" and SEVERITY_RANK[base] < SEVERITY_RANK["warning"]:
            base = "warning"
        return base

    def _is_duplicate(self, key: str) -> bool:
        if not self.dedup_enabled:
            return False
        now = time.time()
        with self._dedup_lock:
            last_sent = self._dedup_seen.get(key)
            if last_sent is not None and now - last_sent < self.dedup_window_seconds:
                return True
            self._dedup_seen[key] = now
            return False

    def _wants_channel(self, channel: str, severity: str) -> bool:
        if not self.routing:
            return True
        return channel in self.routing.get(severity, [])

    def _render(self, channel: str, default_fn, **fields) -> str:
        template = self.templates.get(channel) or self.templates.get("default")
        if not template:
            return default_fn()
        try:
            return template.format(**fields)
        except (KeyError, IndexError) as e:
            logger.error(f"Bad '{channel}' notification template ({e}), using default")
            return default_fn()

    def notify(
        self,
        action: str,
        controller: str,
        user: str,
        status: str,
        details: Optional[str] = None,
        severity: Optional[str] = None,
        dedup_key: Optional[str] = None,
    ) -> dict:
        """
        Single entry point for reporting one action's outcome. Computes the
        effective severity, applies deduplication, and calls every enabled
        channel that severity is routed to (or every enabled channel, if
        routing isn't configured). Returns {channel: bool} for whichever
        channels were attempted - never raises.
        """
        effective_severity = self._effective_severity(severity, status)
        key = dedup_key or f"{action}:{controller}:{status}"
        if self._is_duplicate(key):
            logger.info(f"Notification suppressed (deduplicated within window): {key}")
            return {}

        results = {}
        channels = {
            "slack": self.send_slack_notification,
            "teams": self.send_teams_notification,
            "email": self.send_email_notification,
            "pagerduty": self.send_pagerduty_notification,
            "opsgenie": self.send_opsgenie_notification,
        }
        for name, send in channels.items():
            if self._wants_channel(name, effective_severity):
                results[name] = send(
                    action,
                    controller,
                    user,
                    status,
                    details=details,
                    severity=effective_severity,
                )
        return results

    # ---------------------------------------------------------------
    # Channels
    # ---------------------------------------------------------------

    def send_slack_notification(
        self, action, controller, user, status, details=None, severity=None
    ):
        if not self.slack_enabled or not self.slack_url:
            return False
        if status not in self.slack_notify_on:
            return False

        def default_text():
            text = (
                f"*Auto-Healer Notification*\n*Action:* `{action}`\n"
                f"*Controller:* `{controller}`\n"
                f"*User:* `{user}`\n"
                f"*Status:* `{status.upper()}`"
            )
            if details:
                text += f"\n*Details:* {details}"
            return text

        text = self._render(
            "slack",
            default_text,
            action=action,
            controller=controller,
            user=user,
            status=status,
            severity=severity or "info",
            details=details or "",
        )
        color = getattr(self, "slack_color", "#439FE0")
        payload = {
            "channel": self.slack_channel,
            "username": self.slack_username,
            "attachments": [
                {
                    "color": color,
                    "text": text,
                    "mrkdwn_in": ["text"],
                }
            ],
        }
        try:
            resp = requests.post(self.slack_url, json=payload, timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    def send_teams_notification(
        self, action, controller, user, status, details=None, severity=None
    ):
        if not self.teams_enabled or not self.teams_url:
            return False
        if status not in self.teams_notify_on:
            return False

        def default_text():
            text = (
                f"**Auto-Healer Notification**\n**Action:** `{action}`\n"
                f"**Controller:** `{controller}`\n**User:** `{user}`\n"
                f"**Status:** `{status.upper()}`"
            )
            if details:
                text += f"\n**Details:** {details}"
            return text

        text = self._render(
            "teams",
            default_text,
            action=action,
            controller=controller,
            user=user,
            status=status,
            severity=severity or "info",
            details=details or "",
        )
        color = getattr(self, "teams_color", "0076D7")
        payload = {
            "@type": "MessageCard",
            "themeColor": color,
            "sections": [{"text": text}],
        }
        try:
            resp = requests.post(self.teams_url, json=payload, timeout=5)
            return resp.status_code in (200, 201)
        except Exception:
            return False

    def send_email_notification(
        self, action, controller, user, status, details=None, severity=None
    ):
        if not self.email_enabled or not self.email_smtp_host or not self.email_to:
            return False
        if status not in self.email_notify_on:
            return False

        def default_body():
            body = (
                f"Auto-Healer executed '{action}' on controller '{controller}'.\n\n"
                f"Status: {status.upper()}\n"
                f"Severity: {severity or 'info'}\n"
                f"Triggered by: {user}\n"
            )
            if details:
                body += f"\nDetails:\n{details}\n"
            return body

        body = self._render(
            "email",
            default_body,
            action=action,
            controller=controller,
            user=user,
            status=status,
            severity=severity or "info",
            details=details or "",
        )
        try:
            username = (
                resolve_vault_ref(self.email_username) if self.email_username else None
            )
            password = (
                resolve_vault_ref(self.email_password) if self.email_password else None
            )
        except VaultUnavailableError as e:
            logger.error(f"Failed to resolve email credentials from Vault: {e}")
            return False

        msg = MIMEText(body)
        msg["Subject"] = f"[Auto-Healer] {action} on {controller} - {status.upper()}"
        msg["From"] = self.email_from or username or "auto-healer@localhost"
        msg["To"] = ", ".join(self.email_to)
        try:
            with smtplib.SMTP(
                self.email_smtp_host, self.email_smtp_port, timeout=10
            ) as smtp:
                if self.email_use_tls:
                    smtp.starttls()
                if username and password:
                    smtp.login(username, password)
                smtp.sendmail(msg["From"], self.email_to, msg.as_string())
            return True
        except (smtplib.SMTPException, OSError) as e:
            logger.error(f"Failed to send email notification: {e}")
            return False

    def send_pagerduty_notification(
        self, action, controller, user, status, details=None, severity=None
    ):
        if not self.pagerduty_enabled or not self.pagerduty_routing_key:
            return False
        if status not in self.pagerduty_notify_on:
            return False
        effective_severity = severity or ("critical" if status == "failure" else "info")

        def default_summary():
            return f"Auto-Healer: '{action}' on '{controller}' - {status.upper()}"

        summary = self._render(
            "pagerduty",
            default_summary,
            action=action,
            controller=controller,
            user=user,
            status=status,
            severity=effective_severity,
            details=details or "",
        )
        try:
            routing_key = resolve_vault_ref(self.pagerduty_routing_key)
        except VaultUnavailableError as e:
            logger.error(f"Failed to resolve PagerDuty routing key from Vault: {e}")
            return False

        payload = {
            "routing_key": routing_key,
            "event_action": "trigger",
            # A stable dedup_key lets PagerDuty itself correlate repeat
            # triggers for the same action/controller into one incident,
            # on top of our own notification-level deduplication above.
            "dedup_key": f"auto-healer:{action}:{controller}",
            "payload": {
                "summary": summary,
                "source": "auto-healer",
                "severity": SEVERITY_TO_PAGERDUTY.get(effective_severity, "info"),
                "custom_details": {"user": user, "status": status, "details": details},
            },
        }
        try:
            resp = requests.post(PAGERDUTY_EVENTS_URL, json=payload, timeout=5)
            return resp.status_code == 202
        except requests.RequestException as e:
            logger.error(f"Failed to send PagerDuty notification: {e}")
            return False

    def send_opsgenie_notification(
        self, action, controller, user, status, details=None, severity=None
    ):
        if not self.opsgenie_enabled or not self.opsgenie_api_key:
            return False
        if status not in self.opsgenie_notify_on:
            return False
        effective_severity = severity or ("critical" if status == "failure" else "info")

        def default_message():
            return f"Auto-Healer: '{action}' on '{controller}' - {status.upper()}"

        message = self._render(
            "opsgenie",
            default_message,
            action=action,
            controller=controller,
            user=user,
            status=status,
            severity=effective_severity,
            details=details or "",
        )
        try:
            api_key = resolve_vault_ref(self.opsgenie_api_key)
        except VaultUnavailableError as e:
            logger.error(f"Failed to resolve Opsgenie API key from Vault: {e}")
            return False

        payload = {
            "message": message,
            "description": details or message,
            "priority": SEVERITY_TO_OPSGENIE_PRIORITY.get(effective_severity, "P5"),
            "source": "auto-healer",
            "details": {"user": user, "controller": controller, "status": status},
        }
        headers = {
            "Authorization": f"GenieKey {api_key}",
            "Content-Type": "application/json",
        }
        try:
            resp = requests.post(
                OPSGENIE_ALERTS_URL, json=payload, headers=headers, timeout=5
            )
            return resp.status_code == 202
        except requests.RequestException as e:
            logger.error(f"Failed to send Opsgenie notification: {e}")
            return False


notification_sender = NotificationSender()
