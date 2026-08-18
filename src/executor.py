import datetime
import json
import os
import shlex
import subprocess
import tempfile
import logging
from typing import Dict, Any, List, Optional, Tuple

import kubernetes
import kubernetes.config
from kubernetes.client.exceptions import ApiException

from src.vault import resolve_vault_ref, VaultUnavailableError

logger = logging.getLogger("autoheal.executor")

# ssh's own exit code when it can't connect/authenticate, as opposed to a
# remote command that ran and returned this code itself.
SSH_CONNECTION_FAILURE_EXIT_CODE = 255

KUBE_RESTART_ANNOTATION = "kubectl.kubernetes.io/restartedAt"

# The closed set of kube_action verbs this executor knows how to run.
# Deliberately narrow: each one is one specific, reviewed API operation,
# not a generic "patch arbitrary JSON" escape hatch - new verbs get added
# here on purpose, not opened up by config alone.
KUBE_ACTION_VERBS = {
    "rollout_restart",
    "delete_pod",
    "scale",
    "cordon_node",
    "uncordon_node",
    "drain_node",
    "patch_configmap",
}


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

    def _resolve_secret_file(
        self, value: Optional[str], default_field: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Resolves `value` to an actual file path - used for anything that
        wants a secret handed to it as a file (ssh -i, an ssl_ca_cert
        path, a kubeconfig, a bearer token file). A plain path (the
        default) is returned unchanged. A "vault:<path>#<field>"
        reference (field defaults to `default_field` if omitted) is
        fetched from Vault and materialized to a private, caller-owned
        tempfile (mode 0600) - the secret never touches persistent disk,
        only one ephemeral file for the duration of a single use.

        Returns (path_to_use, tempfile_path_to_clean_up_or_None). Raises
        VaultUnavailableError if a vault: reference can't be resolved -
        callers must treat that as a hard failure, never silently
        proceeding without the secret.
        """
        if not value or not value.startswith("vault:"):
            return value, None
        secret_value = resolve_vault_ref(value, default_field)
        fd, tmp_path = tempfile.mkstemp(prefix="autoheal-secret-")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(secret_value)
            os.chmod(tmp_path, 0o600)
        except Exception:
            os.unlink(tmp_path)
            raise
        return tmp_path, tmp_path

    def _resolve_ssh_key(
        self, ssh_key: Optional[str]
    ) -> Tuple[Optional[str], Optional[str]]:
        """SSH keys default to the "private_key" field when Vault-backed."""
        return self._resolve_secret_file(ssh_key, "private_key")

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

    # ---------------------------------------------------------------
    # Direct Kubernetes API execution (kube_action). Unlike everything
    # above, this never shells out or SSHes anywhere - it talks to the
    # cluster's API server directly using the official kubernetes client,
    # with credentials scoped as narrowly as a RBAC Role allows rather
    # than a full kubeconfig with implicit broader access.
    # ---------------------------------------------------------------

    def _build_kube_configuration(
        self, controller: dict
    ) -> Tuple["kubernetes.client.Configuration", List[str]]:
        """
        Builds a kubernetes.client.Configuration for `controller`, plus a
        list of tempfile paths the caller must delete once done with it.
        Precedence: in_cluster > kubeconfig > api_server+token(+ca_cert).

        Raises VaultUnavailableError if a vault: reference can't be
        resolved, or ValueError if the controller has none of the above
        configured. Either way, whatever tempfiles were already created
        before the failure are cleaned up here - the caller never has to
        clean up after a raised exception from this method.
        """
        cleanup_paths: List[str] = []
        try:
            if controller.get("in_cluster"):
                configuration = kubernetes.client.Configuration()
                kubernetes.config.load_incluster_config(
                    client_configuration=configuration
                )
                return configuration, cleanup_paths

            kubeconfig = controller.get("kubeconfig")
            if kubeconfig:
                resolved_path, tmp = self._resolve_secret_file(kubeconfig, "kubeconfig")
                if tmp:
                    cleanup_paths.append(tmp)
                configuration = kubernetes.client.Configuration()
                kubernetes.config.load_kube_config(
                    config_file=resolved_path, client_configuration=configuration
                )
                return configuration, cleanup_paths

            api_server = controller.get("api_server")
            token_ref = controller.get("token")
            if api_server and token_ref:
                token_path, token_tmp = self._resolve_secret_file(token_ref, "token")
                if token_tmp:
                    cleanup_paths.append(token_tmp)
                with open(token_path) as f:
                    token_value = f.read().strip()

                configuration = kubernetes.client.Configuration()
                configuration.host = api_server
                configuration.api_key = {"authorization": token_value}
                configuration.api_key_prefix = {"authorization": "Bearer"}

                ca_cert_ref = controller.get("ca_cert")
                if ca_cert_ref:
                    ca_path, ca_tmp = self._resolve_secret_file(ca_cert_ref, "ca_cert")
                    if ca_tmp:
                        cleanup_paths.append(ca_tmp)
                    configuration.ssl_ca_cert = ca_path
                else:
                    logger.warning(
                        "kubeapi controller has no ca_cert configured; "
                        "TLS verification will be disabled for this call."
                    )
                    configuration.verify_ssl = False
                return configuration, cleanup_paths
        except Exception:
            for p in cleanup_paths:
                try:
                    os.unlink(p)
                except OSError:
                    pass
            raise

        raise ValueError(
            "Controller has no usable kubeapi credentials configured "
            "(need one of: in_cluster, kubeconfig, or api_server+token)."
        )

    @staticmethod
    def _render_kube_action_fields(
        action: dict, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Renders {param} templates in a kube_action's name/namespace/
        node_name/data fields. `resource` is a fixed choice (deployment,
        statefulset, ...), not user data, so it's passed through as-is.
        Raises KeyError/IndexError for a missing parameter, same
        convention as _build_remote_command/run_command.
        """
        rendered: Dict[str, Any] = {}
        if "resource" in action:
            rendered["resource"] = action["resource"]
        if "name" in action:
            rendered["name"] = action["name"].format(**params)
        if "namespace" in action:
            rendered["namespace"] = action["namespace"].format(**params)
        if "node_name" in action:
            rendered["node_name"] = action["node_name"].format(**params)
        if "data" in action:
            rendered["data"] = {
                k: str(v).format(**params) for k, v in action["data"].items()
            }
        return rendered

    @staticmethod
    def _describe_kube_action(verb: str, rendered: Dict[str, Any]) -> str:
        if verb in ("cordon_node", "uncordon_node", "drain_node"):
            return f"{verb} node '{rendered.get('node_name')}'"
        if verb == "patch_configmap":
            return (
                f"patch_configmap '{rendered.get('name')}' in namespace "
                f"'{rendered.get('namespace')}' with {rendered.get('data')}"
            )
        resource = rendered.get("resource", "deployment")
        return (
            f"{verb} {resource} '{rendered.get('name')}' in namespace "
            f"'{rendered.get('namespace')}'"
        )

    def run_kube_action(
        self,
        controller: dict,
        action: dict,
        params: Optional[Dict[str, Any]] = None,
        dry_run: bool = False,
    ) -> ActionExecutionResult:
        """
        Execute a structured Kubernetes API operation (`kube_action` in
        config/actions.yaml) directly against the cluster's API server -
        no SSH, no shelling out to oc/kubectl. See KUBE_ACTION_VERBS for
        the full set of supported operations.
        """
        params = params or {}
        verb = action.get("kube_action")
        if verb not in KUBE_ACTION_VERBS:
            return ActionExecutionResult(
                False, "", "", 1, error=f"Unknown kube_action '{verb}'"
            )

        try:
            rendered = self._render_kube_action_fields(action, params)
        except (KeyError, IndexError) as e:
            return ActionExecutionResult(
                False, "", "", 1, error=f"Missing parameter {e} for kube_action"
            )

        if dry_run:
            msg = f"[DRY-RUN] Would {self._describe_kube_action(verb, rendered)}"
            logger.info(msg)
            return ActionExecutionResult(
                success=True, stdout=msg, stderr="", exit_code=0, error=None
            )

        try:
            configuration, cleanup_paths = self._build_kube_configuration(controller)
        except VaultUnavailableError as e:
            return ActionExecutionResult(
                False,
                "",
                "",
                1,
                error=f"Failed to resolve kube credentials from Vault: {e}",
            )
        except Exception as e:
            return ActionExecutionResult(
                False, "", "", 1, error=f"Failed to build Kubernetes client config: {e}"
            )

        try:
            api_client = kubernetes.client.ApiClient(configuration)
            handler = getattr(self, f"_kube_{verb}")
            logger.info(
                f"Running kube_action: {self._describe_kube_action(verb, rendered)}"
            )
            return handler(api_client, rendered)
        except ApiException as e:
            logger.error(f"Kubernetes API error for kube_action '{verb}': {e}")
            return ActionExecutionResult(
                False,
                "",
                str(e.body or ""),
                e.status or 1,
                error=f"Kubernetes API error: {e.reason or e}",
            )
        except Exception as e:
            logger.error(f"kube_action '{verb}' failed: {e}")
            return ActionExecutionResult(False, "", "", 1, error=str(e))
        finally:
            for p in cleanup_paths:
                try:
                    os.unlink(p)
                except OSError:
                    pass

    def _kube_rollout_restart(
        self, api_client, rendered: dict
    ) -> ActionExecutionResult:
        apps = kubernetes.client.AppsV1Api(api_client)
        resource = rendered.get("resource", "deployment")
        name = rendered["name"]
        namespace = rendered["namespace"]
        restarted_at = datetime.datetime.now(datetime.UTC).isoformat()
        patch_body = {
            "spec": {
                "template": {
                    "metadata": {"annotations": {KUBE_RESTART_ANNOTATION: restarted_at}}
                }
            }
        }
        patch_fn = {
            "deployment": apps.patch_namespaced_deployment,
            "statefulset": apps.patch_namespaced_stateful_set,
            "daemonset": apps.patch_namespaced_daemon_set,
        }.get(resource)
        if patch_fn is None:
            return ActionExecutionResult(
                False,
                "",
                "",
                1,
                error=f"Unsupported resource '{resource}' for rollout_restart",
            )
        patch_fn(name, namespace, patch_body)
        summary = {
            "resource": resource,
            "name": name,
            "namespace": namespace,
            "restarted_at": restarted_at,
        }
        return ActionExecutionResult(True, json.dumps(summary), "", 0, error=None)

    def _kube_delete_pod(self, api_client, rendered: dict) -> ActionExecutionResult:
        core = kubernetes.client.CoreV1Api(api_client)
        name = rendered["name"]
        namespace = rendered["namespace"]
        core.delete_namespaced_pod(name, namespace)
        summary = {"pod": name, "namespace": namespace, "action": "deleted"}
        return ActionExecutionResult(True, json.dumps(summary), "", 0, error=None)

    def _kube_scale(self, api_client, rendered: dict) -> ActionExecutionResult:
        apps = kubernetes.client.AppsV1Api(api_client)
        resource = rendered.get("resource", "deployment")
        name = rendered["name"]
        namespace = rendered["namespace"]
        try:
            replicas = int(rendered["data"]["replicas"])
        except (KeyError, TypeError, ValueError):
            return ActionExecutionResult(
                False, "", "", 1, error="scale requires an integer 'replicas' in data"
            )
        patch_fn = {
            "deployment": apps.patch_namespaced_deployment_scale,
            "statefulset": apps.patch_namespaced_stateful_set_scale,
            "replicaset": apps.patch_namespaced_replica_set_scale,
        }.get(resource)
        if patch_fn is None:
            return ActionExecutionResult(
                False, "", "", 1, error=f"Unsupported resource '{resource}' for scale"
            )
        patch_fn(name, namespace, {"spec": {"replicas": replicas}})
        summary = {
            "resource": resource,
            "name": name,
            "namespace": namespace,
            "replicas": replicas,
        }
        return ActionExecutionResult(True, json.dumps(summary), "", 0, error=None)

    def _kube_cordon_node(self, api_client, rendered: dict) -> ActionExecutionResult:
        core = kubernetes.client.CoreV1Api(api_client)
        node_name = rendered["node_name"]
        core.patch_node(node_name, {"spec": {"unschedulable": True}})
        summary = {"node": node_name, "unschedulable": True}
        return ActionExecutionResult(True, json.dumps(summary), "", 0, error=None)

    def _kube_uncordon_node(self, api_client, rendered: dict) -> ActionExecutionResult:
        core = kubernetes.client.CoreV1Api(api_client)
        node_name = rendered["node_name"]
        core.patch_node(node_name, {"spec": {"unschedulable": False}})
        summary = {"node": node_name, "unschedulable": False}
        return ActionExecutionResult(True, json.dumps(summary), "", 0, error=None)

    def _kube_drain_node(self, api_client, rendered: dict) -> ActionExecutionResult:
        """
        Cordons the node, then evicts every pod on it that isn't owned by
        a DaemonSet (DaemonSet pods are pinned to the node and re-created
        there regardless, so evicting them is pointless - this matches
        `kubectl drain`'s default behavior of skipping them). Eviction
        goes through the Eviction API so PodDisruptionBudgets are
        respected; a pod blocked by its PDB is reported as a failure for
        this call rather than silently ignored, since "drained" should
        mean actually drained.
        """
        core = kubernetes.client.CoreV1Api(api_client)
        node_name = rendered["node_name"]
        core.patch_node(node_name, {"spec": {"unschedulable": True}})

        pods = core.list_pod_for_all_namespaces(
            field_selector=f"spec.nodeName={node_name}"
        )
        evicted, skipped, failed = [], [], []
        for pod in pods.items:
            owners = pod.metadata.owner_references or []
            if any(o.kind == "DaemonSet" for o in owners):
                skipped.append(pod.metadata.name)
                continue
            eviction = kubernetes.client.V1Eviction(
                metadata=kubernetes.client.V1ObjectMeta(
                    name=pod.metadata.name, namespace=pod.metadata.namespace
                )
            )
            try:
                core.create_namespaced_pod_eviction(
                    pod.metadata.name, pod.metadata.namespace, eviction
                )
                evicted.append(pod.metadata.name)
            except ApiException as e:
                failed.append({"pod": pod.metadata.name, "error": e.reason or str(e)})

        summary = {
            "node": node_name,
            "evicted": evicted,
            "skipped_daemonset_pods": skipped,
            "failed": failed,
        }
        if failed:
            return ActionExecutionResult(
                False,
                json.dumps(summary),
                "",
                1,
                error=f"{len(failed)} pod(s) could not be evicted from '{node_name}'",
            )
        return ActionExecutionResult(True, json.dumps(summary), "", 0, error=None)

    def _kube_patch_configmap(
        self, api_client, rendered: dict
    ) -> ActionExecutionResult:
        core = kubernetes.client.CoreV1Api(api_client)
        name = rendered["name"]
        namespace = rendered["namespace"]
        data = rendered.get("data") or {}
        core.patch_namespaced_config_map(name, namespace, {"data": data})
        summary = {"configmap": name, "namespace": namespace, "data": data}
        return ActionExecutionResult(True, json.dumps(summary), "", 0, error=None)
