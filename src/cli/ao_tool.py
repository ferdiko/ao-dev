import atexit
import os
import sys
import json
import shlex
import shutil
import uuid
import time
import tempfile
import subprocess
from argparse import ArgumentParser, REMAINDER
from pathlib import Path
from ao.common.constants import PLAYBOOK_SERVER_URL, PLAYBOOK_SERVER_TIMEOUT
from ao.server.database_manager import DB

SESSION_WAIT_TIMEOUT = 30  # Max seconds to wait for session_id from agent_runner


def output_json(data: dict) -> None:
    """Print JSON to stdout and exit with appropriate code."""
    print(json.dumps(data, indent=2))
    sys.exit(0 if data.get("status") != "error" else 1)


def format_timestamp(ts) -> str | None:
    """Format a timestamp to ISO 8601 without microseconds."""
    if ts is None:
        return None
    from datetime import datetime
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts)
    return ts.strftime("%Y-%m-%d %H:%M:%S")


# ===========================================================
# Shared helpers for reusable logic
# ===========================================================


def _resolve_value(value: str) -> str:
    """Resolve a value argument: if it's a path to an existing file, read the file contents."""
    if os.path.isfile(value):
        with open(value, "r") as f:
            return f.read()
    return value


def _apply_edit(session_id: str, node_id: str, field: str, key: str, value: str) -> dict:
    """
    Apply an edit to a single key in a node's input or output.

    The key is a flattened dot-notation key (e.g., "messages.0.content")
    matching the keys from probe output. The value can be a literal string
    or a path to a file whose contents will be used.

    Returns dict with status info. Does NOT call output_json or exit.
    """
    from flatten_json import flatten as flatten_complete
    from ao.runner.monkey_patching.api_parser import merge_filtered_into_raw, json_str_to_api_obj

    # Get the node's current data
    if field == "input":
        row = DB.query_one_llm_call_input(session_id, node_id)
    else:
        row = DB.query_one_llm_call_output(session_id, node_id)

    if not row:
        return {"status": "error", "error": f"Node {node_id} not found in session {session_id}"}

    api_type = row["api_type"]

    # Parse the current stored data to get raw and to_show
    if field == "input":
        current_data = json.loads(row["input"])
        inner_data = json.loads(current_data.get("input", "{}"))
    else:
        inner_data = json.loads(row["output"])

    raw_dict = inner_data.get("raw", {})
    to_show = inner_data.get("to_show", {})

    # Flatten to_show completely to match probe output format
    flat_to_show = flatten_complete(to_show, ".") if isinstance(to_show, dict) else {}

    # Validate the key exists
    if key not in flat_to_show:
        return {"status": "error", "error": f"Key '{key}' not found. Available keys: {list(flat_to_show.keys())}"}

    # Resolve value (read file if path, otherwise use as-is)
    value = _resolve_value(value)

    # Parse value: try JSON first (handles numbers, booleans, null), fall back to string
    try:
        parsed_value = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        parsed_value = value

    # Update the single key
    flat_to_show[key] = parsed_value

    # Validate by merging into raw
    try:
        merge_filtered_into_raw(raw_dict, flat_to_show)
    except Exception as e:
        return {"status": "error", "error": f"Failed to merge edit: {e}"}

    # Build the new complete structure
    new_complete = {"raw": raw_dict, "to_show": flat_to_show}
    new_json_str = json.dumps(new_complete, sort_keys=True)

    # For output, validate it can be converted to API object
    if field == "output":
        try:
            json_str_to_api_obj(new_json_str, api_type)
        except Exception as e:
            return {"status": "error", "error": f"Validation failed: {e}"}

    # Apply the edit
    if field == "input":
        DB.set_input_overwrite(session_id, node_id, new_json_str)
    else:
        DB.set_output_overwrite(session_id, node_id, new_json_str)

    return {
        "status": "success",
        "session_id": session_id,
        "node_id": node_id,
        "field": field,
        "key": key,
    }


def _spawn_rerun(session_id: str, timeout: float | None = None) -> dict:
    """
    Spawn a rerun process for a session and block until completion.

    Consistent with record_command: stdout/stderr pass through to terminal.
    Returns result dict with status, session_id, exit_code, etc.
    """
    # Get the original command, cwd, and environment from DB
    cwd, command, environment = DB.get_exec_command(session_id)

    if not command:
        return {"status": "error", "error": f"Session not found or no command stored: {session_id}"}

    # Create temp file for session_id IPC
    run_id = str(uuid.uuid4())[:8]
    session_file = os.path.join(tempfile.gettempdir(), f"ao-session-{run_id}.json")

    def cleanup_session_file():
        try:
            if os.path.exists(session_file):
                os.unlink(session_file)
        except OSError:
            pass

    atexit.register(cleanup_session_file)

    # Set up environment: restore original env + set rerun session ID
    env = os.environ.copy()
    env.update(environment)
    env["AO_SESSION_ID"] = session_id  # Tell agent_runner to reuse this session
    env["AO_SESSION_FILE"] = session_file

    # Parse and execute the original command
    cmd_parts = shlex.split(command)

    process = subprocess.Popen(
        cmd_parts,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
    )

    # Wait for session_id from agent_runner (confirms handshake)
    session_data = wait_for_session_file(session_file, SESSION_WAIT_TIMEOUT)

    # Clean up temp file
    cleanup_session_file()
    atexit.unregister(cleanup_session_file)

    if not session_data:
        return {
            "status": "error",
            "error": "Timeout waiting for session handshake",
            "pid": process.pid,
        }

    # Block until completion
    start_time = time.time()
    try:
        exit_code = process.wait(timeout=timeout)
        duration = time.time() - start_time
        return {
            "status": "completed" if exit_code == 0 else "failed",
            "session_id": session_id,
            "exit_code": exit_code,
            "duration_seconds": round(duration, 2),
        }
    except subprocess.TimeoutExpired:
        process.terminate()
        return {
            "status": "timeout",
            "session_id": session_id,
            "pid": process.pid,
        }



