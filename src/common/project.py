"""
Project config discovery and I/O.

A project is identified by a `.ao/.project_id` file in the project root
containing the project UUID. Project metadata (name, description) lives
in the database's projects table.
"""

import os
import uuid

from ao.common.config import _ask_field, green

CONFIG_DIR = ".ao"
PROJECT_ID_FILE = ".project_id"


def find_project_root(start_path: str) -> str | None:
    """Walk up from start_path looking for .ao/.project_id. Return the directory or None."""
    path = os.path.abspath(start_path)
    while True:
        id_path = os.path.join(path, CONFIG_DIR, PROJECT_ID_FILE)
        if os.path.isfile(id_path):
            return path
        parent = os.path.dirname(path)
        if parent == path:
            return None
        path = parent


def read_project_id(project_root: str) -> str:
    """Read project UUID from .ao/.project_id."""
    id_path = os.path.join(project_root, CONFIG_DIR, PROJECT_ID_FILE)
    with open(id_path, encoding="utf-8") as f:
        return f.read().strip()


def write_project_id(project_root: str, project_id: str) -> None:
    """Write project UUID to .ao/.project_id."""
    ao_dir = os.path.join(project_root, CONFIG_DIR)
    os.makedirs(ao_dir, exist_ok=True)
    id_path = os.path.join(ao_dir, PROJECT_ID_FILE)
    with open(id_path, "w", encoding="utf-8") as f:
        f.write(project_id + "\n")


def _is_ancestor_or_equal(ancestor: str, descendant: str) -> bool:
    """Check if ancestor is an ancestor of (or equal to) descendant."""
    ancestor = os.path.abspath(ancestor) + os.sep
    descendant = os.path.abspath(descendant) + os.sep
    return descendant.startswith(ancestor)


def setup_project_interactive(default_root: str, existing: dict = None, must_contain: str = None) -> tuple[str, dict]:
    """Prompt user for project root, name, and description.

    Args:
        default_root: Default directory to suggest as project root.
        existing: Existing project dict from DB (with project_id, name, description), if reconfiguring.
        must_contain: If set, the chosen root must be an ancestor of (or equal to) this path.

    Returns:
        (project_root, project_config_dict)
    """
    if existing:
        print(f"Project root: {green(default_root)}")
    else:
        print(f"Project root (default: {default_root})")

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

    default_name = existing["name"] if existing else os.path.basename(root)
    if existing:
        print(f"Project name: {green(default_name)}")
    else:
        print(f"Project name (default: {default_name})")
    name = _ask_field("> ", str, default=default_name)

    default_description = existing.get("description", "") if existing else ""
    if existing and default_description:
        print(f"Description: {green(default_description)}")
    else:
        print("Description (optional)")
    description = _ask_field("> ", str, default=default_description)

    project_id = existing["project_id"] if existing else str(uuid.uuid4())
    write_project_id(root, project_id)

    config = {
        "project_id": project_id,
        "name": name,
        "description": description,
    }
    return root, config
