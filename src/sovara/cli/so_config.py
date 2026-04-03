import argparse
import os
from sovara.common.user import read_user_id, setup_user_interactive
from sovara.common.project import find_project_root, read_project_id, setup_project_interactive
from sovara.server.database import DB


from sovara.common.constants import WELCOME_ART


def _notify_running_server_about_user_change() -> None:
    """Best-effort nudge so an already-open UI refreshes local user state."""
    try:
        from sovara.cli.so_server import _server_http_request

        _server_http_request("POST", "/ui/refresh-user")
    except Exception:
        pass


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
    _notify_running_server_about_user_change()

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
        print("\nNo Sovara project in this directory. Run so-record to create one.\n")

def config_command_parser():
    description = (
        "Run `so-config` before you debug your agents. This "
        "will prompt some configurations that you can choose. "
        "These will get saved in a default path or in --config_path "
        "which you can pass: `so-config --config_path some/path/config.yaml`"
    )
    parser = argparse.ArgumentParser("Config", usage="so-config", description=description)
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
