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
    monkeypatch.setattr("src.vault.vault_client", fake_client)

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
    monkeypatch.setattr("src.vault.vault_client", fake_client)

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
    monkeypatch.setattr("src.vault.vault_client", fake_client)

    with pytest.raises(VaultUnavailableError):
        executor._resolve_ssh_key("vault:secret/data/x")


def test_resolve_ssh_key_vault_error_propagates(monkeypatch):
    executor = ActionExecutor()
    fake_client = MagicMock()
    fake_client.get_secret.side_effect = VaultUnavailableError("unreachable")
    monkeypatch.setattr("src.vault.vault_client", fake_client)

    with pytest.raises(VaultUnavailableError):
        executor._resolve_ssh_key("vault:secret/data/x")


def test_run_remote_with_vault_ssh_key_uses_and_cleans_up_tempfile(monkeypatch):
    executor = ActionExecutor()
    fake_client = MagicMock()
    fake_client.get_secret.return_value = {"private_key": "keydata"}
    monkeypatch.setattr("src.vault.vault_client", fake_client)

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
    monkeypatch.setattr("src.vault.vault_client", fake_client)

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
    monkeypatch.setattr("src.vault.vault_client", fake_client)

    result = executor.run_remote(
        VAULT_CONTROLLER,
        {"script": "scripts/health_check.sh"},
        {},
        dry_run=True,
    )

    assert result.success is True
    assert "[DRY-RUN]" in result.stdout
    fake_client.get_secret.assert_not_called()


# ---------------------------------------------------------------------
# kube_action / direct Kubernetes API execution
# ---------------------------------------------------------------------

import kubernetes  # noqa: E402
from kubernetes.client.exceptions import ApiException  # noqa: E402

IN_CLUSTER_CONTROLLER = {"type": "kubeapi", "in_cluster": True}


def make_pod(name, namespace="default", daemonset_owned=False):
    owner_refs = (
        [
            kubernetes.client.V1OwnerReference(
                api_version="apps/v1", kind="DaemonSet", name="x", uid="1"
            )
        ]
        if daemonset_owned
        else []
    )
    return kubernetes.client.V1Pod(
        metadata=kubernetes.client.V1ObjectMeta(
            name=name, namespace=namespace, owner_references=owner_refs
        )
    )


def test_render_kube_action_fields_substitutes_params():
    executor = ActionExecutor()
    rendered = executor._render_kube_action_fields(
        {
            "resource": "deployment",
            "name": "{deployment}",
            "namespace": "{namespace}",
            "data": {"replicas": "{replicas}"},
        },
        {"deployment": "web", "namespace": "prod", "replicas": 3},
    )
    assert rendered == {
        "resource": "deployment",
        "name": "web",
        "namespace": "prod",
        "data": {"replicas": "3"},
    }


def test_render_kube_action_fields_missing_param_raises():
    executor = ActionExecutor()
    with pytest.raises(KeyError):
        executor._render_kube_action_fields({"name": "{deployment}"}, {})


def test_run_kube_action_unknown_verb():
    executor = ActionExecutor()
    result = executor.run_kube_action(
        IN_CLUSTER_CONTROLLER, {"kube_action": "delete_everything"}, {}
    )
    assert result.success is False
    assert "Unknown kube_action" in result.error


def test_run_kube_action_missing_param():
    executor = ActionExecutor()
    result = executor.run_kube_action(
        IN_CLUSTER_CONTROLLER,
        {
            "kube_action": "rollout_restart",
            "resource": "deployment",
            "name": "{deployment}",
        },
        {},
    )
    assert result.success is False
    assert "Missing parameter" in result.error


def test_run_kube_action_dry_run_never_builds_client(monkeypatch):
    executor = ActionExecutor()
    called = {}
    monkeypatch.setattr(
        kubernetes.config,
        "load_incluster_config",
        lambda **kw: called.setdefault("called", True),
    )
    result = executor.run_kube_action(
        IN_CLUSTER_CONTROLLER,
        {
            "kube_action": "rollout_restart",
            "resource": "deployment",
            "name": "{deployment}",
            "namespace": "{namespace}",
        },
        {"deployment": "web", "namespace": "prod"},
        dry_run=True,
    )
    assert result.success is True
    assert "[DRY-RUN]" in result.stdout
    assert "rollout_restart" in result.stdout
    assert "called" not in called


