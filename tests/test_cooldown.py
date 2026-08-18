import json
import os
import time

from src.cooldown import CooldownTracker, MAX_COOLDOWN_RETENTION_SECONDS


def make_tracker(tmp_path):
    return CooldownTracker(str(tmp_path / "cooldowns.json"))


def test_fresh_key_not_in_cooldown(tmp_path):
    tracker = make_tracker(tmp_path)
    assert tracker.seconds_remaining("k", 60) is None


def test_record_then_immediately_blocked(tmp_path):
    tracker = make_tracker(tmp_path)
    tracker.record("k")
    remaining = tracker.seconds_remaining("k", 60)
    assert remaining is not None
    assert 0 < remaining <= 60


def test_zero_or_missing_cooldown_seconds_never_blocks(tmp_path):
    tracker = make_tracker(tmp_path)
    tracker.record("k")
    assert tracker.seconds_remaining("k", 0) is None
    assert tracker.seconds_remaining("k", None) is None


def test_cooldown_clears_after_window_elapses(tmp_path, monkeypatch):
    tracker = make_tracker(tmp_path)
    base = 1_000_000.0
    monkeypatch.setattr(time, "time", lambda: base)
    tracker.record("k")
    assert tracker.seconds_remaining("k", 10) is not None
    # Still within the window.
    monkeypatch.setattr(time, "time", lambda: base + 5)
    assert tracker.seconds_remaining("k", 10) is not None
    # Window has elapsed.
    monkeypatch.setattr(time, "time", lambda: base + 11)
    assert tracker.seconds_remaining("k", 10) is None


def test_different_keys_are_independent(tmp_path):
    tracker = make_tracker(tmp_path)
    tracker.record("a")
    assert tracker.seconds_remaining("a", 60) is not None
    assert tracker.seconds_remaining("b", 60) is None


def test_lowering_cooldown_seconds_takes_effect_immediately(tmp_path, monkeypatch):
    tracker = make_tracker(tmp_path)
    base = 1_000_000.0
    monkeypatch.setattr(time, "time", lambda: base)
    tracker.record("k")
    # 30s later: a 60s cooldown still blocks...
    monkeypatch.setattr(time, "time", lambda: base + 30)
    assert tracker.seconds_remaining("k", 60) is not None
    # ...but a config change to a shorter cooldown clears it right away,
    # without needing a new record().
    assert tracker.seconds_remaining("k", 10) is None


def test_save_is_atomic_no_leftover_tmp_file(tmp_path):
    tracker = make_tracker(tmp_path)
    tracker.record("k")
    assert os.path.exists(tracker.state_path)
    assert not os.path.exists(f"{tracker.state_path}.tmp")


def test_persists_and_reloads_across_instances(tmp_path):
    state_path = str(tmp_path / "cooldowns.json")
    tracker1 = CooldownTracker(state_path)
    tracker1.record("k")

    # Simulate a process restart: a fresh instance over the same file.
    tracker2 = CooldownTracker(state_path)
    assert tracker2.seconds_remaining("k", 60) is not None


def test_load_missing_file_starts_empty(tmp_path):
    tracker = CooldownTracker(str(tmp_path / "does-not-exist.json"))
    assert tracker._last_run == {}


def test_load_corrupt_file_starts_empty(tmp_path):
    state_path = tmp_path / "cooldowns.json"
    state_path.write_text("{not valid json")
    tracker = CooldownTracker(str(state_path))
    assert tracker._last_run == {}


def test_prune_drops_stale_records_beyond_retention_cap(tmp_path, monkeypatch):
    tracker = make_tracker(tmp_path)
    now = 1_000_000.0
    monkeypatch.setattr(time, "time", lambda: now)
    tracker._last_run["stale"] = now - MAX_COOLDOWN_RETENTION_SECONDS - 1
    tracker._last_run["fresh"] = now
    with tracker.lock:
        tracker._save_locked()
    assert "stale" not in tracker._last_run
    assert "fresh" in tracker._last_run
    with open(tracker.state_path) as f:
        on_disk = json.load(f)
    assert "stale" not in on_disk
    assert "fresh" in on_disk


def test_make_key_scopes_by_event_controller_and_dedup_value():
    k1 = CooldownTracker.make_key("restart_deployment", "dc2-oc", "web")
    k2 = CooldownTracker.make_key("restart_deployment", "dc2-oc", "api")
    k3 = CooldownTracker.make_key("restart_deployment", "dc1-ansible", "web")
    assert len({k1, k2, k3}) == 3
