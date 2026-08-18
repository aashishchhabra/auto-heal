import json
import os
import shlex
import subprocess
import tempfile
import logging
from typing import Dict, Any, Optional, Tuple

from src.vault import vault_client, VaultUnavailableError

logger = logging.getLogger("autoheal.executor")

# ssh's own exit code when it can't connect/authenticate, as opposed to a
# remote command that ran and returned this code itself.
SSH_CONNECTION_FAILURE_EXIT_CODE = 255


class ActionExecutionResult:
    def __init__(
        self,
        success: bool,
        stdout: str,
        stderr: str,
        exit_code: int,
        error: Optional[str] = None,
    ):
        self.success = success
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code
        self.error = error

    def as_dict(self):
        return {
            "success": self.success,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "error": self.error,
        }


class ActionExecutor:
    def run_playbook(
        self,
        playbook_path: str,
        extra_vars: Optional[Dict[str, Any]] = None,
        dry_run: bool = False,
    ) -> ActionExecutionResult:
        if dry_run:
            msg = (
                f"[DRY-RUN] Would execute playbook: {playbook_path} with vars: "
                f"{extra_vars}"
            )
            logger.info(msg)
            return ActionExecutionResult(
                success=True,
                stdout=msg,
                stderr="",
                exit_code=0,
                error=None,
            )
        cmd = ["ansible-playbook", playbook_path]
        if extra_vars:
            extra_vars_str = " ".join(f"{k}='{v}'" for k, v in extra_vars.items())
            cmd += ["--extra-vars", extra_vars_str]
        try:
            logger.info(f"Running playbook: {cmd}")
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            return ActionExecutionResult(
                success=proc.returncode == 0,
                stdout=proc.stdout,
                stderr=proc.stderr,
                exit_code=proc.returncode,
            )
        except Exception as e:
            logger.error(f"Playbook execution failed: {e}")
            return ActionExecutionResult(False, "", "", 1, error=str(e))

    def run_script(
        self, script_path: str, args: Optional[list] = None, dry_run: bool = False
    ) -> ActionExecutionResult:
        if dry_run:
            msg = f"[DRY-RUN] Would execute script: {script_path} with args: {args}"
            logger.info(msg)
            return ActionExecutionResult(
                success=True,
                stdout=msg,
                stderr="",
                exit_code=0,
                error=None,
            )
        cmd = [script_path]
        if args:
            cmd += args
        try:
            logger.info(f"Running script: {cmd}")
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            return ActionExecutionResult(
                success=proc.returncode == 0,
                stdout=proc.stdout,
                stderr=proc.stderr,
                exit_code=proc.returncode,
            )
        except Exception as e:
            logger.error(f"Script execution failed: {e}")
            return ActionExecutionResult(False, "", "", 1, error=str(e))

    def run_command(
        self,
        command_template: str,
        params: Optional[Dict[str, Any]] = None,
        dry_run: bool = False,
    ) -> ActionExecutionResult:
        """
        Run a raw shell command locally, e.g. an `oc`/`kubectl` one-liner
        defined directly in config/actions.yaml as `command:` rather than a
        playbook or script file. `{param}` placeholders in the template are
        substituted from `params`.
        """
        params = params or {}
        try:
            rendered = command_template.format(**{k: str(v) for k, v in params.items()})
        except (KeyError, IndexError) as e:
            return ActionExecutionResult(
                False, "", "", 1, error=f"Missing parameter {e} for command template"
            )
        if dry_run:
            msg = f"[DRY-RUN] Would run command: {rendered}"
            logger.info(msg)
            return ActionExecutionResult(
                success=True, stdout=msg, stderr="", exit_code=0, error=None
            )
        try:
            cmd = shlex.split(rendered)
            logger.info(f"Running command: {cmd}")
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            return ActionExecutionResult(
                success=proc.returncode == 0,
                stdout=proc.stdout,
                stderr=proc.stderr,
                exit_code=proc.returncode,
            )
        except Exception as e:
            logger.error(f"Command execution failed: {e}")
            return ActionExecutionResult(False, "", "", 1, error=str(e))

    @staticmethod
    def _build_remote_command(action: dict, params: Dict[str, Any]) -> Optional[str]:
        """
        Build the single shell command line to hand to the remote
        controller's shell over SSH. Every parameter value is shell-quoted
        before being placed in the command string, since (unlike the local
        run_playbook/run_script paths, which pass argv lists straight to
        subprocess with no shell involved) this string *is* interpreted by
        the remote user's shell.
        """
        if "command" in action:
            quoted_params = {k: shlex.quote(str(v)) for k, v in params.items()}
            return action["command"].format(**quoted_params)
        if "playbook" in action:
            parts = ["ansible-playbook", shlex.quote(action["playbook"])]
            if params:
                # JSON keeps types intact and sidesteps ambiguity around
                # quoting individual key=value pairs.
                parts += ["--extra-vars", shlex.quote(json.dumps(params))]
            return " ".join(parts)
        if "script" in action:
            parts = [shlex.quote(action["script"])]
            parts += [shlex.quote(str(v)) for v in params.values()]
            return " ".join(parts)
        return None

    def _resolve_ssh_key(
        self, ssh_key: Optional[str]
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Resolves `ssh_key` to an actual file path to hand to `ssh -i`. A
        plain path (the existing behavior) is returned unchanged. A
        "vault:<path>#<field>" reference (field defaults to
        "private_key" if omitted) is fetched from Vault and materialized
        to a private, caller-owned tempfile (mode 0600) - the key
        material never touches persistent disk, only one ephemeral file
        for the duration of a single ssh call.

        Returns (path_to_use_with_ssh, tempfile_path_to_clean_up_or_None).
        Raises VaultUnavailableError if a vault: reference can't be
        resolved - callers must treat that as a hard failure, not fall
        back to running ssh with no key.
        """
        if not ssh_key or not ssh_key.startswith("vault:"):
            return ssh_key, None
        ref = ssh_key.removeprefix("vault:")
        path, _, field = ref.partition("#")
        field = field or "private_key"
        secret = vault_client.get_secret(path)
        if field not in secret:
            raise VaultUnavailableError(
                f"Vault secret at '{path}' has no field '{field}'"
            )
        fd, tmp_path = tempfile.mkstemp(prefix="autoheal-sshkey-")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(secret[field])
            os.chmod(tmp_path, 0o600)
        except Exception:
            os.unlink(tmp_path)
            raise
        return tmp_path, tmp_path

    def run_remote(
        self,
        controller: dict,
        action: dict,
        params: Optional[Dict[str, Any]] = None,
        dry_run: bool = False,
    ) -> ActionExecutionResult:
        """
        Execute a playbook/script/command on a remote controller node over
        SSH. Auto-Healer never talks to a managed VM directly: it SSHes to
        the controller (an Ansible control node, or an oc-configured host)
        and runs the action there, exactly as run_playbook/run_script would
        locally - the controller's own inventory or kubeconfig decides how
        it reaches the actual target.
        """
        params = params or {}
        host = controller.get("host")
        ssh_user = controller.get("ssh_user")
        ssh_key = controller.get("ssh_key")
        if not host:
            return ActionExecutionResult(
                False,
                "",
                "",
                1,
                error="Controller has no 'host' configured for remote execution.",
            )
        if not ssh_user:
            return ActionExecutionResult(
                False,
                "",
                "",
                1,
                error="Controller has no 'ssh_user' configured for remote execution.",
            )

        try:
            remote_cmd = self._build_remote_command(action, params)
        except (KeyError, IndexError) as e:
            return ActionExecutionResult(
                False, "", "", 1, error=f"Missing parameter {e} for command template"
            )
        if remote_cmd is None:
            return ActionExecutionResult(
                False,
                "",
                "",
                1,
                error="No playbook, script, or command defined for action.",
            )

        if dry_run:
            msg = f"[DRY-RUN] Would SSH to {ssh_user}@{host} and run: {remote_cmd}"
            logger.info(msg)
            return ActionExecutionResult(
                success=True, stdout=msg, stderr="", exit_code=0, error=None
            )

        try:
            resolved_ssh_key, ssh_key_tmp_path = self._resolve_ssh_key(ssh_key)
        except VaultUnavailableError as e:
            logger.error(f"Failed to resolve SSH key from Vault: {e}")
            return ActionExecutionResult(
                False, "", "", 1, error=f"Failed to resolve SSH key from Vault: {e}"
            )

        try:
            ssh_cmd = [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=accept-new",
                "-o",
                "ConnectTimeout=10",
            ]
            if resolved_ssh_key:
                ssh_cmd += ["-i", resolved_ssh_key]
            ssh_cmd += [f"{ssh_user}@{host}", remote_cmd]

            try:
                logger.info(
                    f"Running remote command on {ssh_user}@{host}: {remote_cmd}"
                )
                proc = subprocess.run(
                    ssh_cmd, capture_output=True, text=True, timeout=600
                )
                if proc.returncode == SSH_CONNECTION_FAILURE_EXIT_CODE:
                    detail = proc.stderr.strip() or "SSH exited with code 255"
                    logger.error(
                        f"SSH connection to {ssh_user}@{host} failed: {detail}"
                    )
                    return ActionExecutionResult(
                        False,
                        proc.stdout,
                        proc.stderr,
                        proc.returncode,
                        error=f"SSH connection to {ssh_user}@{host} failed: {detail}",
                    )
                return ActionExecutionResult(
                    success=proc.returncode == 0,
                    stdout=proc.stdout,
                    stderr=proc.stderr,
                    exit_code=proc.returncode,
                )
            except subprocess.TimeoutExpired as e:
                logger.error(f"Remote execution on {host} timed out: {e}")
                return ActionExecutionResult(
                    False, "", "", 1, error=f"Remote execution timed out: {e}"
                )
            except Exception as e:
                logger.error(f"Remote execution on {host} failed: {e}")
                return ActionExecutionResult(False, "", "", 1, error=str(e))
        finally:
            if ssh_key_tmp_path:
                try:
                    os.unlink(ssh_key_tmp_path)
                except OSError:
                    pass