def wait_for_session_file(session_file: str, timeout: float) -> dict | None:
    """Poll for session file to be written by agent_runner.

    Returns the parsed JSON data if successful, None on timeout.
    """
    start = time.time()
    while time.time() - start < timeout:
        if os.path.exists(session_file):
            try:
                with open(session_file, "r") as f:
                    data = json.load(f)
                    if "session_id" in data:
                        return data
            except (json.JSONDecodeError, IOError):
                pass  # File not fully written yet
        time.sleep(0.1)
    return None


def record_command(args) -> None:
    """Run ao-record and block until completion, return result via JSON."""

    if not args.module and not os.path.isfile(args.script_path):
        output_json({"status": "error", "error": f"Script not found: {args.script_path}"})

    run_id = str(uuid.uuid4())[:8]
    session_file = os.path.join(tempfile.gettempdir(), f"ao-session-{run_id}.json")

    def cleanup_session_file():
        try:
            if os.path.exists(session_file):
                os.unlink(session_file)
        except OSError:
            pass

    atexit.register(cleanup_session_file)

    cmd = [sys.executable, "-m", "ao.cli.ao_record"]
    if args.run_name:
        cmd.extend(["--run-name", args.run_name])
    if args.module:
        cmd.append("-m")
    cmd.append(args.script_path)
    cmd.extend(args.script_args)

    env = os.environ.copy()
    env["AO_SESSION_FILE"] = session_file

    process = subprocess.Popen(
        cmd,
        env=env,
        stdin=subprocess.DEVNULL,
    )

    session_data = wait_for_session_file(session_file, SESSION_WAIT_TIMEOUT)

    # Clean up temp file now that we've read it
    cleanup_session_file()
    atexit.unregister(cleanup_session_file)

    if not session_data:
        output_json({
            "status": "error",
            "error": "Timeout waiting for session_id from agent runner",
            "pid": process.pid,
        })

    session_id = session_data["session_id"]

    start_time = time.time()
    try:
        exit_code = process.wait(timeout=args.timeout)
        duration = time.time() - start_time
        output_json({
            "status": "completed" if exit_code == 0 else "failed",
            "session_id": session_id,
            "exit_code": exit_code,
            "duration_seconds": round(duration, 2),
        })
    except subprocess.TimeoutExpired:
        process.terminate()
        output_json({
            "status": "timeout",
            "session_id": session_id,
            "pid": process.pid,
        })


def _truncate_strings(obj, max_len: int = 20):
    """Recursively truncate all string values in a JSON-like structure."""
    if isinstance(obj, str):
        if len(obj) > max_len:
            return obj[:max_len] + "..."
        return obj
    elif isinstance(obj, dict):
        return {k: _truncate_strings(v, max_len) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_truncate_strings(item, max_len) for item in obj]
    else:
        return obj


def _filter_by_key_regex(obj, pattern: str):
    """
    Filter a JSON-like structure by regex pattern on flattened keys.

    Uses flatten_json to create keys like "content.0.hello.key" for nested structures,
    filters by regex match, then unflattens back to nested structure.
    """
    import re
    from flatten_json import flatten, unflatten_list

    if obj is None:
        return None

    try:
        regex = re.compile(pattern)
    except re.error as e:
        raise ValueError(f"Invalid regex pattern: {e}")

    # Flatten the dict with "." separator (lists become content.0.key)
    flattened = flatten(obj, ".")

    # Filter keys that match the regex
    filtered = {k: v for k, v in flattened.items() if regex.search(k)}

    # Unflatten back to nested structure
    return unflatten_list(filtered, ".")


