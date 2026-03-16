import argparse
import os
from ao.common.config import Config, _ask_field
from ao.common.constants import AO_CONFIG
from ao.common.project import (
    find_project_root,
    read_project_config,
    setup_project_interactive,
)


def _convert_playbook_mode(value: str) -> str:
    value = value.strip().lower()
    if value not in ("local", "cloud"):
        raise ValueError("Must be 'local' or 'cloud'")
    return value


def _convert_yes_no(value: str) -> bool:
    value = value.strip().lower()
    if value not in ("y", "n"):
        raise ValueError("Must be 'y' or 'n'")
    return value == "y"


def setup_project() -> None:
    """Set up .ao/config.json, prompting the user."""
    cwd = os.getcwd()
    existing_root = find_project_root(cwd)

    if existing_root == cwd:
        existing = read_project_config(existing_root)
        print(f"Project already configured: {existing.get('name')} ({existing.get('project_id')})")
        overwrite = _ask_field(
            "Overwrite? [y/N]\n> ",
            _convert_yes_no,
            default=False,
            error_message="Please enter 'y' or 'n'.",
        )
        if not overwrite:
            return

    setup_project_interactive(default_root=cwd)


def get_user_input() -> Config:
    # --- Playbook configuration ---
    playbook_mode = _ask_field(
        "Where do you want to host lessons? [local/cloud] (default: local)\n> ",
        _convert_playbook_mode,
        default="local",
        error_message="Please enter 'local' or 'cloud'.",
    )

    playbook_api_key = None
    if playbook_mode == "cloud":
        playbook_api_key = _ask_field(
            "Playbook API key:\n> ",
            str,
            default=os.environ.get("AO_API_KEY"),
            error_message="Please enter your API key.",
        )

    config = Config(
        playbook_mode=playbook_mode,
        playbook_api_key=playbook_api_key,
    )
    return config


def config_command():
    setup_project()
    print()
    config = get_user_input()
    config_file = AO_CONFIG
    config.to_yaml_file(config_file)


def config_command_parser():
    description = (
        "Run `ao config` before you debug your agents. This "
        "will prompt some configurations that you can choose. "
        "These will get saved in a default path or in --config_path "
        "which you can pass: `ao config --config_path some/path/config.yaml"
    )
    parser = argparse.ArgumentParser("Config", usage="ao-config", description=description)
    return parser


def main():
    parser = config_command_parser()
    parser.parse_args()
    config_command()


if __name__ == "__main__":
    main()
