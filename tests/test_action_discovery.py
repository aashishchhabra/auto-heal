import os
import os.path
import pytest
from src.actions import discover_actions, get_action_config, set_merged_actions
import src.actions


@pytest.fixture(autouse=True)
def reset_merged_actions():
    # get_action_config falls back to config/actions.yaml on disk when no
    # merge has been set; make sure tests don't leak state into each other.
    yield
    set_merged_actions(None)


def test_get_action_config_uses_merged_actions_once_set():
    set_merged_actions({"custom_action": {"script": "scripts/custom.sh"}})
    assert get_action_config("custom_action") == {"script": "scripts/custom.sh"}
    # Not present in config/actions.yaml, so without the merge this would be None
    assert get_action_config("not_in_merge") is None


def test_get_action_config_falls_back_to_disk_when_unset():
    assert src.actions._merged_actions is None
    config = get_action_config("restart_service")
    assert config["playbook"] == "playbooks/restart_service.yml"


def test_explicit_config_actions_take_priority_over_discovered():
    # config/actions.yaml gives restart_service a default service_name
    # parameter; the plain directory scan does not. The merge must keep
    # the explicit, richer definition rather than the discovered one.
    discovered = discover_actions()
    assert "parameters" not in discovered.get("restart_service", {})
    explicit = {
        "restart_service": {
            "playbook": "playbooks/restart_service.yml",
            "default_controller": "ansible_local",
            "parameters": {"service_name": "nginx"},
        }
    }
    merged = {**discovered, **explicit}
    set_merged_actions(merged)
    config = get_action_config("restart_service")
    assert config["parameters"]["service_name"] == "nginx"


def test_discover_actions_ignores_non_playbook_files(tmp_path, monkeypatch):
    # Setup temp playbooks/scripts dirs with invalid files
    playbook_dir = tmp_path / "playbooks"
    script_dir = tmp_path / "scripts"
    playbook_dir.mkdir()
    script_dir.mkdir()
    # Valid playbook
    (playbook_dir / "valid_playbook.yml").write_text("---\n- hosts: all\n  tasks: []\n")
    # Invalid file
    (playbook_dir / "README.txt").write_text("not a playbook")
    # Valid script
    (script_dir / "valid_script.sh").write_text("#!/bin/bash\necho ok\n")
    # Invalid file
    (script_dir / "notes.md").write_text("not a script")
    # Patch os.path.join to redirect playbooks/scripts to temp dirs
    orig_join = os.path.join

    def join_patch(*args):
        if len(args) >= 2 and args[1] == "../playbooks":
            return str(playbook_dir)
        if len(args) >= 2 and args[1] == "../scripts":
            return str(script_dir)
        return orig_join(*args)

    monkeypatch.setattr(os.path, "join", join_patch)
    actions = discover_actions()
    assert "valid_playbook" in actions
    assert "valid_script" in actions
    assert "README" not in actions
    assert "notes" not in actions


def test_discover_actions_duplicate_names(tmp_path, monkeypatch):
    playbook_dir = tmp_path / "playbooks"
    script_dir = tmp_path / "scripts"
    playbook_dir.mkdir()
    script_dir.mkdir()
    # Both have a file named "foo"
    (playbook_dir / "foo.yml").write_text("---\n- hosts: all\n  tasks: []\n")
    (script_dir / "foo.sh").write_text("#!/bin/bash\necho ok\n")
    orig_join = os.path.join

    def join_patch(*args):
        if len(args) >= 2 and args[1] == "../playbooks":
            return str(playbook_dir)
        if len(args) >= 2 and args[1] == "../scripts":
            return str(script_dir)
        return orig_join(*args)

    monkeypatch.setattr(os.path, "join", join_patch)
    actions = discover_actions()
    # Last one wins (script overwrites playbook)
    assert actions["foo"]["script"] == "scripts/foo.sh"
    assert "playbook" not in actions["foo"]


def test_discover_actions_missing_default_controller(tmp_path, monkeypatch):
    playbook_dir = tmp_path / "playbooks"
    script_dir = tmp_path / "scripts"
    playbook_dir.mkdir()
    script_dir.mkdir()  # Ensure scripts dir exists
    (playbook_dir / "bar.yml").write_text("---\n- hosts: all\n  tasks: []\n")
    orig_join = os.path.join

    def join_patch(*args):
        if len(args) >= 2 and args[1] == "../playbooks":
            return str(playbook_dir)
        if len(args) >= 2 and args[1] == "../scripts":
            return str(script_dir)
        return orig_join(*args)

    monkeypatch.setattr(os.path, "join", join_patch)
    actions = discover_actions()
    # Should always set default_controller
    assert actions["bar"]["default_controller"] == "ansible_local"
