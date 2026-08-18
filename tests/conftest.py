import pytest
from unittest.mock import patch, MagicMock
import os


@pytest.fixture(autouse=True, scope="session")
def clean_approvals_state_file():
    """
    Tests that don't override src.main.APPROVALS_STATE_PATH (most of them
    hit the real app, so they persist to the real logs/approvals.json)
    would otherwise leave that file behind after a test run. Wipe it
    before and after the session so the suite doesn't pollute a real
    developer's local state or leak entries between runs.
    """
    import src.main as main

    def _remove():
        for path in (main.APPROVALS_STATE_PATH, f"{main.APPROVALS_STATE_PATH}.tmp"):
            if os.path.exists(path):
                os.remove(path)

    _remove()
    yield
    _remove()


@pytest.fixture(autouse=True, scope="session")
def clean_cooldown_state_file():
    """Same reasoning as clean_approvals_state_file, for logs/cooldowns.json."""
    import src.main as main

    def _remove():
        for path in (main.COOLDOWN_STATE_PATH, f"{main.COOLDOWN_STATE_PATH}.tmp"):
            if os.path.exists(path):
                os.remove(path)

    _remove()
    yield
    _remove()


@pytest.fixture(autouse=True)
def reset_cooldown_tracker():
    """
    cooldown_tracker is a single module-level instance shared by every
    test in the session (like approval_queue). Unlike the approval queue,
    leftover cooldown records would silently block unrelated tests from
    executing the same action again - so reset the in-memory state before
    every test, not just once per session.
    """
    import src.main as main

    main.cooldown_tracker._last_run.clear()
    yield
    main.cooldown_tracker._last_run.clear()


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """
    rate_limiter is likewise a single module-level instance shared by
    every test. Without a reset, unrelated tests hammering /webhook back
    to back within the same test session (well within one 60s sliding
    window) would eventually start tripping 429s on each other.
    """
    import src.main as main

    main.rate_limiter._hits.clear()
    yield
    main.rate_limiter._hits.clear()


@pytest.fixture(autouse=True, scope="session")
def patch_subprocess_default():
    """
    Session-wide safety net: nothing in the suite should shell out for real
    (ansible-playbook, ssh, scripts) just because a test forgot to mock
    subprocess.run. Only subprocess.run is patched here - ActionExecutor's
    own methods are left alone so test_executor.py can exercise their real
    logic; other test files get those methods dummied out per-test by
    patch_executor below.
    """
    with patch("subprocess.run") as mock_subproc_run:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "mocked"
        mock_proc.stderr = ""
        mock_subproc_run.return_value = mock_proc
        yield


@pytest.fixture(autouse=True)
def patch_executor(monkeypatch, request):
    # test_executor.py tests ActionExecutor's real implementation (with
    # only subprocess.run mocked via the fixture above), so it must not
    # get its own methods replaced with dummies here. Skip *patching*,
    # not the test itself - pytest.skip() inside a fixture would skip
    # every test in the file outright.
    test_file = request.node.fspath if hasattr(request.node, "fspath") else ""
    if test_file and os.path.basename(str(test_file)) == "test_executor.py":
        yield
        return

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
    monkeypatch.setattr(
        "src.executor.ActionExecutor.run_command", lambda *a, **kw: DummyResult("cmd")
    )
    yield