def probe_command(args) -> None:
    """Query the state of a session - metadata or specific nodes."""
    session_id = args.session_id

    # Get experiment metadata
    experiment = DB.get_experiment_metadata(session_id)
    if not experiment:
        output_json({"status": "error", "error": f"Session not found: {session_id}"})

    # Parse graph topology from JSON
    graph_topology = json.loads(experiment["graph_topology"]) if experiment["graph_topology"] else {"nodes": [], "edges": []}
    edges = graph_topology.get("edges", [])

    # Build parent/child relationships from edges
    parent_ids = {}  # node_id -> list of parent node_ids
    child_ids = {}   # node_id -> list of child node_ids
    for edge in edges:
        src, tgt = edge["source"], edge["target"]
        parent_ids.setdefault(tgt, []).append(src)
        child_ids.setdefault(src, []).append(tgt)

    # Handle --node or --nodes: return detailed info for specific node(s)
    if args.node or args.nodes:
        node_ids = [args.node] if args.node else args.nodes.split(",")
        nodes_data = []
        for node_id in node_ids:
            llm_call = DB.get_llm_call_full(session_id, node_id.strip())
            if not llm_call:
                output_json({"status": "error", "error": f"Node not found: {node_id}"})

            # Parse input/output JSON, extracting to_show fields
            input_to_show = None
            output_to_show = None
            if llm_call["input"]:
                input_data = json.loads(llm_call["input"])
                # input_data has {input: "<json string>", attachments: [...], model: "..."}
                # Parse the nested input JSON to get to_show
                if input_data.get("input"):
                    inner_input = json.loads(input_data["input"])
                    input_to_show = inner_input.get("to_show")

            if llm_call["output"]:
                output_data = json.loads(llm_call["output"])
                # output_data has {raw: {...}, to_show: {...}}
                output_to_show = output_data.get("to_show")

            # Apply key regex filter if requested
            if args.key_regex:
                try:
                    input_to_show = _filter_by_key_regex(input_to_show, args.key_regex)
                    output_to_show = _filter_by_key_regex(output_to_show, args.key_regex)
                except ValueError as e:
                    output_json({"status": "error", "error": str(e)})

            # Apply preview truncation if requested
            if args.preview:
                input_to_show = _truncate_strings(input_to_show)
                output_to_show = _truncate_strings(output_to_show)

            # Flatten completely (including lists into key.0, key.1 notation)
            from flatten_json import flatten as flatten_complete
            if isinstance(input_to_show, dict):
                input_to_show = flatten_complete(input_to_show, ".")
            if isinstance(output_to_show, dict):
                output_to_show = flatten_complete(output_to_show, ".")

            # Determine which content to include based on --input/--output flags
            # If neither specified, include both; if one specified, include only that one
            show_input = not args.show_output or args.show_input
            show_output = not args.show_input or args.show_output

            # Split stack trace into list of lines for readability
            stack_trace = llm_call["stack_trace"]
            if stack_trace:
                stack_trace = [line.strip() for line in stack_trace.split("\n") if line.strip()]

            node_info = {
                "node_id": llm_call["node_id"],
                "session_id": session_id,
                "api_type": llm_call["api_type"],
                "label": llm_call["label"],
                "timestamp": format_timestamp(llm_call["timestamp"]),
                "parent_ids": parent_ids.get(node_id.strip(), []),
                "child_ids": child_ids.get(node_id.strip(), []),
                "has_input_overwrite": llm_call["input_overwrite"] is not None,
                "stack_trace": stack_trace,
            }

            if show_input:
                node_info["input"] = input_to_show
            if show_output:
                node_info["output"] = output_to_show

            nodes_data.append(node_info)

        if args.node:
            # Single node: return just the node object
            output_json(nodes_data[0])
        else:
            # Multiple nodes: return array
            output_json({"nodes": nodes_data})
        return

    # Default: full probe - metadata + graph summary
    output_json({
        "session_id": session_id,
        "name": experiment["name"],
        "status": "finished",  # TODO: track running status
        "timestamp": format_timestamp(experiment["timestamp"]),
        "result": experiment["success"] if experiment["success"] else None,
        "version_date": experiment["version_date"],
        "node_count": len(graph_topology.get("nodes", [])),
        "nodes": [
            {
                "node_id": n["id"],
                "label": n.get("label", ""),
                "parent_ids": parent_ids.get(n["id"], []),
                "child_ids": child_ids.get(n["id"], []),
            }
            for n in graph_topology.get("nodes", [])
        ],
        "edges": [{"source": e["source"], "target": e["target"]} for e in edges],
    })


def experiments_command(args) -> None:
    """List experiments from the database."""
    import re

    # Parse range (format: "start:end", ":end", "start:", or "start")
    range_str = args.range or ":50"

    if ":" in range_str:
        parts = range_str.split(":", 1)
        start = int(parts[0]) if parts[0] else 0
        end = int(parts[1]) if parts[1] else None
    else:
        start = int(range_str)
        end = start + 1  # Single item

    # Get all experiments sorted by timestamp (most recent first)
    all_experiments = DB.get_all_experiments_sorted()
    total_count = len(all_experiments)

    # Apply range first
    if end is not None:
        experiments = all_experiments[start:end]
    else:
        experiments = all_experiments[start:]

    # Apply regex filter on top of the range
    if args.regex:
        try:
            pattern = re.compile(args.regex)
        except re.error as e:
            output_json({"status": "error", "error": f"Invalid regex: {e}"})
        experiments = [exp for exp in experiments if pattern.search(exp["name"] or "")]

    # Format output
    result = []
    for exp in experiments:
        timestamp = exp["timestamp"]
        if hasattr(timestamp, "isoformat"):
            timestamp = timestamp.isoformat()

        result.append({
            "session_id": exp["session_id"],
            "name": exp["name"],
            "timestamp": format_timestamp(timestamp),
            "result": exp["success"],
            "version_date": exp["version_date"],
        })

    output_json({"experiments": result, "total": total_count, "range": f"{start}:{end if end else ''}"})



