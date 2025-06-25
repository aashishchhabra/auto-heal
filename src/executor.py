import subprocess
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("autoheal.executor")


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
        self, playbook_path: str, extra_vars: Optional[Dict[str, Any]] = None
    ) -> ActionExecutionResult:
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
        self, script_path: str, args: Optional[list] = None
    ) -> ActionExecutionResult:
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

    # Stub for SSH/API execution (to be implemented for remote controllers)
    def run_remote(
        self, controller: dict, action: dict, params: dict
    ) -> ActionExecutionResult:
        logger.warning("Remote execution not implemented yet.")
        return ActionExecutionResult(
            False, "", "", 1, error="Remote execution not implemented."
        )
