"""
Project config discovery and I/O.

A project is identified by a `.ao/config.json` file in the project root,
discovered via upward directory traversal.
"""

import json
import os
import uuid

from ao.common.config import _ask_field

CONFIG_DIR = ".ao"
CONFIG_FILE = "config.json"


def find_project_root(start_path: str) -> str | None:
    """Walk up from start_path looking for .ao/config.json. Return the directory containing .ao/ or None."""
    path = os.path.abspath(start_path)
    while True:
        config_path = os.path.join(path, CONFIG_DIR, CONFIG_FILE)
        if os.path.isfile(config_path):
            return path
        parent = os.path.dirname(path)
        if parent == path:
            return None
        path = parent


def read_project_config(project_root: str) -> dict:
    """Read and return parsed .ao/config.json."""
    config_path = os.path.join(project_root, CONFIG_DIR, CONFIG_FILE)
    with open(config_path, encoding="utf-8") as f:
        return json.load(f)


def write_project_config(project_root: str, config: dict) -> None:
    """Write .ao/config.json."""
    ao_dir = os.path.join(project_root, CONFIG_DIR)
    os.makedirs(ao_dir, exist_ok=True)
    config_path = os.path.join(ao_dir, CONFIG_FILE)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
        f.write("\n")


def _is_ancestor_or_equal(ancestor: str, descendant: str) -> bool:
    """Check if ancestor is an ancestor of (or equal to) descendant."""
    ancestor = os.path.abspath(ancestor) + os.sep
    descendant = os.path.abspath(descendant) + os.sep
    return descendant.startswith(ancestor)


def setup_project_interactive(default_root: str, must_contain: str = None) -> str:
    """Prompt user to set up a new project. Returns the project root path.

    Args:
        default_root: Default directory to suggest as project root.
        must_contain: If set, the chosen root must be an ancestor of (or equal to) this path.
                      Used to prevent creating a project root deeper than the script being run.
    """
    print(f"No AO project associated with this agent. Enter the project root ({default_root}):")

    while True:
        root = _ask_field(
            "> ",
            lambda v: os.path.abspath(v.strip()),
            default=os.path.abspath(default_root),
            path_completion=True,
        )
        if not os.path.isdir(root):
            print(f"Directory does not exist: {root}")
            continue
        if must_contain and not _is_ancestor_or_equal(root, must_contain):
            print(f"Project root must be an ancestor of {must_contain}")
            continue
        break

    name = _ask_field(
        f"Project name (default: {os.path.basename(root)})\n> ",
        str,
        default=os.path.basename(root),
    )

    description = _ask_field(
        "Description (optional)\n> ",
        str,
        default="",
    )

    project_id = str(uuid.uuid4())
    config = {
        "project_id": project_id,
        "name": name,
        "description": description,
    }
    write_project_config(root, config)
    print(f"Created project '{name}' at {root}")
    return root