def _copy_experiment(session_id: str, run_name: str | None = None) -> str | dict:
    """
    Clones the experiment and llm-calls entries for the given session_id in the DB
    and writes them into new entries in the DB with a new session id we generate here.
    Returns the new session id, or an error dict if the session doesn't exist.

    Args:
        session_id: The session to copy
        run_name: Optional name for the new run. If None, defaults to "Edit of <original name>"
    """
    from datetime import datetime

    # Get the original experiment metadata
    experiment = DB.get_experiment_metadata(session_id)
    if not experiment:
        return {"status": "error", "error": f"Session not found: {session_id}"}

    # Get execution info (cwd, command, environment)
    cwd, command, environment = DB.get_exec_command(session_id)
    if not command:
        return {"status": "error", "error": f"No command stored for session: {session_id}"}

    # Generate new session ID
    new_session_id = str(uuid.uuid4())

    # Determine run name
    if run_name is None:
        run_name = f"Edit of {experiment['name']}"

    # Create new experiment with copied data but new session_id and timestamp
    DB.add_experiment(
        session_id=new_session_id,
        name=run_name,
        timestamp=datetime.now(),
        cwd=cwd,
        command=command,
        environment=environment,
        parent_session_id=new_session_id,  # Self-referential for new top-level run
        user_id=None,
        version_date=experiment["version_date"],
    )

    # Copy graph topology from original
    if experiment["graph_topology"]:
        graph = json.loads(experiment["graph_topology"])
        DB.update_graph_topology(new_session_id, graph)

    # Copy all LLM calls to new session
    DB.copy_llm_calls(session_id, new_session_id)

    return new_session_id


def edit_and_rerun_command(args) -> None:
    """Edit a single key in a node's input or output and immediately rerun."""
    session_id = args.session_id
    node_id = args.node_id

    # Determine field, key, and value from mutually exclusive args
    if args.input:
        field = "input"
        key, value = args.input
    else:
        field = "output"
        key, value = args.output

    # Always create a new run (copy experiment)
    result = _copy_experiment(session_id, args.run_name)
    if isinstance(result, dict):
        output_json(result)
    session_id = result

    # Step 1: Apply the edit
    edit_result = _apply_edit(session_id, node_id, field, key, value)
    if edit_result.get("status") == "error":
        output_json(edit_result)

    # Step 2: Spawn rerun and block until completion
    result = _spawn_rerun(session_id, timeout=args.timeout)
    result["node_id"] = node_id
    result["edited_field"] = field
    result["edited_key"] = key
    output_json(result)


def install_skill_command() -> None:
    """Install the ao skill to a project's .claude/skills/ao/ directory."""
    from ao.common.config import _ask_field, _convert_to_valid_path

    # Ask for target path with tab-completion
    default_path = os.getcwd()
    target_root_str = _ask_field(
        f"Target project directory [{default_path}]\n> ",
        _convert_to_valid_path,
        default=default_path,
        error_message="Please enter a valid directory path.",
    )
    target_root = Path(target_root_str).resolve()
    target_dir = target_root / ".claude" / "skills" / "ao"
    target_file = target_dir / "SKILL.md"

    # Find the source SKILL.md relative to this package
    # ao package is at ao-dev/ao/, SKILL.md is at ao-dev/SKILL.md
    import ao
    ao_package_dir = Path(ao.__file__).parent  # ao-dev/ao/
    skill_source = ao_package_dir.parent / "SKILL.md"  # Go up to repo root

    if not skill_source.exists():
        print(f"Error: SKILL.md not found at {skill_source}", file=sys.stderr)
        sys.exit(1)

    # Create target directory
    target_dir.mkdir(parents=True, exist_ok=True)

    # Copy the file
    shutil.copy2(skill_source, target_file)
    print(f"\033[32mSkill installed to {target_file}\033[0m")

    # Ask about adding Bash permissions
    settings_file = target_root / ".claude" / "settings.local.json"
    print(f"\nAdd ao-tool Bash permissions to Claude Code settings?")
    print(f"This allows Claude to run ao-tool commands without asking for permission.")
    print(f"Target: {settings_file}")
    response = input("Add permissions? [Y/n]: ").strip().lower()

    if response in ("", "y", "yes"):
        _add_ao_permissions(settings_file)
        print("\033[32mPermissions added.\033[0m")
    else:
        print("Skipped adding permissions.")

    print("\nMake sure to re-open Claude Code for changes to take effect.")


