import time

from src.ratelimit import RateLimiter


def make_limiter(tmp_path, config_text=None):
    config_path = tmp_path / "rate_limits.yaml"
    if config_text is not None:
        config_path.write_text(config_text)
    return RateLimiter(str(config_path))


def test_missing_config_file_uses_defaults(tmp_path):
    limiter = make_limiter(tmp_path)
    assert limiter.limit_for_role("admin") == 60
    assert limiter.limit_for_role(None) == 60
    assert limiter.limit_for_action("restart_service") is None


def test_config_role_and_action_overrides(tmp_path):
    limiter = make_limiter(
        tmp_path,
        """
default:
  requests_per_minute: 60
per_role:
  readonly:
    requests_per_minute: 5
per_action:
  restart_deployment:
    requests_per_minute: 2
""",
    )
    assert limiter.limit_for_role("readonly") == 5
    assert limiter.limit_for_role("admin") == 60  # not overridden, falls to default
    assert limiter.limit_for_action("restart_deployment") == 2
    assert limiter.limit_for_action("restart_service") is None


def test_corrupt_config_falls_back_to_defaults(tmp_path):
    config_path = tmp_path / "rate_limits.yaml"
    config_path.write_text("{not: valid: yaml: [")
    limiter = RateLimiter(str(config_path))
    assert limiter.limit_for_role("admin") == 60


def test_allows_up_to_the_limit_then_blocks(tmp_path):
    limiter = make_limiter(tmp_path)
    for _ in range(3):
        assert limiter.check("k", 3) is None
    retry_after = limiter.check("k", 3)
    assert retry_after is not None
    assert retry_after > 0


def test_blocked_call_is_not_itself_recorded(tmp_path):
    limiter = make_limiter(tmp_path)
    assert limiter.check("k", 1) is None
    assert limiter.check("k", 1) is not None
    # Still blocked - the rejected attempt didn't consume another slot
    # that would somehow un-stick it.
    assert limiter.check("k", 1) is not None


def test_window_slides_and_frees_up_capacity(monkeypatch, tmp_path):
    limiter = make_limiter(tmp_path)
    base = 1_000_000.0
    monkeypatch.setattr(time, "time", lambda: base)
    assert limiter.check("k", 1, window_seconds=10) is None
    assert limiter.check("k", 1, window_seconds=10) is not None

    monkeypatch.setattr(time, "time", lambda: base + 11)
    assert limiter.check("k", 1, window_seconds=10) is None


def test_zero_or_none_limit_never_blocks(tmp_path):
    limiter = make_limiter(tmp_path)
    for _ in range(10):
        assert limiter.check("k", 0) is None
        assert limiter.check("k", None) is None


def test_keys_are_independent(tmp_path):
    limiter = make_limiter(tmp_path)
    assert limiter.check("a", 1) is None
    assert limiter.check("a", 1) is not None
    assert limiter.check("b", 1) is None
