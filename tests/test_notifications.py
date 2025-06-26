import pytest
from unittest.mock import patch
from src.notifications import NotificationSender


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