def _add_ao_permissions(settings_file: Path) -> None:
    """Add ao-tool Bash permissions to a Claude settings file."""
    ao_permissions = [
        "Bash(*ao.cli.ao_tool*)",
        "Bash(*ao-tool*)",
    ]

    # Load existing settings or create new
    if settings_file.exists():
        with open(settings_file, "r") as f:
            settings = json.load(f)
    else:
        settings = {}

    # Ensure permissions.allow exists
    if "permissions" not in settings:
        settings["permissions"] = {}
    if "allow" not in settings["permissions"]:
        settings["permissions"]["allow"] = []

    # Add new permissions (avoid duplicates)
    existing = set(settings["permissions"]["allow"])
    for perm in ao_permissions:
        if perm not in existing:
            settings["permissions"]["allow"].append(perm)

    # Create directory if needed and write file
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    with open(settings_file, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")


# ===========================================================
# Playbook commands
# ===========================================================


def _is_playbook_server_running() -> bool:
    """Check if the playbook server is already running."""
    import urllib.request
    import urllib.error

    try:
        req = urllib.request.Request(f"{PLAYBOOK_SERVER_URL}/health", method="GET")
        with urllib.request.urlopen(req, timeout=2) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def playbook_start_server_command(args) -> None:
    """Start the ao-playbook-server daemon."""
    # Check if already running
    if _is_playbook_server_running():
        output_json({
            "status": "success",
            "message": "Playbook server is already running",
            "url": PLAYBOOK_SERVER_URL,
        })

    # Run the server start command (it handles its own daemonization)
    cmd = ["uv", "run", "ao-playbook-server", "start"]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=PLAYBOOK_SERVER_TIMEOUT)
        if result.returncode == 0:
            output_json({
                "status": "success",
                "message": "Playbook server started successfully",
                "url": PLAYBOOK_SERVER_URL,
            })
        else:
            error_output = result.stderr or result.stdout or "Unknown error starting server"
            output_json({
                "status": "error",
                "error": error_output,
                "hint": "ao-playbook may not be installed. To install:\n"
                        "  - With uv: add ao-playbook = { path = \"../ao-playbook\", editable = true } to pyproject.toml\n"
                        "  - With pip: pip install -e ../ao-playbook",
            })
    except FileNotFoundError:
        output_json({
            "status": "error",
            "error": "uv command not found. Please install uv or ensure it's in PATH.",
        })
    except subprocess.TimeoutExpired:
        output_json({
            "status": "error",
            "error": f"Server start command timed out after {PLAYBOOK_SERVER_TIMEOUT}s",
        })
    except Exception as e:
        output_json({
            "status": "error",
            "error": f"Failed to start playbook server: {e}",
        })


def _playbook_request(method: str, path: str, data: dict | None = None) -> dict:
    """Make an HTTP request to the playbook server.

    Returns the parsed JSON response, or an error dict.
    Uses AO_API_KEY env var for authentication if set.
    """
    import urllib.request
    import urllib.error

    url = f"{PLAYBOOK_SERVER_URL}{path}"

    if data is not None:
        body = json.dumps(data).encode("utf-8")
    else:
        body = None

    headers = {}
    if body:
        headers["Content-Type"] = "application/json"

    # Add API key if available
    api_key = os.environ.get("AO_API_KEY")
    if api_key:
        headers["X-API-Key"] = api_key

    req = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else str(e)
        try:
            server_error = json.loads(error_body)
            if "detail" in server_error:
                return {"status": "error", "error": server_error["detail"]}
            if "error" in server_error:
                return {"status": "error", "error": server_error["error"]}
        except json.JSONDecodeError:
            pass
        return {"status": "error", "error": error_body}
    except urllib.error.URLError as e:
        return {"status": "error", "error": f"Connection failed: {e.reason}"}
    except json.JSONDecodeError as e:
        return {"status": "error", "error": f"Invalid JSON response: {e}"}


def playbook_lessons_list_command(args) -> None:
    """List all lessons, optionally filtered by folder path."""
    endpoint = "/api/v1/lessons"
    if args.path:
        from urllib.parse import urlencode
        endpoint += "?" + urlencode({"path": args.path})
    result = _playbook_request("GET", endpoint)
    if "status" in result and result["status"] == "error":
        output_json(result)
    output_json({"status": "success", "lessons": result})


def playbook_lessons_get_command(args) -> None:
    """Get a specific lesson by ID."""
    result = _playbook_request("GET", f"/api/v1/lessons/{args.lesson_id}")
    if "status" in result and result["status"] == "error":
        output_json(result)
    output_json({"status": "success", "lesson": result})


def playbook_lessons_create_command(args) -> None:
    """Create a new lesson. Server performs LLM validation unless force=true."""
    data = {
        "name": args.name,
        "summary": args.summary,
        "content": args.content,
    }
    if args.path:
        data["path"] = args.path

    # Use force query param to skip server-side validation
    endpoint = "/api/v1/lessons"
    if args.force:
        endpoint += "?force=true"

    result = _playbook_request("POST", endpoint, data)

    # Handle validation rejection
    if result.get("status") == "rejected":
        output_json({
            "status": "rejected",
            "reason": result.get("reason", "Validation failed"),
            "conflicting_lesson_ids": result.get("conflicting_lesson_ids", []),
            "hint": result.get("hint") or "Use --force to skip validation and create anyway",
        })

    if result.get("status") == "error":
        output_json(result)

    # Success: status is "created", lesson data is at top level
    if result.get("status") == "created":
        lesson = {
            "id": result.get("id"),
            "name": result.get("name"),
            "summary": result.get("summary"),
            "content": result.get("content"),
            "path": result.get("path"),
        }
        response = {"status": "success", "lesson": lesson}
        if "validation" in result:
            response["validation"] = result["validation"]
        output_json(response)

    # Fallback for unexpected response
    output_json({"status": "error", "error": f"Unexpected response: {result}"})