def test_build_kube_configuration_in_cluster(monkeypatch):
    executor = ActionExecutor()
    calls = {}
    monkeypatch.setattr(
        kubernetes.config,
        "load_incluster_config",
        lambda client_configuration=None: calls.setdefault("cfg", client_configuration),
    )
    configuration, cleanup_paths = executor._build_kube_configuration(
        {"type": "kubeapi", "in_cluster": True}
    )
    assert cleanup_paths == []
    assert calls["cfg"] is configuration


def test_build_kube_configuration_token_and_ca(tmp_path):
    executor = ActionExecutor()
    token_file = tmp_path / "token"
    token_file.write_text("my-token\n")
    ca_file = tmp_path / "ca.crt"
    ca_file.write_text("-----BEGIN CERTIFICATE-----\n...")

    configuration, cleanup_paths = executor._build_kube_configuration(
        {
            "type": "kubeapi",
            "api_server": "https://api.example.com:6443",
            "token": str(token_file),
            "ca_cert": str(ca_file),
        }
    )
    assert cleanup_paths == []
    assert configuration.host == "https://api.example.com:6443"
    assert configuration.get_api_key_with_prefix("authorization") == "Bearer my-token"
    assert configuration.ssl_ca_cert == str(ca_file)


def test_build_kube_configuration_token_without_ca_disables_verify(tmp_path):
    executor = ActionExecutor()
    token_file = tmp_path / "token"
    token_file.write_text("my-token")

    configuration, _ = executor._build_kube_configuration(
        {
            "type": "kubeapi",
            "api_server": "https://api.example.com:6443",
            "token": str(token_file),
        }
    )
    assert configuration.verify_ssl is False


def test_build_kube_configuration_from_vault(monkeypatch):
    executor = ActionExecutor()
    fake_client = MagicMock()
    fake_client.get_secret.return_value = {"token": "vault-token", "ca_cert": "ca-data"}
    monkeypatch.setattr("src.vault.vault_client", fake_client)

    configuration, cleanup_paths = executor._build_kube_configuration(
        {
            "type": "kubeapi",
            "api_server": "https://api.example.com:6443",
            "token": "vault:secret/data/clusters/prod",
            "ca_cert": "vault:secret/data/clusters/prod",
        }
    )
    try:
        assert len(cleanup_paths) == 2
        assert (
            configuration.get_api_key_with_prefix("authorization")
            == "Bearer vault-token"
        )
        with open(configuration.ssl_ca_cert) as f:
            assert f.read() == "ca-data"
    finally:
        for p in cleanup_paths:
            if os.path.exists(p):
                os.unlink(p)


def test_build_kube_configuration_partial_vault_failure_cleans_up(monkeypatch):
    import tempfile as tempfile_module

    executor = ActionExecutor()
    fake_client = MagicMock()

    def get_secret(path):
        if path == "secret/data/token-path":
            return {"token": "vault-token"}
        raise VaultUnavailableError("ca fetch failed")

    fake_client.get_secret.side_effect = get_secret
    monkeypatch.setattr("src.vault.vault_client", fake_client)

    def snapshot():
        return {
            f
            for f in os.listdir(tempfile_module.gettempdir())
            if f.startswith("autoheal-secret-")
        }

    before = snapshot()
    with pytest.raises(VaultUnavailableError):
        executor._build_kube_configuration(
            {
                "type": "kubeapi",
                "api_server": "https://api.example.com:6443",
                "token": "vault:secret/data/token-path",
                "ca_cert": "vault:secret/data/ca-path",
            }
        )
    # The token tempfile created before the ca_cert lookup failed must not
    # be left behind - no NEW autoheal-secret-* files versus before the call.
    assert snapshot() == before


def test_build_kube_configuration_no_credentials_raises():
    executor = ActionExecutor()
    with pytest.raises(ValueError):
        executor._build_kube_configuration({"type": "kubeapi"})


def test_run_kube_action_no_credentials_returns_failure():
    executor = ActionExecutor()
    result = executor.run_kube_action(
        {"type": "kubeapi"},
        {
            "kube_action": "rollout_restart",
            "resource": "deployment",
            "name": "{deployment}",
            "namespace": "{namespace}",
        },
        {"deployment": "web", "namespace": "prod"},
    )
    assert result.success is False
    assert "credentials" in result.error.lower()


def test_run_kube_action_vault_failure_returns_failure(monkeypatch):
    executor = ActionExecutor()
    fake_client = MagicMock()
    fake_client.get_secret.side_effect = VaultUnavailableError("sealed")
    monkeypatch.setattr("src.vault.vault_client", fake_client)

    result = executor.run_kube_action(
        {
            "type": "kubeapi",
            "api_server": "https://api.example.com:6443",
            "token": "vault:secret/data/x",
        },
        {
            "kube_action": "rollout_restart",
            "resource": "deployment",
            "name": "{deployment}",
            "namespace": "{namespace}",
        },
        {"deployment": "web", "namespace": "prod"},
    )
    assert result.success is False
    assert "Vault" in result.error


