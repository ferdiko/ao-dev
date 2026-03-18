import argparse
import os
from ao.common.config import Config, _ask_field
from ao.common.constants import AO_CONFIG
from ao.common.user import read_user_id, setup_user_interactive
from ao.common.project import find_project_root, read_project_id, setup_project_interactive
from ao.server.database_manager import DB


def _convert_playbook_mode(value: str) -> str:
    value = value.strip().lower()
    if value not in ("local", "cloud"):
        raise ValueError("Must be 'local' or 'cloud'")
    return value


def get_playbook_input() -> Config:
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

    return Config(
        playbook_mode=playbook_mode,
        playbook_api_key=playbook_api_key,
    )


from ao.common.constants import WELCOME_ART


def config_command():
    print("Press Ctrl+C to exit at any time.\n")

    # --- User identity ---
    user_id = read_user_id()
    existing_user = None
    if user_id:
        row = DB.get_user(user_id)
        if row:
            existing_user = {"user_id": user_id, "full_name": row["full_name"], "email": row["email"]}

    if existing_user:
        print(f"User: {existing_user['full_name']} <{existing_user['email']}>\n"
              "Press enter to keep current values, or type to change.\n")
    else:
        print(WELCOME_ART)
        print("Welcome to Sovara! Let's get you set up.\n")

    user = setup_user_interactive(existing_user)
    DB.upsert_user(user["user_id"], user["full_name"], user["email"])

    # --- Project (reconfigure only, no creation) ---
    cwd = os.getcwd()
    existing_root = find_project_root(cwd)
    if existing_root:
        project_id = read_project_id(existing_root)
        row = DB.get_project(project_id)
        if row:
            existing_project = {"project_id": project_id, "name": row["name"], "description": row["description"] or ""}
        else:
            existing_project = {"project_id": project_id, "name": os.path.basename(existing_root), "description": ""}

        print(f"\nProject: {existing_project['name']}\n"
              "Press enter to keep current values, or type to change.\n")
        _, project = setup_project_interactive(
            default_root=existing_root,
            existing=existing_project,
        )
        DB.upsert_project(project["project_id"], project["name"], project["description"])
    else:
        print("\nNo AO project in this directory. Run ao-record to create one.\n")

    # --- Playbook ---
    print()
    config = get_playbook_input()
    config.to_yaml_file(AO_CONFIG)


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
    try:
        config_command()
    except (KeyboardInterrupt, EOFError):
        print("\nAborted.")
        return


if __name__ == "__main__":
    main()