def playbook_lessons_update_command(args) -> None:
    """Update an existing lesson. Server performs LLM validation unless force=true."""
    data = {}
    if args.name:
        data["name"] = args.name
    if args.summary:
        data["summary"] = args.summary
    if args.content:
        data["content"] = args.content

    if not data:
        output_json({"status": "error", "error": "At least one of --name, --summary, or --content is required"})

    # Use force query param to skip server-side validation
    endpoint = f"/api/v1/lessons/{args.lesson_id}"
    if args.force:
        endpoint += "?force=true"

    result = _playbook_request("PUT", endpoint, data)

    # Handle validation rejection
    if result.get("status") == "rejected":
        output_json({
            "status": "rejected",
            "reason": result.get("reason", "Validation failed"),
            "conflicting_lesson_ids": result.get("conflicting_lesson_ids", []),
            "hint": result.get("hint") or "Use --force to skip validation and update anyway",
        })

    if result.get("status") == "error":
        output_json(result)

    # Success: status is "updated", lesson data is at top level
    if result.get("status") == "updated":
        lesson = {
            "id": result.get("id"),
            "name": result.get("name"),
            "summary": result.get("summary"),
            "content": result.get("content"),
            "path": result.get("path"),
        }
        response = {"status": "success", "lesson": lesson}
        if "validation" in result:
            response["validation"] = result["validation"]
        output_json(response)

    # Fallback for unexpected response
    output_json({"status": "error", "error": f"Unexpected response: {result}"})


def playbook_lessons_delete_command(args) -> None:
    """Delete a lesson."""
    result = _playbook_request("DELETE", f"/api/v1/lessons/{args.lesson_id}")
    if "status" in result and result["status"] == "error":
        output_json(result)
    output_json({"status": "success", "deleted": args.lesson_id})


def playbook_lessons_query_command(args) -> None:
    """Query lessons by folder path."""
    data = {}
    if args.path:
        data["path"] = args.path
    result = _playbook_request("POST", "/api/v1/query/lessons", data)
    if "status" in result and result["status"] == "error":
        output_json(result)
    output_json({
        "status": "success",
        "lessons": result.get("lessons", []),
        "injected_context": result.get("injected_context", ""),
    })


def _normalize_folder_path(path: str) -> str:
    """Normalize a folder path: append '/' if non-empty and missing trailing slash.

    Validates path safety: rejects '..', leading '/', double '//', and '.folder' segments.
    """
    if not path:
        return path
    # Reject unsafe patterns
    if ".." in path:
        output_json({"status": "error", "error": "Path must not contain '..'"})
    if path.startswith("/"):
        output_json({"status": "error", "error": "Path must not start with '/'"})
    if "//" in path:
        output_json({"status": "error", "error": "Path must not contain '//'"})
    # Reject segments ending with '.' (e.g. '.hidden/' or 'some.folder/')
    for segment in path.rstrip("/").split("/"):
        if segment.startswith("."):
            output_json({"status": "error", "error": f"Path segment '{segment}' must not start with '.'"})
    if not path.endswith("/"):
        return path + "/"
    return path


def playbook_lessons_ls_command(args) -> None:
    """List folder contents at a path."""
    path = _normalize_folder_path(args.path or "")
    result = _playbook_request("POST", "/api/v1/lessons/folders/ls", {"path": path})
    if result.get("status") == "error":
        output_json(result)
    output_json({
        "status": "success",
        "path": result.get("path", path),
        "folders": result.get("folders", []),
        "lessons": result.get("lessons", []),
        "lesson_count": result.get("lesson_count", 0),
    })


def playbook_lessons_mkdir_command(args) -> None:
    """Create an empty folder."""
    path = _normalize_folder_path(args.path)
    result = _playbook_request("POST", "/api/v1/lessons/folders/mkdir", {"path": path})
    if result.get("status") == "error":
        output_json(result)
    output_json({"status": "success", "path": result.get("path", path)})


def playbook_lessons_mv_command(args) -> None:
    """Move/rename a folder, or move lessons by ID."""
    if args.ids:
        # Lesson mode: -i id1,id2 DST
        lesson_ids = [i.strip() for i in args.ids.split(",")]
        if not args.paths:
            output_json({"status": "error", "error": "DST path is required when using -i"})
        dst = _normalize_folder_path(args.paths[0])
        result = _playbook_request("POST", "/api/v1/lessons/folders/mv", {
            "lesson_ids": lesson_ids,
            "dst": dst,
        })
    else:
        # Folder mode: SRC DST
        if not args.paths or len(args.paths) != 2:
            output_json({"status": "error", "error": "mv requires SRC and DST arguments (or use -i for lesson IDs)"})
        src = _normalize_folder_path(args.paths[0])
        dst = _normalize_folder_path(args.paths[1])
        result = _playbook_request("POST", "/api/v1/lessons/folders/mv", {
            "src": src,
            "dst": dst,
        })
    if result.get("status") == "error":
        output_json(result)
    output_json(result)


def playbook_lessons_cp_command(args) -> None:
    """Copy a folder to a new destination."""
    src = _normalize_folder_path(args.src)
    dst = _normalize_folder_path(args.dst)
    result = _playbook_request("POST", "/api/v1/lessons/folders/cp", {
        "src": src,
        "dst": dst,
    })
    if result.get("status") == "error":
        output_json(result)
    output_json(result)


def playbook_lessons_rm_command(args) -> None:
    """Delete a lesson by ID, or recursively delete a folder."""
    if args.recursive:
        # Folder mode: rm -r PATH
        path = _normalize_folder_path(args.target)
        result = _playbook_request("POST", "/api/v1/lessons/folders/rm", {"path": path})
    else:
        # Single lesson delete by ID
        result = _playbook_request("DELETE", f"/api/v1/lessons/{args.target}")
    if result.get("status") == "error":
        output_json(result)
    output_json(result)


