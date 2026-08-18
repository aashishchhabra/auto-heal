import yaml
import os

# Populated at startup by src.main's lifespan via set_merged_actions() with
# discovered playbooks/scripts merged under config/actions.yaml. Kept as
# module state (rather than rebinding get_action_config itself) so that
# callers who did `from src.actions import get_action_config` still see
# the merged data once it's set - reassigning the module attribute after
# import does not affect names already bound elsewhere.
_merged_actions = None


def set_merged_actions(merged):
    global _merged_actions
    _merged_actions = merged


def load_actions_config():
    with open(os.path.join(os.path.dirname(__file__), "../config/actions.yaml")) as f:
        return yaml.safe_load(f)


def get_action_config(action_name):
    if _merged_actions is not None:
        return _merged_actions.get(action_name)
    config = load_actions_config()
    return config["actions"].get(action_name)


def load_controllers_config():
    with open(
        os.path.join(os.path.dirname(__file__), "../config/controllers.yaml")
    ) as f:
        return yaml.safe_load(f)


def get_controller_config(controller_name):
    config = load_controllers_config()
    return config["controllers"].get(controller_name)


def discover_actions():
    actions = {}
    playbook_dir = os.path.join(os.path.dirname(__file__), "../playbooks")
    script_dir = os.path.join(os.path.dirname(__file__), "../scripts")
    # Discover playbooks
    for fname in os.listdir(playbook_dir):
        if fname.endswith(".yml") or fname.endswith(".yaml"):
            action_name = os.path.splitext(fname)[0]
            actions[action_name] = {
                "playbook": f"playbooks/{fname}",
                "default_controller": "ansible_local",
            }
    # Discover scripts
    for fname in os.listdir(script_dir):
        if fname.endswith(".sh") or fname.endswith(".py"):
            action_name = os.path.splitext(fname)[0]
            actions[action_name] = {
                "script": f"scripts/{fname}",
                "default_controller": "local",
            }
    return actions
