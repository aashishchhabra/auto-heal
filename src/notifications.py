# flake8: noqa: E501
import os
import yaml
import requests

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "../config/notifications.yaml")


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

    def _load_config(self):
        if not os.path.exists(CONFIG_PATH):
            return {}
        with open(CONFIG_PATH) as f:
            return yaml.safe_load(f)

    def send_slack_notification(self, action, controller, user, status, details=None):
        if not self.slack_enabled or not self.slack_url:
            return False
        if status not in self.slack_notify_on:
            return False
        color = getattr(self, "slack_color", "#439FE0")
        text = (
            f"*Auto-Healer Notification*\n*Action:* `{action}`\n"
            f"*Controller:* `{controller}`\n"
            f"*User:* `{user}`\n"
            f"*Status:* `{status.upper()}`"
        )
        if details:
            text += f"\n*Details:* {details}"
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

    def send_teams_notification(self, action, controller, user, status, details=None):
        if not self.teams_enabled or not self.teams_url:
            return False
        if status not in self.teams_notify_on:
            return False
        color = getattr(self, "teams_color", "0076D7")
        text = (
            f"**Auto-Healer Notification**\n**Action:** `{action}`\n"
            f"**Controller:** `{controller}`\n**User:** `{user}`\n"
            f"**Status:** `{status.upper()}`"
        )
        if details:
            text += f"\n**Details:** {details}"
        payload = {
            "@type": "MessageCard",
            "themeColor": color,
            "text": text,
        }
        try:
            resp = requests.post(self.teams_url, json=payload, timeout=5)
            return resp.status_code in (200, 201)
        except Exception:
            return False


notification_sender = NotificationSender()
