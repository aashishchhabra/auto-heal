"""
Tests for src/audit.py: the hash-chained AuditChain writer, verify_chain,
the ECS mapping, and AuditShipper's syslog/http sinks.
"""

import json
import os

import pytest
import requests

from src.audit import (
    AuditChain,
    AuditShipper,
    GENESIS_HASH,
    to_ecs,
    verify_chain,
)


@pytest.fixture
def audit_path(tmp_path):
    return str(tmp_path / "audit.log")


def read_lines(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


# --- AuditChain -------------------------------------------------------


def test_first_entry_anchors_to_genesis(audit_path):
    chain = AuditChain(audit_path)
    finalized = chain.append({"action": "restart_service"})
    assert finalized["sequence"] == 1
    assert finalized["prev_hash"] == GENESIS_HASH
    assert "entry_hash" in finalized


def test_entries_link_sequentially(audit_path):
    chain = AuditChain(audit_path)
    first = chain.append({"action": "a"})
    second = chain.append({"action": "b"})
    third = chain.append({"action": "c"})
    assert [e["sequence"] for e in (first, second, third)] == [1, 2, 3]
    assert second["prev_hash"] == first["entry_hash"]
    assert third["prev_hash"] == second["entry_hash"]


def test_append_writes_to_file(audit_path):
    chain = AuditChain(audit_path)
    chain.append({"action": "restart_service"})
    chain.append({"action": "cleanup_disk"})
    lines = read_lines(audit_path)
    assert len(lines) == 2
    assert lines[0]["action"] == "restart_service"
    assert lines[1]["action"] == "cleanup_disk"


def test_entry_hash_is_deterministic_given_same_fields(audit_path):
    chain = AuditChain(audit_path)
    finalized = chain.append({"action": "x", "z_field": 1, "a_field": 2})
    from src.audit import _hash_entry

    recomputed = _hash_entry({k: v for k, v in finalized.items() if k != "entry_hash"})
    assert recomputed == finalized["entry_hash"]


def test_chain_resumes_correctly_across_new_instance(audit_path):
    # Simulates a process restart: a fresh AuditChain pointed at the same
    # file must continue the chain, not restart it.
    AuditChain(audit_path).append({"action": "a"})
    second_instance = AuditChain(audit_path)
    finalized = second_instance.append({"action": "b"})
    assert finalized["sequence"] == 2
    first_hash = read_lines(audit_path)[0]["entry_hash"]
    assert finalized["prev_hash"] == first_hash


def test_chain_self_heals_after_file_removed_externally(audit_path):
    # No in-memory caching across appends (see AuditChain's docstring) -
    # if the file vanishes (rotation, a test fixture wiping state), the
    # next append must start a fresh, correctly-anchored chain rather
    # than continuing a stale in-memory sequence.
    chain = AuditChain(audit_path)
    chain.append({"action": "a"})
    chain.append({"action": "b"})
    os.remove(audit_path)
    finalized = chain.append({"action": "c"})
    assert finalized["sequence"] == 1
    assert finalized["prev_hash"] == GENESIS_HASH


def test_chain_starts_new_segment_on_unparseable_tail(audit_path, caplog):
    with open(audit_path, "w") as f:
        f.write("not valid json\n")
    chain = AuditChain(audit_path)
    finalized = chain.append({"action": "a"})
    assert finalized["sequence"] == 1
    assert finalized["prev_hash"] == GENESIS_HASH


def test_chain_starts_new_segment_on_legacy_unchained_tail(audit_path):
    # Pre-hash-chain audit.log entries have no sequence/prev_hash/entry_hash.
    with open(audit_path, "w") as f:
        f.write(json.dumps({"action": "old_entry", "user": "admin-key"}) + "\n")
    chain = AuditChain(audit_path)
    finalized = chain.append({"action": "new_entry"})
    assert finalized["sequence"] == 1
    assert finalized["prev_hash"] == GENESIS_HASH


# --- verify_chain -------------------------------------------------------


def test_verify_empty_or_missing_file_is_ok(audit_path):
    result = verify_chain(audit_path)
    assert result["ok"] is True
    assert result["entries_checked"] == 0


def test_verify_valid_chain_is_ok(audit_path):
    chain = AuditChain(audit_path)
    for i in range(5):
        chain.append({"action": f"action-{i}"})
    result = verify_chain(audit_path)
    assert result["ok"] is True
    assert result["entries_checked"] == 5
    assert result["first_broken_line"] is None
    # A brand new, never-rotated chain's first entry trivially looks
    # like "sequence=1, prev_hash=GENESIS_HASH" - same as a real restart
    # mid-file - but it isn't one, so it must not show up here.
    assert result["segment_boundaries"] == []


def test_verify_detects_modified_entry(audit_path):
    chain = AuditChain(audit_path)
    chain.append({"action": "a"})
    chain.append({"action": "b"})
    chain.append({"action": "c"})

    lines = open(audit_path).readlines()
    tampered = json.loads(lines[1])
    tampered["action"] = "TAMPERED"  # entry_hash no longer matches content
    lines[1] = json.dumps(tampered) + "\n"
    with open(audit_path, "w") as f:
        f.writelines(lines)

    result = verify_chain(audit_path)
    assert result["ok"] is False
    assert result["first_broken_line"] == 2


def test_verify_detects_deleted_entry(audit_path):
    chain = AuditChain(audit_path)
    chain.append({"action": "a"})
    chain.append({"action": "b"})
    chain.append({"action": "c"})

    lines = open(audit_path).readlines()
    del lines[1]  # remove the middle entry - breaks the prev_hash link
    with open(audit_path, "w") as f:
        f.writelines(lines)

    result = verify_chain(audit_path)
    assert result["ok"] is False
    assert result["first_broken_line"] == 2


def test_verify_detects_reordered_entries(audit_path):
    chain = AuditChain(audit_path)
    chain.append({"action": "a"})
    chain.append({"action": "b"})

    lines = open(audit_path).readlines()
    with open(audit_path, "w") as f:
        f.writelines([lines[1], lines[0]])

    result = verify_chain(audit_path)
    assert result["ok"] is False


def test_verify_tolerates_legacy_prefix(audit_path):
    with open(audit_path, "w") as f:
        f.write(json.dumps({"action": "legacy", "user": "x"}) + "\n")
    chain = AuditChain(audit_path)
    chain.append({"action": "new"})
    chain.append({"action": "newer"})

    result = verify_chain(audit_path)
    assert result["ok"] is True
    assert result["legacy_entries"] == 1
    assert result["entries_checked"] == 2


def test_verify_removed_file_starts_a_clean_untagged_segment(audit_path):
    # Deleting the file (as opposed to rotating it aside and keeping its
    # content) erases the prior segment entirely - the resulting file is
    # indistinguishable from a chain that never existed before, so it's
    # correctly NOT reported as a "boundary": there's nothing left in
    # the file for verify() to have detected a discontinuity against.
    chain = AuditChain(audit_path)
    chain.append({"action": "a"})
    chain.append({"action": "b"})
    os.remove(audit_path)
    chain.append({"action": "c"})

    result = verify_chain(audit_path)
    assert result["ok"] is True
    assert result["segment_boundaries"] == []
    assert result["entries_checked"] == 1


def test_verify_records_boundary_when_two_segments_are_concatenated(
    audit_path, tmp_path
):
    # The realistic case a segment boundary exists to catch: rotated-out
    # history (audit.log.1, audit.log.2, ...) reassembled into one file
    # for a compliance review. Each segment is independently valid and
    # genesis-anchored; verify() must accept the join as legitimate,
    # not as tampering, while still reporting exactly where it is.
    segment1_path = str(tmp_path / "segment1.log")
    AuditChain(segment1_path).append({"action": "a"})
    AuditChain(segment1_path).append({"action": "b"})

    segment2_path = str(tmp_path / "segment2.log")
    AuditChain(segment2_path).append({"action": "c"})

    with open(audit_path, "w") as out:
        out.writelines(open(segment1_path).readlines())
        out.writelines(open(segment2_path).readlines())

    result = verify_chain(audit_path)
    assert result["ok"] is True
    assert result["segment_boundaries"] == [3]
    assert result["entries_checked"] == 3


def test_verify_rejects_malformed_json_line(audit_path):
    with open(audit_path, "w") as f:
        f.write("{not json\n")
    result = verify_chain(audit_path)
    assert result["ok"] is False
    assert result["first_broken_line"] == 1


# --- to_ecs ---------------------------------------------------------------


def test_to_ecs_maps_core_fields():
    entry = {
        "timestamp": "2026-01-01T00:00:00Z",
        "user": "admin-key",
        "role": "admin",
        "action": "restart_service",
        "controller": "ansible_local",
        "controller_type": "ansible",
        "parameters": {"service_name": "nginx"},
        "execution": {"success": True, "stdout": "ok", "error": None},
        "client_ip": "10.0.0.1",
        "sequence": 3,
        "prev_hash": "a" * 64,
        "entry_hash": "b" * 64,
    }
    doc = to_ecs(entry)
    assert doc["@timestamp"] == "2026-01-01T00:00:00Z"
    assert doc["event"]["action"] == "restart_service"
    assert doc["event"]["outcome"] == "success"
    assert doc["event"]["sequence"] == 3
    assert doc["event"]["hash"] == "b" * 64
    assert doc["event"]["type"] == ["change"]
    assert doc["user"]["name"] == "admin-key"
    assert doc["user"]["roles"] == ["admin"]
    assert doc["source"]["ip"] == "10.0.0.1"
    assert doc["service"]["name"] == "auto-healer"
    assert doc["auto_healer"]["controller"] == "ansible_local"
    assert doc["auto_healer"]["parameters"] == {"service_name": "nginx"}


def test_to_ecs_maps_blocked_entry():
    entry = {
        "timestamp": "2026-01-01T00:00:00Z",
        "action": "restart_deployment",
        "blocked_reason": "cooldown",
        "execution": {"success": False, "error": "blocked-by-cooldown"},
    }
    doc = to_ecs(entry)
    assert doc["event"]["type"] == ["denied"]
    assert doc["event"]["outcome"] == "failure"
    assert doc["event"]["reason"] == "cooldown"


def test_to_ecs_maps_unknown_outcome_when_no_execution():
    doc = to_ecs({"action": "x"})
    assert doc["event"]["outcome"] == "unknown"


def test_to_ecs_omits_absent_source_ip():
    doc = to_ecs({"action": "x", "client_ip": None})
    assert "source" not in doc


# --- AuditShipper -----------------------------------------------------


def test_shipper_disabled_by_default_does_nothing(tmp_path, monkeypatch):
    # No config/audit.yaml at all.
    shipper = AuditShipper(str(tmp_path / "nonexistent-audit.yaml"))
    calls = []
    monkeypatch.setattr("requests.request", lambda *a, **kw: calls.append(1))
    shipper.ship({"action": "x"})
    assert calls == []


def test_shipper_http_sink_posts_ecs_document(tmp_path, monkeypatch):
    config_path = tmp_path / "audit.yaml"
    config_path.write_text(
        "shipping:\n"
        "  http:\n"
        "    enabled: true\n"
        "    url: 'https://es.example.com/idx/_doc'\n"
        "    headers:\n"
        "      Authorization: 'ApiKey abc123'\n"
    )
    shipper = AuditShipper(str(config_path))

    captured = {}

    class DummyResponse:
        status_code = 200
        text = ""

    def fake_request(method, url, json=None, headers=None, timeout=None):
        captured["method"] = method
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return DummyResponse()

    monkeypatch.setattr("requests.request", fake_request)
    shipper.ship({"action": "restart_service", "execution": {"success": True}})

    assert captured["method"] == "POST"
    assert captured["url"] == "https://es.example.com/idx/_doc"
    assert captured["headers"]["Authorization"] == "ApiKey abc123"
    assert captured["json"]["event"]["action"] == "restart_service"


def test_shipper_http_sink_resolves_vault_header(tmp_path, monkeypatch):
    config_path = tmp_path / "audit.yaml"
    config_path.write_text(
        "shipping:\n"
        "  http:\n"
        "    enabled: true\n"
        "    url: 'https://es.example.com/idx/_doc'\n"
        "    headers:\n"
        "      Authorization: 'vault:secret/data/audit#authorization'\n"
    )
    shipper = AuditShipper(str(config_path))
    monkeypatch.setattr("src.audit.resolve_vault_ref", lambda value: "resolved-token")

    captured = {}

    class DummyResponse:
        status_code = 200
        text = ""

    def fake_request(method, url, json=None, headers=None, timeout=None):
        captured["headers"] = headers
        return DummyResponse()

    monkeypatch.setattr("requests.request", fake_request)
    shipper.ship({"action": "x"})
    assert captured["headers"]["Authorization"] == "resolved-token"


def test_shipper_http_sink_failure_does_not_raise(tmp_path, monkeypatch):
    config_path = tmp_path / "audit.yaml"
    config_path.write_text(
        "shipping:\n"
        "  http:\n"
        "    enabled: true\n"
        "    url: 'https://es.example.com/idx/_doc'\n"
    )
    shipper = AuditShipper(str(config_path))
    monkeypatch.setattr(
        "requests.request",
        lambda *a, **kw: (_ for _ in ()).throw(requests.ConnectionError("down")),
    )
    # Must not raise - shipping is best-effort.
    shipper.ship({"action": "x"})


def test_shipper_http_sink_non_2xx_does_not_raise(tmp_path, monkeypatch):
    config_path = tmp_path / "audit.yaml"
    config_path.write_text(
        "shipping:\n"
        "  http:\n"
        "    enabled: true\n"
        "    url: 'https://es.example.com/idx/_doc'\n"
    )
    shipper = AuditShipper(str(config_path))

    class DummyResponse:
        status_code = 500
        text = "internal error"

    monkeypatch.setattr("requests.request", lambda *a, **kw: DummyResponse())
    shipper.ship({"action": "x"})  # must not raise


def test_shipper_syslog_sink_emits_via_handler(tmp_path, monkeypatch):
    config_path = tmp_path / "audit.yaml"
    config_path.write_text(
        "shipping:\n"
        "  syslog:\n"
        "    enabled: true\n"
        "    host: 'logs.example.com'\n"
        "    port: 514\n"
        "    protocol: 'udp'\n"
    )
    shipper = AuditShipper(str(config_path))

    emitted = []

    class DummyHandler:
        def emit(self, record):
            emitted.append(record.getMessage())

    monkeypatch.setattr(shipper, "_get_syslog_handler", lambda cfg: DummyHandler())
    shipper.ship({"action": "restart_service", "execution": {"success": True}})

    assert len(emitted) == 1
    payload = json.loads(emitted[0])
    assert payload["event"]["action"] == "restart_service"


def test_shipper_syslog_sink_failure_does_not_raise(tmp_path, monkeypatch):
    config_path = tmp_path / "audit.yaml"
    config_path.write_text(
        "shipping:\n"
        "  syslog:\n"
        "    enabled: true\n"
        "    host: 'unreachable.invalid'\n"
    )
    shipper = AuditShipper(str(config_path))
    monkeypatch.setattr(
        shipper,
        "_get_syslog_handler",
        lambda cfg: (_ for _ in ()).throw(OSError("connection refused")),
    )
    shipper.ship({"action": "x"})  # must not raise


def test_shipper_syslog_unsupported_protocol_does_not_raise(tmp_path):
    config_path = tmp_path / "audit.yaml"
    config_path.write_text(
        "shipping:\n" "  syslog:\n" "    enabled: true\n" "    protocol: 'tls'\n"
    )
    shipper = AuditShipper(str(config_path))
    shipper.ship({"action": "x"})  # logs an error, doesn't raise


def test_shipper_syslog_handler_cached_across_calls(tmp_path):
    config_path = tmp_path / "audit.yaml"
    config_path.write_text(
        "shipping:\n"
        "  syslog:\n"
        "    enabled: true\n"
        "    host: 'localhost'\n"
        "    port: 1514\n"
    )
    shipper = AuditShipper(str(config_path))
    cfg = shipper._config["shipping"]["syslog"]
    handler1 = shipper._get_syslog_handler(cfg)
    handler2 = shipper._get_syslog_handler(cfg)
    assert handler1 is handler2
    handler1.close()


def test_shipper_malformed_config_file_disables_shipping(tmp_path, monkeypatch):
    config_path = tmp_path / "audit.yaml"
    config_path.write_text("not: valid: yaml: [")
    shipper = AuditShipper(str(config_path))
    calls = []
    monkeypatch.setattr("requests.request", lambda *a, **kw: calls.append(1))
    shipper.ship({"action": "x"})
    assert calls == []
