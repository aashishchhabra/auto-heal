import time

import pytest
import requests
from unittest.mock import patch

from src.notifications import NotificationSender
from src.vault import VaultUnavailableError


@pytest.fixture
def notif_sender():
    # Use a test config dict
    sender = NotificationSender()
    sender.slack_enabled = True
    sender.slack_url = "https://hooks.slack.com/services/test"
    sender.slack_channel = "#test"
    sender.slack_username = "TestBot"
    sender.slack_notify_on = ["success", "failure"]
    sender.teams_enabled = True
    sender.teams_url = "https://outlook.office.com/webhook/test"
    sender.teams_channel = "Test"
    sender.teams_notify_on = ["success", "failure"]
    return sender


def test_slack_notification_success(notif_sender):
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        result = notif_sender.send_slack_notification(
            action="restart_service",
            controller="dc1-ansible",
            user="admin-key",
            status="success",
            details="Service restarted successfully.",
        )
        assert result is True
        payload = mock_post.call_args[1]["json"]
        assert payload["channel"] == "#test"
        assert payload["username"] == "TestBot"
        assert "attachments" in payload
        assert "Service restarted successfully." in payload["attachments"][0]["text"]


def test_slack_notification_failure_filtered(notif_sender):
    notif_sender.slack_notify_on = ["failure"]
    with patch("requests.post") as mock_post:
        result = notif_sender.send_slack_notification(
            action="restart_service",
            controller="dc1-ansible",
            user="admin-key",
            status="success",
            details=None,
        )
        assert result is False
        mock_post.assert_not_called()


def test_teams_notification_success(notif_sender):
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        result = notif_sender.send_teams_notification(
            action="cleanup_disk",
            controller="local",
            user="operator-key",
            status="success",
            details="Disk cleaned.",
        )
        assert result is True
        payload = mock_post.call_args[1]["json"]
        assert payload["@type"] == "MessageCard"
        assert "Disk cleaned." in payload["sections"][0]["text"]


def test_teams_notification_failure_filtered(notif_sender):
    notif_sender.teams_notify_on = ["failure"]
    with patch("requests.post") as mock_post:
        result = notif_sender.send_teams_notification(
            action="cleanup_disk",
            controller="local",
            user="operator-key",
            status="success",
            details=None,
        )
        assert result is False
        mock_post.assert_not_called()


# --- Email --------------------------------------------------------------


@pytest.fixture
def email_sender():
    sender = NotificationSender()
    sender.email_enabled = True
    sender.email_smtp_host = "smtp.example.com"
    sender.email_smtp_port = 587
    sender.email_use_tls = True
    sender.email_username = "bot@example.com"
    sender.email_password = "secret"
    sender.email_from = "auto-healer@example.com"
    sender.email_to = ["oncall@example.com"]
    sender.email_notify_on = ["success", "failure"]
    return sender


def test_email_notification_success(email_sender):
    with patch("smtplib.SMTP") as mock_smtp_cls:
        smtp = mock_smtp_cls.return_value.__enter__.return_value
        result = email_sender.send_email_notification(
            action="restart_service",
            controller="dc1-ansible",
            user="admin-key",
            status="success",
            details="Service restarted successfully.",
        )
    assert result is True
    smtp.starttls.assert_called_once()
    smtp.login.assert_called_once_with("bot@example.com", "secret")
    assert smtp.sendmail.called
    sent_body = smtp.sendmail.call_args[0][2]
    assert "Service restarted successfully." in sent_body


def test_email_notification_disabled_does_nothing(email_sender):
    email_sender.email_enabled = False
    with patch("smtplib.SMTP") as mock_smtp_cls:
        result = email_sender.send_email_notification(
            "restart_service", "dc1-ansible", "admin-key", "success"
        )
    assert result is False
    mock_smtp_cls.assert_not_called()


def test_email_notification_missing_recipients_does_nothing(email_sender):
    email_sender.email_to = []
    with patch("smtplib.SMTP") as mock_smtp_cls:
        result = email_sender.send_email_notification(
            "restart_service", "dc1-ansible", "admin-key", "success"
        )
    assert result is False
    mock_smtp_cls.assert_not_called()


def test_email_notification_filtered_by_notify_on(email_sender):
    email_sender.email_notify_on = ["failure"]
    with patch("smtplib.SMTP") as mock_smtp_cls:
        result = email_sender.send_email_notification(
            "restart_service", "dc1-ansible", "admin-key", "success"
        )
    assert result is False
    mock_smtp_cls.assert_not_called()


