from __future__ import annotations

import argparse
import json
from pathlib import Path

from sovara.common.constants import HOST, PORT
from sovara.common.project import read_project_id, write_project_id
from sovara.common.user import read_user_id
from sovara.common.utils import http_post, set_server_url
from sovara.runner.agent_runner import ensure_server_running
from sovara.server.database_manager import DB

try:
    from .prettify_fixture import (
        PROJECT_DESCRIPTION,
        PROJECT_ID,
        PROJECT_NAME,
        PROJECT_ROOT,
        build_prettify_fixture,
    )
except ImportError:
    from prettify_fixture import (
        PROJECT_DESCRIPTION,
        PROJECT_ID,
        PROJECT_NAME,
        PROJECT_ROOT,
        build_prettify_fixture,
    )


SERVER_URL = f"http://{HOST}:{PORT}"
DEFAULT_RUN_NAME = "UI Prettify Fixture"


def _user_metadata() -> dict[str, str]:
    user_id = read_user_id()
    if not user_id:
        return {}

    row = DB.get_user(user_id)
    if not row:
        return {}

    return {
        "user_id": user_id,
        "user_full_name": row["full_name"] or "",
        "user_email": row["email"] or "",
    }


def _ensure_project_metadata(user: dict[str, str]) -> str:
    project_id_path = PROJECT_ROOT / ".sovara" / ".project_id"
    if not project_id_path.exists():
        write_project_id(str(PROJECT_ROOT), PROJECT_ID)

    project_id = read_project_id(str(PROJECT_ROOT))
    DB.upsert_project(project_id, PROJECT_NAME, PROJECT_DESCRIPTION)

    user_id = user.get("user_id")
    if user_id:
        DB.upsert_project_location(user_id, project_id, str(PROJECT_ROOT))

    return project_id


def _node_payload(node: dict) -> dict:
    return {
        "id": node["id"],
        "label": node["label"],
        "input": json.dumps(node["input"], indent=2, ensure_ascii=False),
        "output": json.dumps(node["output"], indent=2, ensure_ascii=False),
        "border_color": node["border_color"],
        "stack_trace": "Synthetic prettify fixture",
        "model": node["model"],
        "attachments": [],
    }


def inject_fixture_run(run_name: str = DEFAULT_RUN_NAME) -> str:
    fixture = build_prettify_fixture()
    user = _user_metadata()
    project_id = _ensure_project_metadata(user)

    ensure_server_running()
    set_server_url(SERVER_URL)

    register_payload = {
        "cwd": str(PROJECT_ROOT),
        "command": f"uv run python {Path(__file__).name}",
        "environment": {
            "SOVARA_SYNTHETIC_RUN": "1",
            "SOVARA_DEBUG_EXAMPLE": "prettify_fixture",
        },
        "name": run_name,
        "project_id": project_id,
        "project_name": PROJECT_NAME,
        "project_description": PROJECT_DESCRIPTION,
        "project_root": str(PROJECT_ROOT),
        **user,
    }

    session_id = http_post("/runner/register", register_payload)["session_id"]
    try:
        for node in fixture["nodes"]:
            http_post(
                "/runner/add-node",
                {
                    "session_id": session_id,
                    "node": _node_payload(node),
                    "incoming_edges": node.get("incoming_edges", []),
                },
            )
    finally:
        http_post("/runner/deregister", {"session_id": session_id}, timeout=0.5)

    return session_id


def _dry_run_summary() -> dict:
    fixture = build_prettify_fixture()
    return {
        "name": fixture["name"],
        "node_labels": [node["label"] for node in fixture["nodes"]],
        "node_count": len(fixture["nodes"]),
        "payload_files": sorted(path.name for path in (PROJECT_ROOT / "payloads").iterdir()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Inject a synthetic prettify fixture run into the local Sovara server.")
    parser.add_argument("--dry-run", action="store_true", help="Print a summary without contacting the server.")
    parser.add_argument("--run-name", default=DEFAULT_RUN_NAME, help="Override the synthetic run name.")
    args = parser.parse_args()

    if args.dry_run:
        print(json.dumps(_dry_run_summary(), indent=2))
        return

    session_id = inject_fixture_run(run_name=args.run_name)
    print(f"Injected synthetic run: {session_id}")


if __name__ == "__main__":
    main()