def create_parser() -> ArgumentParser:
    """Create the argument parser with subcommands."""
    parser = ArgumentParser(
        prog="ao-tool",
        description="CLI for programmatic interaction with AO dataflow system. All output is JSON.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # record subcommand
    record = subparsers.add_parser(
        "record",
        help="Start recording a script execution",
        description="Spawn ao-record as a background process and return session_id.",
    )
    record.add_argument(
        "-m", "--module",
        action="store_true",
        help="Run script_path as a Python module (like python -m)",
    )
    record.add_argument("--run-name", help="Human-readable name for this run")
    record.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Timeout in seconds (terminates script if exceeded)",
    )
    # Positional args must come after options to avoid REMAINDER capturing them
    record.add_argument("script_path", help="Script to execute (or module name with -m)")
    record.add_argument("script_args", nargs=REMAINDER, help="Arguments to pass to the script")

    # probe subcommand
    probe = subparsers.add_parser(
        "probe",
        help="Query session state",
        description="Query metadata or specific nodes of a session.",
    )
    probe.add_argument("session_id", help="Session ID to probe")
    probe.add_argument(
        "--node",
        help="Return detailed info for a single node",
    )
    probe.add_argument(
        "--nodes",
        help="Return detailed info for multiple nodes (comma-separated IDs)",
    )
    probe.add_argument(
        "--preview",
        action="store_true",
        help="Truncate string values to 20 characters for a compact overview",
    )
    probe.add_argument(
        "--input",
        dest="show_input",
        action="store_true",
        help="Only show input content (omit output)",
    )
    probe.add_argument(
        "--output",
        dest="show_output",
        action="store_true",
        help="Only show output content (omit input)",
    )
    probe.add_argument(
        "--key-regex",
        help="Filter keys using regex pattern on flattened keys (e.g., 'messages.*content'). Lists use index notation: content.0.hello",
    )

    # experiments subcommand
    experiments = subparsers.add_parser(
        "experiments",
        help="List experiments from database",
        description="List experiments with optional range. Range format: ':50' (first 50), '50:100' (50-99), '10:' (from 10 onwards).",
    )
    experiments.add_argument(
        "--range",
        default=":50",
        help="Range of experiments to return (default: ':50'). Format: 'start:end', ':end', 'start:'",
    )
    experiments.add_argument(
        "--regex",
        help="Filter experiments by name using regex pattern",
    )

    # edit-and-rerun subcommand
    edit_and_rerun = subparsers.add_parser(
        "edit-and-rerun",
        help="Edit a node and immediately rerun",
        description="Copy a session, edit a single key in a node's input or output, and rerun. "
                    "Keys use flattened dot-notation from probe output (e.g., messages.0.content). "
                    "Value can be a literal or a path to a file.",
    )
    edit_and_rerun.add_argument("session_id", help="Session ID containing the node")
    edit_and_rerun.add_argument("node_id", help="Node ID to edit")
    edit_and_rerun_group = edit_and_rerun.add_mutually_exclusive_group(required=True)
    edit_and_rerun_group.add_argument(
        "--input",
        nargs=2,
        metavar=("KEY", "VALUE"),
        help="Edit an input key: --input <flat_key> <value_or_file_path>",
    )
    edit_and_rerun_group.add_argument(
        "--output",
        nargs=2,
        metavar=("KEY", "VALUE"),
        help="Edit an output key: --output <flat_key> <value_or_file_path>",
    )
    edit_and_rerun.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Timeout in seconds (terminates script if exceeded)",
    )
    edit_and_rerun.add_argument(
        "--run-name",
        help="Name for the new run. Defaults to 'Edit of <original name>'",
    )

    # install-skill subcommand
    subparsers.add_parser(
        "install-skill",
        help="Install the ao skill to a project",
        description="Interactive setup: copies SKILL.md and adds Claude Code permissions.",
    )

    # playbook subcommand with nested subcommands
    playbook = subparsers.add_parser(
        "playbook",
        help="Design playbook commands",
        description="Manage lessons for agent development.",
    )
    playbook_subparsers = playbook.add_subparsers(dest="playbook_command", required=True)

    # playbook start-server
    playbook_subparsers.add_parser(
        "start-server",
        help="Start the playbook server",
        description="Start the ao-playbook-server daemon.",
    )

    # playbook lessons (nested subcommand)
    lessons = playbook_subparsers.add_parser(
        "lessons",
        help="Manage lessons",
        description="CRUD operations for user lessons.",
    )
    lessons_subparsers = lessons.add_subparsers(dest="lessons_command", required=True)

    # playbook lessons list
    lessons_list = lessons_subparsers.add_parser(
        "list",
        help="List all lessons",
        description="List all lessons with their IDs, names, and summaries.",
    )
    lessons_list.add_argument("--path", "-p", default=None, help="Folder path to filter by")

    # playbook lessons get
    lessons_get = lessons_subparsers.add_parser(
        "get",
        help="Get a specific lesson",
        description="Get full details of a lesson by its ID.",
    )
    lessons_get.add_argument("lesson_id", help="The lesson ID to retrieve")

    # playbook lessons create
    lessons_create = lessons_subparsers.add_parser(
        "create",
        help="Create a new lesson",
        description="Create a new lesson with name, summary, and content.",
    )
    lessons_create.add_argument(
        "--name", "-n",
        required=True,
        help="Lesson name (max 200 chars)",
    )
    lessons_create.add_argument(
        "--summary", "-s",
        required=True,
        help="Brief summary (max 1000 chars)",
    )
    lessons_create.add_argument(
        "--content", "-c",
        required=True,
        help="Full lesson content in markdown",
    )
    lessons_create.add_argument(
        "--path", "-p",
        default=None,
        help="Folder path (e.g. 'beaver/retriever/')",
    )
    lessons_create.add_argument(
        "--force", "-f",
        action="store_true",
        help="Skip LLM validation and create the lesson directly",
    )

    # playbook lessons update
    lessons_update = lessons_subparsers.add_parser(
        "update",
        help="Update a lesson",
        description="Update an existing lesson's name, summary, or content.",
    )
    lessons_update.add_argument("lesson_id", help="The lesson ID to update")
    lessons_update.add_argument("--name", "-n", help="New lesson name")
    lessons_update.add_argument("--summary", "-s", help="New summary")
    lessons_update.add_argument("--content", "-c", help="New content")
    lessons_update.add_argument(
        "--force", "-f",
        action="store_true",
        help="Skip LLM validation and update the lesson directly",
    )

    # playbook lessons delete
    lessons_delete = lessons_subparsers.add_parser(
        "delete",
        help="Delete a lesson",
        description="Delete a lesson by its ID.",
    )
    lessons_delete.add_argument("lesson_id", help="The lesson ID to delete")

    # playbook lessons query
    lessons_query = lessons_subparsers.add_parser(
        "query",
        help="Query lessons by folder path",
        description="Get lessons from a folder and return them as injected context.",
    )
    lessons_query.add_argument(
        "--path", "-p",
        default=None,
        help="Folder path to retrieve lessons from (omit for all lessons)",
    )

    # playbook lessons ls
    lessons_ls = lessons_subparsers.add_parser(
        "ls",
        help="List folder contents",
        description="List immediate child folders and lessons at a path.",
    )
    lessons_ls.add_argument("path", nargs="?", default="", help="Folder path to list (default: root)")

    # playbook lessons mkdir
    lessons_mkdir = lessons_subparsers.add_parser(
        "mkdir",
        help="Create an empty folder",
        description="Create an empty folder at the given path.",
    )
    lessons_mkdir.add_argument("path", help="Folder path to create (e.g. 'beaver/new-folder/')")

    # playbook lessons mv
    lessons_mv = lessons_subparsers.add_parser(
        "mv",
        help="Move/rename a folder or move lessons by ID",
        description="Move a folder (mv SRC DST) or move lessons by ID (mv -i id1,id2 DST).",
    )
    lessons_mv.add_argument(
        "-i", "--ids",
        default=None,
        help="Comma-separated lesson IDs to move (lesson mode)",
    )
    lessons_mv.add_argument("paths", nargs="*", help="SRC DST (folder mode) or DST (with -i)")

    # playbook lessons cp
    lessons_cp = lessons_subparsers.add_parser(
        "cp",
        help="Copy a folder",
        description="Copy all lessons under a folder to a new destination.",
    )
    lessons_cp.add_argument("src", help="Source folder path")
    lessons_cp.add_argument("dst", help="Destination folder path")

    # playbook lessons rm
    lessons_rm = lessons_subparsers.add_parser(
        "rm",
        help="Delete a lesson or folder",
        description="Delete a single lesson by ID (rm TARGET) or a folder recursively (rm -r PATH).",
    )
    lessons_rm.add_argument(
        "-r", "--recursive",
        action="store_true",
        help="Delete folder recursively",
    )
    lessons_rm.add_argument("target", help="Lesson ID or folder path (with -r)")

    return parser