def test_email_notification_resolves_vault_credentials(email_sender, monkeypatch):
    email_sender.email_username = "vault:secret/data/auto-healer/email#username"
    email_sender.email_password = "vault:secret/data/auto-healer/email#password"
    monkeypatch.setattr(
        "src.notifications.resolve_vault_ref",
        lambda value, default_field=None: {
            "vault:secret/data/auto-healer/email#username": "resolved-user",
            "vault:secret/data/auto-healer/email#password": "resolved-pass",
        }[value],
    )
    with patch("smtplib.SMTP") as mock_smtp_cls:
        smtp = mock_smtp_cls.return_value.__enter__.return_value
        result = email_sender.send_email_notification(
            "restart_service", "dc1-ansible", "admin-key", "success"
        )
    assert result is True
    smtp.login.assert_called_once_with("resolved-user", "resolved-pass")


def test_email_notification_vault_failure_returns_false(email_sender, monkeypatch):
    email_sender.email_username = "vault:secret/data/auto-healer/email#username"

    def raise_unavailable(value, default_field=None):
        raise VaultUnavailableError("unreachable")

    monkeypatch.setattr("src.notifications.resolve_vault_ref", raise_unavailable)
    with patch("smtplib.SMTP") as mock_smtp_cls:
        result = email_sender.send_email_notification(
            "restart_service", "dc1-ansible", "admin-key", "success"
        )
    assert result is False
    mock_smtp_cls.assert_not_called()


def test_email_notification_smtp_failure_returns_false(email_sender):
    with patch("smtplib.SMTP", side_effect=OSError("connection refused")):
        result = email_sender.send_email_notification(
            "restart_service", "dc1-ansible", "admin-key", "success"
        )
    assert result is False


# --- PagerDuty ------------------------------------------------------------


@pytest.fixture
def pagerduty_sender():
    sender = NotificationSender()
    sender.pagerduty_enabled = True
    sender.pagerduty_routing_key = "test-routing-key"
    sender.pagerduty_notify_on = ["success", "failure"]
    return sender


def test_pagerduty_notification_success(pagerduty_sender):
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 202
        result = pagerduty_sender.send_pagerduty_notification(
            "restart_deployment_kubeapi", "k8s-in-cluster", "admin-key", "failure"
        )
    assert result is True
    payload = mock_post.call_args[1]["json"]
    assert payload["routing_key"] == "test-routing-key"
    assert payload["payload"]["severity"] == "critical"
    assert (
        payload["dedup_key"] == "auto-healer:restart_deployment_kubeapi:k8s-in-cluster"
    )


def test_pagerduty_disabled_does_nothing(pagerduty_sender):
    pagerduty_sender.pagerduty_enabled = False
    with patch("requests.post") as mock_post:
        result = pagerduty_sender.send_pagerduty_notification(
            "restart_service", "dc1-ansible", "admin-key", "failure"
        )
    assert result is False
    mock_post.assert_not_called()


def test_pagerduty_default_notify_on_excludes_success():
    # Real default (not the fixture's override): paging on every
    # successful auto-remediation would be noise, not signal.
    sender = NotificationSender()
    sender.pagerduty_enabled = True
    sender.pagerduty_routing_key = "test-routing-key"
    with patch("requests.post") as mock_post:
        result = sender.send_pagerduty_notification(
            "restart_service", "dc1-ansible", "admin-key", "success"
        )
    assert result is False
    mock_post.assert_not_called()


def test_pagerduty_severity_mapping(pagerduty_sender):
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 202
        pagerduty_sender.send_pagerduty_notification(
            "restart_service",
            "dc1-ansible",
            "admin-key",
            "success",
            severity="warning",
        )
    assert mock_post.call_args[1]["json"]["payload"]["severity"] == "warning"


def test_pagerduty_resolves_vault_routing_key(pagerduty_sender, monkeypatch):
    pagerduty_sender.pagerduty_routing_key = (
        "vault:secret/data/auto-healer/pagerduty#routing_key"
    )
    monkeypatch.setattr(
        "src.notifications.resolve_vault_ref",
        lambda value, default_field=None: "real-key",
    )
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 202
        pagerduty_sender.send_pagerduty_notification(
            "restart_service", "dc1-ansible", "admin-key", "failure"
        )
    assert mock_post.call_args[1]["json"]["routing_key"] == "real-key"


def test_pagerduty_vault_failure_returns_false(pagerduty_sender, monkeypatch):
    def raise_unavailable(value, default_field=None):
        raise VaultUnavailableError("unreachable")

    monkeypatch.setattr("src.notifications.resolve_vault_ref", raise_unavailable)
    with patch("requests.post") as mock_post:
        result = pagerduty_sender.send_pagerduty_notification(
            "restart_service", "dc1-ansible", "admin-key", "failure"
        )
    assert result is False
    mock_post.assert_not_called()


