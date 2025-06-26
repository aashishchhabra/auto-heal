import os
import sys
from unittest.mock import patch, MagicMock

from src.executor import ActionExecutor

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def test_run_playbook_success():
    executor = ActionExecutor()
    with patch("subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "ok"
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc
        result = executor.run_playbook(
            "playbooks/restart_service.yml", {"service_name": "nginx"}
        )
        assert result.success is True
        assert result.stdout == "ok"
        assert result.stderr == ""
        assert result.exit_code == 0
        assert result.error is None


def test_run_playbook_failure():
    executor = ActionExecutor()
    with patch("subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.returncode = 2
        mock_proc.stdout = ""
        mock_proc.stderr = "error"
        mock_run.return_value = mock_proc
        result = executor.run_playbook(
            "playbooks/restart_service.yml", {"service_name": "nginx"}
        )
        assert result.success is False
        assert result.stdout == ""
        assert result.stderr == "error"
        assert result.exit_code == 2


def test_run_script_success():
    executor = ActionExecutor()
    with patch("subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "done"
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc
        result = executor.run_script("scripts/cleanup_disk.sh", ["--path", "/tmp"])
        assert result.success is True
        assert result.stdout == "done"
        assert result.stderr == ""
        assert result.exit_code == 0


def test_run_script_failure():
    executor = ActionExecutor()
    with patch("subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = ""
        mock_proc.stderr = "fail"
        mock_run.return_value = mock_proc
        result = executor.run_script("scripts/cleanup_disk.sh", ["--path", "/tmp"])
        assert result.success is False
        assert result.stdout == ""
        assert result.stderr == "fail"
        assert result.exit_code == 1


def test_run_playbook_exception():
    executor = ActionExecutor()
    with patch("subprocess.run", side_effect=Exception("boom")):
        result = executor.run_playbook(
            "playbooks/restart_service.yml", {"service_name": "nginx"}
        )
        assert result.success is False
        assert result.error == "boom"


def test_run_script_exception():
    executor = ActionExecutor()
    with patch("subprocess.run", side_effect=Exception("crash")):
        result = executor.run_script("scripts/cleanup_disk.sh", ["--path", "/tmp"])
        assert result.success is False
        assert result.error == "crash"


def test_run_playbook_dry_run():
    executor = ActionExecutor()
    result = executor.run_playbook(
        "playbooks/restart_service.yml", {"service_name": "nginx"}, dry_run=True
    )
    assert result.success is True
    assert result.exit_code == 0
    assert result.stderr == ""
    assert result.error is None
    assert "[DRY-RUN]" in result.stdout
    assert "playbooks/restart_service.yml" in result.stdout


def test_run_script_dry_run():
    executor = ActionExecutor()
    result = executor.run_script(
        "scripts/cleanup_disk.sh", ["--path", "/tmp"], dry_run=True
    )
    assert result.success is True
    assert result.exit_code == 0
    assert result.stderr == ""
    assert result.error is None
    assert "[DRY-RUN]" in result.stdout
    assert "scripts/cleanup_disk.sh" in result.stdout