def _patch_incluster(monkeypatch):
    monkeypatch.setattr(kubernetes.config, "load_incluster_config", lambda **kw: None)


def test_run_kube_action_rollout_restart_deployment(monkeypatch):
    executor = ActionExecutor()
    _patch_incluster(monkeypatch)
    mock_apps = MagicMock()
    with patch("kubernetes.client.AppsV1Api", return_value=mock_apps):
        result = executor.run_kube_action(
            IN_CLUSTER_CONTROLLER,
            {
                "kube_action": "rollout_restart",
                "resource": "deployment",
                "name": "{deployment}",
                "namespace": "{namespace}",
            },
            {"deployment": "web", "namespace": "prod"},
        )
    assert result.success is True
    mock_apps.patch_namespaced_deployment.assert_called_once()
    call_args = mock_apps.patch_namespaced_deployment.call_args[0]
    assert call_args[0] == "web"
    assert call_args[1] == "prod"
    annotations = call_args[2]["spec"]["template"]["metadata"]["annotations"]
    assert "kubectl.kubernetes.io/restartedAt" in annotations


def test_run_kube_action_rollout_restart_statefulset(monkeypatch):
    executor = ActionExecutor()
    _patch_incluster(monkeypatch)
    mock_apps = MagicMock()
    with patch("kubernetes.client.AppsV1Api", return_value=mock_apps):
        result = executor.run_kube_action(
            IN_CLUSTER_CONTROLLER,
            {
                "kube_action": "rollout_restart",
                "resource": "statefulset",
                "name": "{name}",
                "namespace": "{namespace}",
            },
            {"name": "db", "namespace": "prod"},
        )
    assert result.success is True
    mock_apps.patch_namespaced_stateful_set.assert_called_once()


def test_run_kube_action_rollout_restart_unsupported_resource(monkeypatch):
    executor = ActionExecutor()
    _patch_incluster(monkeypatch)
    with patch("kubernetes.client.AppsV1Api", return_value=MagicMock()):
        result = executor.run_kube_action(
            IN_CLUSTER_CONTROLLER,
            {
                "kube_action": "rollout_restart",
                "resource": "job",
                "name": "{name}",
                "namespace": "{namespace}",
            },
            {"name": "x", "namespace": "prod"},
        )
    assert result.success is False
    assert "Unsupported resource" in result.error


def test_run_kube_action_delete_pod(monkeypatch):
    executor = ActionExecutor()
    _patch_incluster(monkeypatch)
    mock_core = MagicMock()
    with patch("kubernetes.client.CoreV1Api", return_value=mock_core):
        result = executor.run_kube_action(
            IN_CLUSTER_CONTROLLER,
            {"kube_action": "delete_pod", "name": "{pod}", "namespace": "{namespace}"},
            {"pod": "web-abc123", "namespace": "prod"},
        )
    assert result.success is True
    mock_core.delete_namespaced_pod.assert_called_once_with("web-abc123", "prod")


def test_run_kube_action_scale(monkeypatch):
    executor = ActionExecutor()
    _patch_incluster(monkeypatch)
    mock_apps = MagicMock()
    with patch("kubernetes.client.AppsV1Api", return_value=mock_apps):
        result = executor.run_kube_action(
            IN_CLUSTER_CONTROLLER,
            {
                "kube_action": "scale",
                "resource": "deployment",
                "name": "{deployment}",
                "namespace": "{namespace}",
                "data": {"replicas": "{replicas}"},
            },
            {"deployment": "web", "namespace": "prod", "replicas": 5},
        )
    assert result.success is True
    mock_apps.patch_namespaced_deployment_scale.assert_called_once_with(
        "web", "prod", {"spec": {"replicas": 5}}
    )


def test_run_kube_action_scale_missing_replicas(monkeypatch):
    executor = ActionExecutor()
    _patch_incluster(monkeypatch)
    with patch("kubernetes.client.AppsV1Api", return_value=MagicMock()):
        result = executor.run_kube_action(
            IN_CLUSTER_CONTROLLER,
            {
                "kube_action": "scale",
                "resource": "deployment",
                "name": "{deployment}",
                "namespace": "{namespace}",
            },
            {"deployment": "web", "namespace": "prod"},
        )
    assert result.success is False
    assert "replicas" in result.error