def test_pagerduty_request_failure_returns_false(pagerduty_sender):
    with patch("requests.post", side_effect=requests.ConnectionError("down")):
        result = pagerduty_sender.send_pagerduty_notification(
            "restart_service", "dc1-ansible", "admin-key", "failure"
        )
    assert result is False


# --- Opsgenie ---------------------------------------------------------


@pytest.fixture
def opsgenie_sender():
    sender = NotificationSender()
    sender.opsgenie_enabled = True
    sender.opsgenie_api_key = "test-api-key"
    sender.opsgenie_notify_on = ["success", "failure"]
    return sender


def test_opsgenie_notification_success(opsgenie_sender):
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 202
        result = opsgenie_sender.send_opsgenie_notification(
            "drain_node", "k8s-in-cluster", "admin-key", "failure"
        )
    assert result is True
    payload = mock_post.call_args[1]["json"]
    headers = mock_post.call_args[1]["headers"]
    assert headers["Authorization"] == "GenieKey test-api-key"
    assert payload["priority"] == "P1"


def test_opsgenie_disabled_does_nothing(opsgenie_sender):
    opsgenie_sender.opsgenie_enabled = False
    with patch("requests.post") as mock_post:
        result = opsgenie_sender.send_opsgenie_notification(
            "restart_service", "dc1-ansible", "admin-key", "failure"
        )
    assert result is False
    mock_post.assert_not_called()


def test_opsgenie_default_notify_on_excludes_success():
    sender = NotificationSender()
    sender.opsgenie_enabled = True
    sender.opsgenie_api_key = "test-api-key"
    with patch("requests.post") as mock_post:
        result = sender.send_opsgenie_notification(
            "restart_service", "dc1-ansible", "admin-key", "success"
        )
    assert result is False
    mock_post.assert_not_called()


def test_opsgenie_priority_mapping(opsgenie_sender):
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 202
        opsgenie_sender.send_opsgenie_notification(
            "restart_service", "dc1-ansible", "admin-key", "success", severity="info"
        )
    assert mock_post.call_args[1]["json"]["priority"] == "P5"


def test_opsgenie_resolves_vault_api_key(opsgenie_sender, monkeypatch):
    opsgenie_sender.opsgenie_api_key = "vault:secret/data/auto-healer/opsgenie#api_key"
    monkeypatch.setattr(
        "src.notifications.resolve_vault_ref",
        lambda value, default_field=None: "real-key",
    )
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 202
        opsgenie_sender.send_opsgenie_notification(
            "restart_service", "dc1-ansible", "admin-key", "failure"
        )
    assert mock_post.call_args[1]["headers"]["Authorization"] == "GenieKey real-key"


def test_opsgenie_vault_failure_returns_false(opsgenie_sender, monkeypatch):
    def raise_unavailable(value, default_field=None):
        raise VaultUnavailableError("unreachable")

    monkeypatch.setattr("src.notifications.resolve_vault_ref", raise_unavailable)
    with patch("requests.post") as mock_post:
        result = opsgenie_sender.send_opsgenie_notification(
            "restart_service", "dc1-ansible", "admin-key", "failure"
        )
    assert result is False
    mock_post.assert_not_called()


def test_opsgenie_request_failure_returns_false(opsgenie_sender):
    with patch("requests.post", side_effect=requests.ConnectionError("down")):
        result = opsgenie_sender.send_opsgenie_notification(
            "restart_service", "dc1-ansible", "admin-key", "failure"
        )
    assert result is False


# --- notify() coordinator: severity, dedup, routing ------------------------


def test_notify_fans_out_to_all_enabled_channels_without_routing():
    sender = NotificationSender()
    sender.slack_enabled = True
    sender.slack_url = "https://hooks.slack.com/services/test"
    sender.teams_enabled = True
    sender.teams_url = "https://outlook.office.com/webhook/test"
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        results = sender.notify(
            "restart_service", "dc1-ansible", "admin-key", "success"
        )
    assert results["slack"] is True
    assert results["teams"] is True
    assert mock_post.call_count == 2


def test_notify_routing_restricts_to_configured_channels():
    sender = NotificationSender()
    sender.slack_enabled = True
    sender.slack_url = "https://hooks.slack.com/services/test"
    sender.pagerduty_enabled = True
    sender.pagerduty_routing_key = "test-key"
    sender.pagerduty_notify_on = ["success", "failure"]
    sender.routing = {"info": ["slack"], "critical": ["slack", "pagerduty"]}
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        results = sender.notify(
            "restart_service", "dc1-ansible", "admin-key", "success"
        )
    # severity defaults to "info" -> routing only sends to slack
    assert "slack" in results
    assert "pagerduty" not in results
    assert mock_post.call_count == 1


