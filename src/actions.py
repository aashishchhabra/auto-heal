import yaml
import os


def load_actions_config():
    with open(os.path.join(os.path.dirname(__file__), "../config/actions.yaml")) as f:
        return yaml.safe_load(f)


def get_action_config(action_name):
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
