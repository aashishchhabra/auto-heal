import os
import sys
from unittest.mock import patch, MagicMock

import pytest

from src.executor import ActionExecutor
from src.vault import VaultUnavailableError

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


ANSIBLE_CONTROLLER = {
    "type": "ansible",
    "host": "ansible.dc1.example.com",
    "ssh_user": "ansible",
    "ssh_key": "/secrets/dc1_ansible.key",
}

OC_CONTROLLER = {
    "type": "oc",
    "host": "oc.dc2.example.com",
    "ssh_user": "ocadmin",
    "ssh_key": "/secrets/dc2_oc.key",
}


def test_run_remote_playbook_builds_ssh_command():
    executor = ActionExecutor()
    with patch("subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "ok"
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc
        result = executor.run_remote(
            ANSIBLE_CONTROLLER,
            {"playbook": "playbooks/restart_service.yml"},
            {"service_name": "nginx"},
        )
        assert result.success is True
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "ssh"
        assert "-i" in cmd and "/secrets/dc1_ansible.key" in cmd
        assert cmd[-2] == "ansible@ansible.dc1.example.com"
        remote_cmd = cmd[-1]
        assert remote_cmd.startswith("ansible-playbook playbooks/restart_service.yml")
        assert "--extra-vars" in remote_cmd


def test_run_remote_script_builds_ssh_command():
    executor = ActionExecutor()
    with patch("subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "done"
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc
        result = executor.run_remote(
            OC_CONTROLLER,
            {"script": "scripts/cleanup_disk.sh"},
            {"path": "/tmp"},
        )
        assert result.success is True
        remote_cmd = mock_run.call_args[0][0][-1]
        assert remote_cmd == "scripts/cleanup_disk.sh /tmp"


def test_run_remote_command_template():
    executor = ActionExecutor()
    with patch("subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "restarted"
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc
        result = executor.run_remote(
            OC_CONTROLLER,
            {"command": "oc rollout restart deployment/{deployment} -n {namespace}"},
            {"deployment": "web", "namespace": "prod"},
        )
        assert result.success is True
        remote_cmd = mock_run.call_args[0][0][-1]
        assert remote_cmd == "oc rollout restart deployment/web -n prod"


def test_run_remote_command_template_quotes_params_against_injection():
    executor = ActionExecutor()
    with patch("subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc
        executor.run_remote(
            OC_CONTROLLER,
            {"command": "oc get pod {pod}"},
            {"pod": "web; rm -rf /"},
        )
        remote_cmd = mock_run.call_args[0][0][-1]
        # The whole malicious value must come through as a single quoted
        # token, not as unquoted shell metacharacters.
        assert remote_cmd == "oc get pod 'web; rm -rf /'"


def test_run_remote_missing_param_for_command_template():
    executor = ActionExecutor()
    result = executor.run_remote(OC_CONTROLLER, {"command": "oc get pod {pod}"}, {})
    assert result.success is False
    assert "pod" in result.error


def test_run_remote_ssh_connection_failure():
    executor = ActionExecutor()
    with patch("subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.returncode = 255
        mock_proc.stdout = ""
        mock_proc.stderr = "Permission denied (publickey)."
        mock_run.return_value = mock_proc
        result = executor.run_remote(
            ANSIBLE_CONTROLLER, {"script": "scripts/health_check.sh"}, {}
        )
        assert result.success is False
        assert result.exit_code == 255
        assert "SSH connection" in result.error
        assert "Permission denied" in result.error


def test_run_remote_missing_host():
    executor = ActionExecutor()
    result = executor.run_remote(
        {"type": "ansible", "ssh_user": "ansible"},
        {"script": "scripts/health_check.sh"},
        {},
    )
    assert result.success is False
    assert "host" in result.error


def test_run_remote_missing_ssh_user():
    executor = ActionExecutor()
    result = executor.run_remote(
        {"type": "ansible", "host": "ansible.dc1.example.com"},
        {"script": "scripts/health_check.sh"},
        {},
    )
    assert result.success is False
    assert "ssh_user" in result.error


def test_run_remote_no_executable_defined():
    executor = ActionExecutor()
    result = executor.run_remote(ANSIBLE_CONTROLLER, {}, {})
    assert result.success is False
    assert "No playbook, script, or command" in result.error


def test_run_remote_dry_run():
    executor = ActionExecutor()
    result = executor.run_remote(
        OC_CONTROLLER,
        {"command": "oc rollout restart deployment/{deployment}"},
        {"deployment": "web"},
        dry_run=True,
    )
    assert result.success is True
    assert result.exit_code == 0
    assert "[DRY-RUN]" in result.stdout
    assert "ocadmin@oc.dc2.example.com" in result.stdout
    assert "oc rollout restart deployment/web" in result.stdout


def test_run_command_local_success():
    executor = ActionExecutor()
    with patch("subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "restarted"
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc
        result = executor.run_command(
            "oc rollout restart deployment/{deployment}", {"deployment": "web"}
        )
        assert result.success is True
        cmd = mock_run.call_args[0][0]
        assert cmd == ["oc", "rollout", "restart", "deployment/web"]


def test_run_command_missing_param():
    executor = ActionExecutor()
    result = executor.run_command("oc get pod {pod}", {})
    assert result.success is False
    assert "pod" in result.error


def test_run_command_dry_run():
    executor = ActionExecutor()
    result = executor.run_command(
        "oc rollout restart deployment/{deployment}",
        {"deployment": "web"},
        dry_run=True,
    )
    assert result.success is True
    assert "[DRY-RUN]" in result.stdout
    assert "oc rollout restart deployment/web" in result.stdout


VAULT_CONTROLLER = {
    "type": "oc",
    "host": "oc.dc2.example.com",
    "ssh_user": "ocadmin",
    "ssh_key": "vault:secret/data/auto-healer/controllers/dc2-oc",
}


def test_resolve_ssh_key_plain_path_unchanged():
    executor = ActionExecutor()
    resolved, tmp_path = executor._resolve_ssh_key("/secrets/dc1_ansible.key")
    assert resolved == "/secrets/dc1_ansible.key"
    assert tmp_path is None


def test_resolve_ssh_key_none_unchanged():
    executor = ActionExecutor()
    resolved, tmp_path = executor._resolve_ssh_key(None)
    assert resolved is None
    assert tmp_path is None


def test_resolve_ssh_key_from_vault_default_field(monkeypatch):
    executor = ActionExecutor()
    fake_client = MagicMock()
    fake_client.get_secret.return_value = {"private_key": "-----BEGIN KEY-----\nx"}
    monkeypatch.setattr("src.executor.vault_client", fake_client)

    resolved, tmp_path = executor._resolve_ssh_key(
        "vault:secret/data/auto-healer/controllers/dc2-oc"
    )
    try:
        fake_client.get_secret.assert_called_once_with(
            "secret/data/auto-healer/controllers/dc2-oc"
        )
        assert resolved == tmp_path
        assert os.path.exists(tmp_path)
        with open(tmp_path) as f:
            assert f.read() == "-----BEGIN KEY-----\nx"
        # Key material must not be world/group readable.
        assert oct(os.stat(tmp_path).st_mode)[-3:] == "600"
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


def test_resolve_ssh_key_from_vault_custom_field(monkeypatch):
    executor = ActionExecutor()
    fake_client = MagicMock()
    fake_client.get_secret.return_value = {"ssh_private_key": "keydata"}
    monkeypatch.setattr("src.executor.vault_client", fake_client)

    resolved, tmp_path = executor._resolve_ssh_key(
        "vault:secret/data/x#ssh_private_key"
    )
    try:
        fake_client.get_secret.assert_called_once_with("secret/data/x")
        with open(tmp_path) as f:
            assert f.read() == "keydata"
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


def test_resolve_ssh_key_missing_field_raises(monkeypatch):
    executor = ActionExecutor()
    fake_client = MagicMock()
    fake_client.get_secret.return_value = {"some_other_field": "x"}
    monkeypatch.setattr("src.executor.vault_client", fake_client)

    with pytest.raises(VaultUnavailableError):
        executor._resolve_ssh_key("vault:secret/data/x")


def test_resolve_ssh_key_vault_error_propagates(monkeypatch):
    executor = ActionExecutor()
    fake_client = MagicMock()
    fake_client.get_secret.side_effect = VaultUnavailableError("unreachable")
    monkeypatch.setattr("src.executor.vault_client", fake_client)

    with pytest.raises(VaultUnavailableError):
        executor._resolve_ssh_key("vault:secret/data/x")


def test_run_remote_with_vault_ssh_key_uses_and_cleans_up_tempfile(monkeypatch):
    executor = ActionExecutor()
    fake_client = MagicMock()
    fake_client.get_secret.return_value = {"private_key": "keydata"}
    monkeypatch.setattr("src.executor.vault_client", fake_client)

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        i_index = cmd.index("-i")
        captured["key_path"] = cmd[i_index + 1]
        # The tempfile must exist (with the right content) at the moment
        # ssh is actually invoked.
        assert os.path.exists(captured["key_path"])
        with open(captured["key_path"]) as f:
            assert f.read() == "keydata"
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "ok"
        mock_proc.stderr = ""
        return mock_proc

    with patch("subprocess.run", side_effect=fake_run):
        result = executor.run_remote(
            VAULT_CONTROLLER, {"script": "scripts/health_check.sh"}, {}
        )

    assert result.success is True
    assert "-i" in captured["cmd"]
    # Cleaned up after the call - no leftover key material on disk.
    assert not os.path.exists(captured["key_path"])


def test_run_remote_vault_failure_does_not_attempt_ssh(monkeypatch):
    executor = ActionExecutor()
    fake_client = MagicMock()
    fake_client.get_secret.side_effect = VaultUnavailableError("sealed")
    monkeypatch.setattr("src.executor.vault_client", fake_client)

    with patch("subprocess.run") as mock_run:
        result = executor.run_remote(
            VAULT_CONTROLLER, {"script": "scripts/health_check.sh"}, {}
        )

    assert result.success is False
    assert "Vault" in result.error
    mock_run.assert_not_called()


def test_run_remote_dry_run_never_touches_vault(monkeypatch):
    executor = ActionExecutor()
    fake_client = MagicMock()
    monkeypatch.setattr("src.executor.vault_client", fake_client)

    result = executor.run_remote(
        VAULT_CONTROLLER,
        {"script": "scripts/health_check.sh"},
        {},
        dry_run=True,
    )

    assert result.success is True
    assert "[DRY-RUN]" in result.stdout
    fake_client.get_secret.assert_not_called()