def test_notify_failure_bumps_severity_into_routing():
    sender = NotificationSender()
    sender.pagerduty_enabled = True
    sender.pagerduty_routing_key = "test-key"
    sender.pagerduty_notify_on = ["success", "failure"]
    sender.routing = {"info": [], "warning": ["pagerduty"], "critical": ["pagerduty"]}
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 202
        # base severity unset -> "info" -> failure bumps to "warning"
        results = sender.notify(
            "restart_service", "dc1-ansible", "admin-key", "failure"
        )
    assert results.get("pagerduty") is True


def test_notify_action_severity_is_not_downgraded_by_success():
    sender = NotificationSender()
    sender.pagerduty_enabled = True
    sender.pagerduty_routing_key = "test-key"
    sender.pagerduty_notify_on = ["success", "failure"]
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 202
        sender.notify(
            "drain_node",
            "k8s-in-cluster",
            "admin-key",
            "success",
            severity="critical",
        )
    assert mock_post.call_args[1]["json"]["payload"]["severity"] == "critical"


def test_notify_deduplicates_within_window():
    sender = NotificationSender()
    sender.slack_enabled = True
    sender.slack_url = "https://hooks.slack.com/services/test"
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        first = sender.notify("restart_service", "dc1-ansible", "admin-key", "success")
        second = sender.notify("restart_service", "dc1-ansible", "admin-key", "success")
    assert first != {}
    assert second == {}
    assert mock_post.call_count == 1


def test_notify_does_not_deduplicate_after_window_elapses(monkeypatch):
    sender = NotificationSender()
    sender.slack_enabled = True
    sender.slack_url = "https://hooks.slack.com/services/test"
    sender.dedup_window_seconds = 10
    base = time.time()
    monkeypatch.setattr(time, "time", lambda: base)
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        sender.notify("restart_service", "dc1-ansible", "admin-key", "success")
        monkeypatch.setattr(time, "time", lambda: base + 11)
        sender.notify("restart_service", "dc1-ansible", "admin-key", "success")
    assert mock_post.call_count == 2


def test_notify_dedup_disabled_always_sends():
    sender = NotificationSender()
    sender.slack_enabled = True
    sender.slack_url = "https://hooks.slack.com/services/test"
    sender.dedup_enabled = False
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        sender.notify("restart_service", "dc1-ansible", "admin-key", "success")
        sender.notify("restart_service", "dc1-ansible", "admin-key", "success")
    assert mock_post.call_count == 2


def test_notify_different_controllers_are_not_deduplicated_together():
    sender = NotificationSender()
    sender.slack_enabled = True
    sender.slack_url = "https://hooks.slack.com/services/test"
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        sender.notify("restart_service", "web-01", "admin-key", "success")
        sender.notify("restart_service", "web-02", "admin-key", "success")
    assert mock_post.call_count == 2


# --- Custom templates -------------------------------------------------


def test_custom_slack_template_overrides_default(notif_sender):
    notif_sender.templates = {
        "slack": "[{severity}] {action} on {controller}: {status}"
    }
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        notif_sender.send_slack_notification(
            "restart_service",
            "dc1-ansible",
            "admin-key",
            "success",
            severity="warning",
        )
    text = mock_post.call_args[1]["json"]["attachments"][0]["text"]
    assert text == "[warning] restart_service on dc1-ansible: success"


def test_default_template_fallback_used_when_no_channel_specific_template(notif_sender):
    notif_sender.templates = {"default": "generic: {action}"}
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        notif_sender.send_slack_notification(
            "restart_service", "dc1-ansible", "admin-key", "success"
        )
    text = mock_post.call_args[1]["json"]["attachments"][0]["text"]
    assert text == "generic: restart_service"


def test_malformed_template_falls_back_to_default_wording(notif_sender):
    notif_sender.templates = {"slack": "{nonexistent_field}"}
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        notif_sender.send_slack_notification(
            "restart_service",
            "dc1-ansible",
            "admin-key",
            "success",
            details="fell back ok",
        )
    text = mock_post.call_args[1]["json"]["attachments"][0]["text"]
    assert "fell back ok" in text
    assert "Auto-Healer Notification" in text


def test_no_template_configured_keeps_original_wording(notif_sender):
    # Regression check: the exact pre-existing hardcoded format must be
    # byte-for-byte unchanged when no template is configured, since real
    # deployments (and the tests above) depend on it.
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        notif_sender.send_slack_notification(
            "restart_service",
            "dc1-ansible",
            "admin-key",
            "success",
            details="ok",
        )
    text = mock_post.call_args[1]["json"]["attachments"][0]["text"]
    assert text == (
        "*Auto-Healer Notification*\n*Action:* `restart_service`\n"
        "*Controller:* `dc1-ansible`\n"
        "*User:* `admin-key`\n"
        "*Status:* `SUCCESS`\n*Details:* ok"
    )
