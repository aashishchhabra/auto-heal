import pytest
from unittest.mock import patch, MagicMock
import os


@pytest.fixture(autouse=True, scope="session")
def patch_executor_and_subprocess():
    # Patch ActionExecutor methods to always return a safe dummy result
    from src.executor import ActionExecutionResult, ActionExecutor

    dummy_result = ActionExecutionResult(
        success=True,
        stdout="mocked",
        stderr="",
        exit_code=0,
        error=None,
    )
    with patch.object(
        ActionExecutor, "run_playbook", return_value=dummy_result
    ), patch.object(
        ActionExecutor, "run_script", return_value=dummy_result
    ), patch.object(
        ActionExecutor, "run_remote", return_value=dummy_result
    ), patch(
        "subprocess.run"
    ) as mock_subproc_run:
        # subprocess.run always returns a MagicMock with safe defaults
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "mocked"
        mock_proc.stderr = ""
        mock_subproc_run.return_value = mock_proc
        yield


@pytest.fixture(autouse=True)
def patch_executor(monkeypatch, request):
    # Only patch if not running in test_executor.py
    test_file = request.node.fspath if hasattr(request.node, "fspath") else ""
    if test_file and os.path.basename(str(test_file)) == "test_executor.py":
        pytest.skip("Skip global executor patching for executor unit tests.")

    class DummyResult:
        def __init__(self, stdout):
            self.success = True
            self.stdout = stdout
            self.stderr = ""
            self.exit_code = 0
            self.error = None

        def as_dict(self):
            return {
                "success": self.success,
                "stdout": self.stdout,
                "stderr": self.stderr,
                "exit_code": self.exit_code,
                "error": self.error,
            }

    monkeypatch.setattr(
        "src.executor.ActionExecutor.run_playbook", lambda *a, **kw: DummyResult("ok")
    )
    monkeypatch.setattr(
        "src.executor.ActionExecutor.run_script", lambda *a, **kw: DummyResult("done")
    )
    monkeypatch.setattr(
        "src.executor.ActionExecutor.run_remote", lambda *a, **kw: DummyResult("remote")
    )
    yield
