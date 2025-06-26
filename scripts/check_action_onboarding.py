#!/usr/bin/env python3
"""
CI check: Validate action onboarding and auto-discovery consistency.
- Ensures all playbooks/scripts are mapped or discoverable.
- Ensures no duplicate action names.
- Ensures all mapped files exist.
"""
import os
import sys
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_ACTIONS = os.path.join(ROOT, "config", "actions.yaml")
PLAYBOOKS_DIR = os.path.join(ROOT, "playbooks")
SCRIPTS_DIR = os.path.join(ROOT, "scripts")

errors = []


def load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f)


def main():
    # 1. Discover playbooks/scripts
    playbooks = [f for f in os.listdir(PLAYBOOKS_DIR) if f.endswith((".yml", ".yaml"))]
    scripts = [f for f in os.listdir(SCRIPTS_DIR) if f.endswith((".sh", ".py"))]
    discovered = set(os.path.splitext(f)[0] for f in playbooks + scripts)
    # 2. Load config actions
    config = load_yaml(CONFIG_ACTIONS)
    config_actions = config.get("actions", config)  # fallback for flat structure
    mapped = set(config_actions.keys())
    # 3. Check for duplicates
    duplicates = set(os.path.splitext(f)[0] for f in playbooks) & set(
        os.path.splitext(f)[0] for f in scripts
    )
    if duplicates:
        errors.append(
            f"Duplicate action names in playbooks and scripts: {sorted(duplicates)}"
        )
    # 4. Check all mapped files exist
    for name, entry in config_actions.items():
        if "playbook" in entry:
            path = os.path.join(ROOT, entry["playbook"])
            if not os.path.isfile(path):
                errors.append(
                    f"Mapped playbook for action '{name}' not found: "
                    f"{entry['playbook']}"
                )
        if "script" in entry:
            path = os.path.join(ROOT, entry["script"])
            if not os.path.isfile(path):
                errors.append(
                    f"Mapped script for action '{name}' not found: {entry['script']}"
                )
    # 5. Warn if any discovered actions are not mapped (optional, not error)
    unmapped = discovered - mapped
    if unmapped:
        print(f"[INFO] Unmapped actions (will be auto-discovered): {sorted(unmapped)}")
    # 6. Print errors and exit nonzero if any
    if errors:
        print("[ERROR] Action onboarding/auto-discovery check failed:")
        for e in errors:
            print(" -", e)
        sys.exit(1)
    print("[OK] Action onboarding/auto-discovery check passed.")


if __name__ == "__main__":
    main()