def test_run_kube_action_cordon_node(monkeypatch):
    executor = ActionExecutor()
    _patch_incluster(monkeypatch)
    mock_core = MagicMock()
    with patch("kubernetes.client.CoreV1Api", return_value=mock_core):
        result = executor.run_kube_action(
            IN_CLUSTER_CONTROLLER,
            {"kube_action": "cordon_node", "node_name": "{node}"},
            {"node": "node-1"},
        )
    assert result.success is True
    mock_core.patch_node.assert_called_once_with(
        "node-1", {"spec": {"unschedulable": True}}
    )


def test_run_kube_action_uncordon_node(monkeypatch):
    executor = ActionExecutor()
    _patch_incluster(monkeypatch)
    mock_core = MagicMock()
    with patch("kubernetes.client.CoreV1Api", return_value=mock_core):
        result = executor.run_kube_action(
            IN_CLUSTER_CONTROLLER,
            {"kube_action": "uncordon_node", "node_name": "{node}"},
            {"node": "node-1"},
        )
    assert result.success is True
    mock_core.patch_node.assert_called_once_with(
        "node-1", {"spec": {"unschedulable": False}}
    )


def test_run_kube_action_patch_configmap(monkeypatch):
    executor = ActionExecutor()
    _patch_incluster(monkeypatch)
    mock_core = MagicMock()
    with patch("kubernetes.client.CoreV1Api", return_value=mock_core):
        result = executor.run_kube_action(
            IN_CLUSTER_CONTROLLER,
            {
                "kube_action": "patch_configmap",
                "name": "{configmap}",
                "namespace": "{namespace}",
                "data": {"feature_x_enabled": "{enabled}"},
            },
            {"configmap": "app-config", "namespace": "prod", "enabled": "true"},
        )
    assert result.success is True
    mock_core.patch_namespaced_config_map.assert_called_once_with(
        "app-config", "prod", {"data": {"feature_x_enabled": "true"}}
    )


def test_run_kube_action_drain_node_skips_daemonset_pods_and_evicts_rest(monkeypatch):
    executor = ActionExecutor()
    _patch_incluster(monkeypatch)
    mock_core = MagicMock()
    mock_core.list_pod_for_all_namespaces.return_value = MagicMock(
        items=[
            make_pod("web-1"),
            make_pod("web-2"),
            make_pod("fluentd-abc", daemonset_owned=True),
        ]
    )
    with patch("kubernetes.client.CoreV1Api", return_value=mock_core):
        result = executor.run_kube_action(
            IN_CLUSTER_CONTROLLER,
            {"kube_action": "drain_node", "node_name": "{node}"},
            {"node": "node-1"},
        )
    assert result.success is True
    mock_core.patch_node.assert_called_once_with(
        "node-1", {"spec": {"unschedulable": True}}
    )
    assert mock_core.create_namespaced_pod_eviction.call_count == 2
    evicted_names = {
        c.args[0] for c in mock_core.create_namespaced_pod_eviction.call_args_list
    }
    assert evicted_names == {"web-1", "web-2"}


def test_run_kube_action_drain_node_reports_eviction_failures(monkeypatch):
    executor = ActionExecutor()
    _patch_incluster(monkeypatch)
    mock_core = MagicMock()
    mock_core.list_pod_for_all_namespaces.return_value = MagicMock(
        items=[make_pod("web-1")]
    )
    mock_core.create_namespaced_pod_eviction.side_effect = ApiException(
        status=429, reason="Too Many Requests"
    )
    with patch("kubernetes.client.CoreV1Api", return_value=mock_core):
        result = executor.run_kube_action(
            IN_CLUSTER_CONTROLLER,
            {"kube_action": "drain_node", "node_name": "{node}"},
            {"node": "node-1"},
        )
    assert result.success is False
    assert "could not be evicted" in result.error


def test_run_kube_action_api_exception_maps_to_failure(monkeypatch):
    executor = ActionExecutor()
    _patch_incluster(monkeypatch)
    mock_apps = MagicMock()
    mock_apps.patch_namespaced_deployment.side_effect = ApiException(
        status=404, reason="Not Found"
    )
    with patch("kubernetes.client.AppsV1Api", return_value=mock_apps):
        result = executor.run_kube_action(
            IN_CLUSTER_CONTROLLER,
            {
                "kube_action": "rollout_restart",
                "resource": "deployment",
                "name": "{deployment}",
                "namespace": "{namespace}",
            },
            {"deployment": "missing", "namespace": "prod"},
        )
    assert result.success is False
    assert result.exit_code == 404
    assert "Not Found" in result.error
