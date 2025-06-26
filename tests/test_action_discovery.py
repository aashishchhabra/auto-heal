import os
import os.path
from src.actions import discover_actions


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