def main():
    parser = create_parser()
    args = parser.parse_args()

    if args.command == "record":
        record_command(args)
    elif args.command == "probe":
        probe_command(args)
    elif args.command == "experiments":
        experiments_command(args)
    elif args.command == "edit-and-rerun":
        edit_and_rerun_command(args)
    elif args.command == "install-skill":
        install_skill_command()
    elif args.command == "playbook":
        if args.playbook_command == "start-server":
            playbook_start_server_command(args)
        elif args.playbook_command == "lessons":
            if args.lessons_command == "list":
                playbook_lessons_list_command(args)
            elif args.lessons_command == "get":
                playbook_lessons_get_command(args)
            elif args.lessons_command == "create":
                playbook_lessons_create_command(args)
            elif args.lessons_command == "update":
                playbook_lessons_update_command(args)
            elif args.lessons_command == "delete":
                playbook_lessons_delete_command(args)
            elif args.lessons_command == "query":
                playbook_lessons_query_command(args)
            elif args.lessons_command == "ls":
                playbook_lessons_ls_command(args)
            elif args.lessons_command == "mkdir":
                playbook_lessons_mkdir_command(args)
            elif args.lessons_command == "mv":
                playbook_lessons_mv_command(args)
            elif args.lessons_command == "cp":
                playbook_lessons_cp_command(args)
            elif args.lessons_command == "rm":
                playbook_lessons_rm_command(args)


if __name__ == "__main__":
    main()
