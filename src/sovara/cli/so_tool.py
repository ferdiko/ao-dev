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
from typing import Any
from sovara.common.constants import HOST, PORT, PRIORS_SERVER_URL, PRIORS_SERVER_TIMEOUT

RUN_WAIT_TIMEOUT = 30  # Max seconds to wait for run_id from agent_runner
SOVARA_SERVER_URL = f"http://{HOST}:{PORT}"


def output_json(data: Any) -> None:
    """Print JSON to stdout and exit with appropriate code."""
    print(json.dumps(data, indent=2))
    if isinstance(data, dict) and data.get("status") == "error":
        sys.exit(1)
    sys.exit(0)


def format_timestamp(ts) -> str | None:
    """Format a timestamp to ISO 8601 without microseconds."""
    if ts is None:
        return None
    from datetime import datetime
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts)
        except ValueError:
            return ts
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


def _load_json_file(path: str) -> Any:
    """Load a JSON file from disk."""
    with open(path, "r") as f:
        return json.load(f)


def _build_restructure_execute_body(args) -> dict:
    """Build the execute request body from CLI arguments."""
    body = {}

    if args.proposal_file:
        proposal = _load_json_file(args.proposal_file)
        if not isinstance(proposal, dict):
            raise ValueError("--proposal-file must contain a JSON object")
        for key in ("task_id", "moves", "new_folders", "base_path", "snapshot"):
            if key in proposal:
                body[key] = proposal[key]

    if args.task_id:
        body["task_id"] = args.task_id

    if args.moves_file:
        moves = _load_json_file(args.moves_file)
        if not isinstance(moves, list):
            raise ValueError("--moves-file must contain a JSON array")
        body["moves"] = moves

    if args.base_path is not None:
        body["base_path"] = args.base_path

    if args.snapshot is not None:
        body["snapshot"] = args.snapshot

    if args.new_folder:
        body["new_folders"] = args.new_folder

    if not body:
        raise ValueError("Provide --task-id, --proposal-file, or a standalone execute body")

    return body


def _ensure_server_running() -> None:
    """Start the local FastAPI server on demand for CLI reads/writes."""
    from sovara.cli.so_server import _is_server_running, launch_daemon_server

    if _is_server_running():
        return

    launch_daemon_server()
    deadline = time.time() + 10.0
    while time.time() < deadline:
        if _is_server_running():
            return
        time.sleep(0.1)

    output_json({
        "status": "error",
        "error": "Sovara server did not become ready. Run `so-server start` and retry.",
    })


def _extract_http_error(resp) -> str:
    try:
        data = resp.json()
    except ValueError:
        text = resp.text.strip()
        return text or "Server error"

    if isinstance(data, dict):
        detail = data.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail
        error = data.get("error")
        if isinstance(error, str) and error.strip():
            return error

    return "Server error"


def _server_request(
    method: str,
    path: str,
    *,
    params: dict | None = None,
    data: dict | None = None,
    timeout: float = 30.0,
) -> dict:
    """Make a JSON request to the local Sovara server."""
    import httpx

    _ensure_server_running()

    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.request(
                method,
                f"{SOVARA_SERVER_URL}{path}",
                params=params,
                json=data,
            )
    except httpx.RequestError as exc:
        return {"status": "error", "error": f"Connection failed: {exc}"}

    if not response.is_success:
        return {
            "status": "error",
            "error": _extract_http_error(response),
            "code": response.status_code,
        }

    try:
        return response.json()
    except ValueError as exc:
        return {"status": "error", "error": f"Invalid JSON response: {exc}"}


def _fetch_all_runs() -> list[dict]:
    """Fetch the full run list via paginated UI endpoints."""
    first_page = _server_request("GET", "/ui/runs")
    if first_page.get("status") == "error":
        output_json(first_page)

    runs = list(first_page.get("runs", []))
    finished_offset = sum(1 for run in runs if run.get("status") != "running")
    has_more = first_page.get("has_more", False)

    while has_more:
        page = _server_request("GET", "/ui/runs/more", params={"offset": finished_offset})
        if page.get("status") == "error":
            output_json(page)
        next_runs = page.get("runs", [])
        runs.extend(next_runs)
        finished_offset += len(next_runs)
        has_more = page.get("has_more", False)

    return runs


def _spawn_rerun(prepared: dict, timeout: float | None = None) -> dict:
    """
    Spawn a rerun process for a run and block until completion.

    Consistent with record_command: stdout/stderr pass through to terminal.
    Returns result dict with status, run_id, exit_code, etc.
    """
    run_id = prepared["run_id"]
    cwd = prepared["cwd"]
    command = prepared["command"]
    environment = prepared["environment"]

    if not command:
        return {"status": "error", "error": f"Run not found or no command stored: {run_id}"}

    # Create temp file for run_id IPC
    run_file = os.path.join(tempfile.gettempdir(), f"sovara-run-{run_id}.json")

    def cleanup_run_file():
        try:
            if os.path.exists(run_file):
                os.unlink(run_file)
        except OSError:
            pass

    atexit.register(cleanup_run_file)

    # Set up environment: restore original env + set rerun run ID
    env = os.environ.copy()
    env.update(environment)
    env["SOVARA_RUN_ID"] = run_id  # Tell agent_runner to reuse this run
    env["SOVARA_RUN_FILE"] = run_file

    # Parse and execute the original command
    cmd_parts = shlex.split(command)

    process = subprocess.Popen(
        cmd_parts,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
    )

    # Wait for run_id from agent_runner (confirms handshake)
    run_data = wait_for_run_file(run_file, RUN_WAIT_TIMEOUT)

    # Clean up temp file
    cleanup_run_file()
    atexit.unregister(cleanup_run_file)

    if not run_data:
        return {
            "status": "error",
            "error": "Timeout waiting for run handshake",
            "pid": process.pid,
        }
    if run_data["run_id"] != run_id:
        return {
            "status": "error",
            "error": f"Run handshake mismatch: expected {run_id}, got {run_data['run_id']}",
            "pid": process.pid,
        }

    # Block until completion
    start_time = time.time()
    try:
        exit_code = process.wait(timeout=timeout)
        duration = time.time() - start_time
        return {
            "status": "completed" if exit_code == 0 else "failed",
            "run_id": run_id,
            "exit_code": exit_code,
            "duration_seconds": round(duration, 2),
        }
    except subprocess.TimeoutExpired:
        process.terminate()
        return {
            "status": "timeout",
            "run_id": run_id,
            "pid": process.pid,
        }



def wait_for_run_file(run_file: str, timeout: float) -> dict | None:
    """Poll for the run file written by agent_runner.

    Returns the parsed JSON data if successful, None on timeout.
    """
    start = time.time()
    while time.time() - start < timeout:
        if os.path.exists(run_file):
            try:
                with open(run_file, "r") as f:
                    data = json.load(f)
                    if "run_id" in data:
                        return data
            except (json.JSONDecodeError, IOError):
                pass  # File not fully written yet
        time.sleep(0.1)
    return None


def record_command(args) -> None:
    """Run so-record and block until completion, return result via JSON."""

    if not args.module and not os.path.isfile(args.script_path):
        output_json({"status": "error", "error": f"Script not found: {args.script_path}"})

    run_id = str(uuid.uuid4())[:8]
    run_file = os.path.join(tempfile.gettempdir(), f"sovara-run-{run_id}.json")

    def cleanup_run_file():
        try:
            if os.path.exists(run_file):
                os.unlink(run_file)
        except OSError:
            pass

    atexit.register(cleanup_run_file)

    cmd = [sys.executable, "-m", "sovara.cli.so_record"]
    if args.run_name:
        cmd.extend(["--run-name", args.run_name])
    if args.module:
        cmd.append("-m")
    cmd.append(args.script_path)
    cmd.extend(args.script_args)

    env = os.environ.copy()
    env["SOVARA_RUN_FILE"] = run_file

    process = subprocess.Popen(
        cmd,
        env=env,
        stdin=subprocess.DEVNULL,
    )

    run_data = wait_for_run_file(run_file, RUN_WAIT_TIMEOUT)

    # Clean up temp file now that we've read it
    cleanup_run_file()
    atexit.unregister(cleanup_run_file)

    if not run_data:
        output_json({
            "status": "error",
            "error": "Timeout waiting for run_id from agent runner",
            "pid": process.pid,
        })

    run_id = run_data["run_id"]

    start_time = time.time()
    try:
        exit_code = process.wait(timeout=args.timeout)
        duration = time.time() - start_time
        output_json({
            "status": "completed" if exit_code == 0 else "failed",
            "run_id": run_id,
            "exit_code": exit_code,
            "duration_seconds": round(duration, 2),
        })
    except subprocess.TimeoutExpired:
        process.terminate()
        output_json({
            "status": "timeout",
            "run_id": run_id,
            "pid": process.pid,
        })


def probe_command(args) -> None:
    """Query the state of a run via the REST API."""
    params = {}
    if args.node:
        params["node"] = args.node
    if args.nodes:
        params["nodes"] = args.nodes
    if args.preview:
        params["preview"] = True
    if args.show_input:
        params["input"] = True
    if args.show_output:
        params["output"] = True
    if args.key_regex:
        params["key_regex"] = args.key_regex

    result = _server_request("GET", f"/ui/run/{args.run_id}/probe", params=params)
    output_json(result)


def runs_command(args) -> None:
    """List runs via the REST API."""
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

    all_runs = _fetch_all_runs()
    total_count = len(all_runs)

    if args.status != "all":
        all_runs = [run for run in all_runs if run.get("status") == args.status]

    # Apply range first
    if end is not None:
        runs = all_runs[start:end]
    else:
        runs = all_runs[start:]

    # Apply regex filter on top of the range
    if args.regex:
        try:
            pattern = re.compile(args.regex)
        except re.error as e:
            output_json({"status": "error", "error": f"Invalid regex: {e}"})
        runs = [exp for exp in runs if pattern.search(exp["name"] or "")]

    # Format output
    result = []
    for exp in runs:
        result.append({
            "run_id": exp["run_id"],
            "name": exp["name"],
            "status": exp.get("status"),
            "timestamp": format_timestamp(exp.get("timestamp")),
            "custom_metrics": exp.get("custom_metrics", {}),
            "thumb_label": exp.get("thumb_label"),
            "version_date": exp["version_date"],
        })

    output_json({"runs": result, "total": total_count, "range": f"{start}:{end if end else ''}"})


def edit_and_rerun_command(args) -> None:
    """Edit a single key in a node's input or output and immediately rerun."""
    node_uuid = args.node_uuid

    # Determine field, key, and value from mutually exclusive args
    if args.input:
        field = "input"
        key, value = args.input
    else:
        field = "output"
        key, value = args.output

    prepared = _server_request(
        "POST",
        f"/ui/run/{args.run_id}/prepare-edit-rerun",
        data={
            "node_uuid": node_uuid,
            "field": field,
            "key": key,
            "value": _resolve_value(value),
            "run_name": args.run_name,
        },
    )
    if prepared.get("status") == "error":
        output_json(prepared)

    result = _spawn_rerun(prepared, timeout=args.timeout)
    result["node_uuid"] = node_uuid
    result["edited_field"] = field
    result["edited_key"] = key
    output_json(result)


def install_skill_command() -> None:
    """Install the sovara skill to a project's .claude/skills/sovara/ directory."""
    from sovara.common.config import _ask_field, _convert_to_valid_path

    # Ask for target path with tab-completion
    default_path = os.getcwd()
    target_root_str = _ask_field(
        f"Target project directory [{default_path}]\n> ",
        _convert_to_valid_path,
        default=default_path,
        error_message="Please enter a valid directory path.",
    )
    target_root = Path(target_root_str).resolve()
    target_dir = target_root / ".claude" / "skills" / "sovara"
    target_file = target_dir / "SKILL.md"

    # Find the source SKILL.md bundled inside the sovara package
    import sovara.assets
    skill_source = Path(sovara.assets.__file__).parent / "SKILL.md"

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
    print(f"\nAdd so-cli Bash permissions to Claude Code settings?")
    print(f"This allows Claude to run so-cli commands without asking for permission.")
    print(f"Target: {settings_file}")
    response = input("Add permissions? [Y/n]: ").strip().lower()

    if response in ("", "y", "yes"):
        _add_ao_permissions(settings_file)
        print("\033[32mPermissions added.\033[0m")
    else:
        print("Skipped adding permissions.")

    print("\nMake sure to re-open Claude Code for changes to take effect.")


def _add_ao_permissions(settings_file: Path) -> None:
    """Add so-cli Bash permissions to a Claude settings file."""
    ao_permissions = [
        "Bash(*sovara.cli.so_tool*)",
        "Bash(*so-cli*)",
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
# Priors commands
# ===========================================================


def _is_priors_server_running() -> bool:
    """Check if the priors server is already running."""
    import urllib.request
    import urllib.error

    try:
        req = urllib.request.Request(f"{PRIORS_SERVER_URL}/health", method="GET")
        with urllib.request.urlopen(req, timeout=2) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def priors_start_server_command(args) -> None:
    """Start the SovaraDB daemon."""
    # Check if already running
    if _is_priors_server_running():
        output_json({
            "status": "success",
            "message": "SovaraDB server is already running",
            "url": PRIORS_SERVER_URL,
        })

    # Run the server start command (it handles its own daemonization)
    cmd = ["uv", "run", "so-priors", "start"]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=PRIORS_SERVER_TIMEOUT)
        if result.returncode == 0:
            output_json({
                "status": "success",
                "message": "SovaraDB server started successfully",
                "url": PRIORS_SERVER_URL,
            })
        else:
            error_output = result.stderr or result.stdout or "Unknown error starting server"
            output_json({
                "status": "error",
                "error": error_output,
                "hint": "SovaraDB may not be installed. To install:\n"
                        "  - With uv: add the local so-priors checkout as an editable path dependency\n"
                        "    (for example: sovara-priorsdb = { path = \"../so-priors\", editable = true })\n"
                        "  - With pip: pip install -e ../so-priors",
            })
    except FileNotFoundError:
        output_json({
            "status": "error",
            "error": "uv command not found. Please install uv or ensure it's in PATH.",
        })
    except subprocess.TimeoutExpired:
        output_json({
            "status": "error",
            "error": f"Server start command timed out after {PRIORS_SERVER_TIMEOUT}s",
        })
    except Exception as e:
        output_json({
            "status": "error",
            "error": f"Failed to start priors server: {e}",
        })


def _priors_request(method: str, path: str, data: dict | None = None) -> dict:
    """Make an HTTP request to the priors server.

    Returns the parsed JSON response, or an error dict.
    """
    import urllib.request
    import urllib.error

    url = f"{PRIORS_SERVER_URL}{path}"

    if data is not None:
        body = json.dumps(data).encode("utf-8")
    else:
        body = None

    headers = {}
    if body:
        headers["Content-Type"] = "application/json"

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


def _parse_sse_stream(response) -> dict:
    """Read an SSE stream from *response* and return the result/error data.

    Handles ``waiting``, ``result``, and ``error`` events.  On ``waiting``,
    prints a message to stderr so the CLI user sees feedback.
    """
    current_event = None
    for raw_line in response:
        line = raw_line.decode("utf-8", errors="replace").rstrip("\n").rstrip("\r")

        if line.startswith("event: "):
            current_event = line[7:]
        elif line.startswith("data: "):
            data_str = line[6:]
            try:
                data = json.loads(data_str)
            except json.JSONDecodeError:
                data = {"raw": data_str}

            if current_event == "waiting":
                msg = data.get("message", "Waiting for lock...")
                print(f"[priors] {msg}", file=sys.stderr)
            elif current_event == "acquired":
                msg = data.get("message", "Acquired lock")
                print(f"[priors] {msg}", file=sys.stderr)
            elif current_event == "result":
                return data
            elif current_event == "error":
                code = data.get("code", 500)
                error_msg = data.get("error", "Unknown error")
                return {"status": "error", "error": error_msg, "code": code}

            current_event = None

    # Stream ended without result/error
    return {"status": "error", "error": "SSE stream ended unexpectedly"}


def _priors_request_sse(method: str, path: str, data: dict | None = None) -> dict:
    """Make an HTTP request to the priors server expecting an SSE stream.

    Returns the parsed result/error data dict.
    """
    import urllib.request
    import urllib.error

    url = f"{PRIORS_SERVER_URL}{path}"

    if data is not None:
        body = json.dumps(data).encode("utf-8")
    else:
        body = None

    headers = {"Accept": "text/event-stream"}
    if body:
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            content_type = response.headers.get("Content-Type", "")
            if "text/event-stream" in content_type:
                return _parse_sse_stream(response)
            # Fallback: plain JSON response
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


def priors_list_command(args) -> None:
    """List priors, optionally filtered by folder path."""
    endpoint = "/api/v1/priors"
    if args.path:
        from urllib.parse import urlencode

        endpoint += "?" + urlencode({"path": args.path})
    output_json(_priors_request("GET", endpoint))


def priors_get_command(args) -> None:
    """Get a specific prior by ID."""
    output_json(_priors_request("GET", f"/api/v1/priors/{args.prior_id}"))


def priors_create_command(args) -> None:
    """Create a new prior. Server performs LLM validation unless force=true."""
    data = {
        "name": args.name,
        "summary": args.summary,
        "content": args.content,
    }
    if args.path:
        data["path"] = args.path
    if args.creation_trace_id:
        data["creation_trace_id"] = args.creation_trace_id
    if args.trace_source:
        data["trace_source"] = args.trace_source

    endpoint = "/api/v1/priors"
    if args.force:
        endpoint += "?force=true"

    output_json(_priors_request_sse("POST", endpoint, data))


def priors_update_command(args) -> None:
    """Update an existing prior. Server performs LLM validation unless force=true."""
    data = {}
    if args.name:
        data["name"] = args.name
    if args.summary:
        data["summary"] = args.summary
    if args.content:
        data["content"] = args.content
    if args.path:
        data["path"] = args.path

    if not data:
        output_json({"status": "error", "error": "At least one field must be provided"})

    endpoint = f"/api/v1/priors/{args.prior_id}"
    if args.force:
        endpoint += "?force=true"

    output_json(_priors_request_sse("PUT", endpoint, data))


def priors_delete_command(args) -> None:
    """Delete a prior."""
    output_json(_priors_request_sse("DELETE", f"/api/v1/priors/{args.prior_id}"))


def priors_query_command(args) -> None:
    """Query all priors in a folder and return an injected context block."""
    data = {}
    if args.path:
        data["path"] = args.path
    output_json(_priors_request("POST", "/api/v1/query/priors", data))


def priors_retrieve_command(args) -> None:
    """Retrieve relevant priors with the LLM-backed retriever."""
    data = {"context": args.context}
    if args.path:
        data["base_path"] = args.path
    if args.model:
        data["model"] = args.model
    output_json(_priors_request("POST", "/api/v1/query/priors/retrieve", data))


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


def priors_migrate_command(args) -> None:
    """Migrate root-level priors into the default retrieval folder."""
    output_json(_priors_request("POST", "/api/v1/priors/migrate", {}))


def priors_restructure_propose_command(args) -> None:
    """Propose a prior folder restructure."""
    data = {"base_path": args.path or ""}
    if args.comments:
        data["comments"] = args.comments
    output_json(_priors_request("POST", "/api/v1/priors/restructure/propose", data))


def priors_restructure_execute_command(args) -> None:
    """Execute a proposed or client-specified prior restructure."""
    try:
        data = _build_restructure_execute_body(args)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        output_json({"status": "error", "error": str(exc)})
    output_json(_priors_request("POST", "/api/v1/priors/restructure/execute", data))


def priors_restructure_abort_command(args) -> None:
    """Abort a pending prior restructure proposal."""
    output_json(_priors_request("POST", "/api/v1/priors/restructure/abort", {"task_id": args.task_id}))


def priors_ls_command(args) -> None:
    """List folder contents at a path."""
    path = _normalize_folder_path(args.path or "")
    output_json(_priors_request("POST", "/api/v1/priors/folders/ls", {"path": path}))


def priors_mkdir_command(args) -> None:
    """Create an empty folder."""
    path = _normalize_folder_path(args.path)
    output_json(_priors_request("POST", "/api/v1/priors/folders/mkdir", {"path": path}))


def priors_mv_command(args) -> None:
    """Move/rename a folder, or move priors by ID."""
    if args.ids:
        # Prior mode: -i id1,id2 DST
        prior_ids = [i.strip() for i in args.ids.split(",")]
        if not args.paths:
            output_json({"status": "error", "error": "DST path is required when using -i"})
        dst = _normalize_folder_path(args.paths[0])
        result = _priors_request("POST", "/api/v1/priors/folders/mv", {
            "prior_ids": prior_ids,
            "dst": dst,
        })
    else:
        # Folder mode: SRC DST
        if not args.paths or len(args.paths) != 2:
            output_json({"status": "error", "error": "mv requires SRC and DST arguments (or use -i for prior IDs)"})
        src = _normalize_folder_path(args.paths[0])
        dst = _normalize_folder_path(args.paths[1])
        result = _priors_request("POST", "/api/v1/priors/folders/mv", {
            "src": src,
            "dst": dst,
        })
    output_json(result)


def priors_cp_command(args) -> None:
    """Copy a folder to a new destination."""
    src = _normalize_folder_path(args.src)
    dst = _normalize_folder_path(args.dst)
    result = _priors_request("POST", "/api/v1/priors/folders/cp", {
        "src": src,
        "dst": dst,
    })
    output_json(result)


def priors_rm_command(args) -> None:
    """Delete a prior by ID, or recursively delete a folder."""
    if args.recursive:
        # Folder mode: rm -r PATH
        path = _normalize_folder_path(args.target)
        result = _priors_request("POST", "/api/v1/priors/folders/rm", {"path": path})
    else:
        # Single prior delete by ID
        result = _priors_request_sse("DELETE", f"/api/v1/priors/{args.target}")
    output_json(result)


def create_parser() -> ArgumentParser:
    """Create the argument parser with subcommands."""
    parser = ArgumentParser(
        prog="so-cli",
        description="CLI for programmatic interaction with Sovara dataflow system. All output is JSON.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # record subcommand
    record = subparsers.add_parser(
        "record",
        help="Start recording a script execution",
        description="Spawn so-record as a background process and return run_id.",
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
        help="Query run state",
        description="Query metadata or specific nodes of a run.",
    )
    probe.add_argument("run_id", help="Run ID to probe")
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

    # runs subcommand
    runs = subparsers.add_parser(
        "runs",
        help="List runs from server",
        description="List runs with optional range. Range format: ':50' (first 50), '50:100' (50-99), '10:' (from 10 onwards).",
    )
    runs.add_argument(
        "--range",
        default=":50",
        help="Range of runs to return (default: ':50'). Format: 'start:end', ':end', 'start:'",
    )
    runs.add_argument(
        "--regex",
        help="Filter runs by name using regex pattern",
    )
    runs.add_argument(
        "--status",
        choices=["all", "running", "finished"],
        default="all",
        help="Filter runs by runtime status",
    )

    # edit-and-rerun subcommand
    edit_and_rerun = subparsers.add_parser(
        "edit-and-rerun",
        help="Edit a node and immediately rerun",
        description="Copy a run, edit a single key in a node's input or output, and rerun. "
                    "Keys use flattened dot-notation from probe output (e.g., messages.0.content). "
                    "Value can be a literal or a path to a file.",
    )
    edit_and_rerun.add_argument("run_id", help="Run ID containing the node")
    edit_and_rerun.add_argument("node_uuid", help="Node UUID to edit")
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
        help="Install the sovara skill to a project",
        description="Interactive setup: copies SKILL.md and adds Claude Code permissions.",
    )

    # priors subcommand with nested subcommands
    priors = subparsers.add_parser(
        "priors",
        help="Design priors commands",
        description="Manage priors for agent development.",
    )
    priors_subparsers = priors.add_subparsers(dest="priors_command", required=True)

    # priors start-server
    priors_subparsers.add_parser(
        "start-server",
        help="Start the priors server",
        description="Start the SovaraDB daemon.",
    )

    priors_list = priors_subparsers.add_parser(
        "list",
        help="List priors",
        description="List priors with their IDs, names, and summaries.",
    )
    priors_list.add_argument("--path", "-p", default=None, help="Folder path to filter by")

    priors_get = priors_subparsers.add_parser(
        "get",
        help="Get a prior",
        description="Get full details of a prior by its ID.",
    )
    priors_get.add_argument("prior_id", help="The prior ID to retrieve")

    priors_create = priors_subparsers.add_parser(
        "create",
        help="Create a prior",
        description="Create a new prior with name, summary, and content.",
    )
    priors_create.add_argument(
        "--name", "-n",
        required=True,
        help="Prior name (max 200 chars)",
    )
    priors_create.add_argument(
        "--summary", "-s",
        required=True,
        help="Brief summary (max 1000 chars)",
    )
    priors_create.add_argument(
        "--content", "-c",
        required=True,
        help="Full prior content in markdown",
    )
    priors_create.add_argument(
        "--path", "-p",
        default=None,
        help="Folder path (e.g. 'beaver/retriever/')",
    )
    priors_create.add_argument(
        "--creation-trace-id",
        default=None,
        help="Optional run ID that created this prior",
    )
    priors_create.add_argument(
        "--trace-source",
        default=None,
        help="Optional source label for the creating system",
    )
    priors_create.add_argument(
        "--force", "-f",
        action="store_true",
        help="Skip LLM validation and create the prior directly",
    )

    priors_update = priors_subparsers.add_parser(
        "update",
        help="Update a prior",
        description="Update an existing prior's name, summary, content, or path.",
    )
    priors_update.add_argument("prior_id", help="The prior ID to update")
    priors_update.add_argument("--name", "-n", help="New prior name")
    priors_update.add_argument("--summary", "-s", help="New summary")
    priors_update.add_argument("--content", "-c", help="New content")
    priors_update.add_argument("--path", "-p", help="New folder path")
    priors_update.add_argument(
        "--force", "-f",
        action="store_true",
        help="Skip LLM validation and update the prior directly",
    )

    priors_delete = priors_subparsers.add_parser(
        "delete",
        help="Delete a prior",
        description="Delete a prior by its ID.",
    )
    priors_delete.add_argument("prior_id", help="The prior ID to delete")

    priors_query = priors_subparsers.add_parser(
        "query",
        help="Query priors by folder path",
        description="Get priors from a folder and return them as injected context.",
    )
    priors_query.add_argument(
        "--path", "-p",
        default=None,
        help="Folder path to retrieve priors from (omit for all priors)",
    )

    priors_retrieve = priors_subparsers.add_parser(
        "retrieve",
        help="Retrieve relevant priors",
        description="Use the LLM-backed retriever to select relevant priors.",
    )
    priors_retrieve.add_argument("context", help="Context string used for retrieval")
    priors_retrieve.add_argument(
        "--path", "-p",
        default=None,
        help="Root folder path to search from",
    )
    priors_retrieve.add_argument(
        "--model",
        default=None,
        help="Optional retriever model override",
    )

    priors_migrate = priors_subparsers.add_parser(
        "migrate",
        help="Migrate root priors",
        description="Move root-level priors into the default retrieval folder.",
    )

    priors_restructure = priors_subparsers.add_parser(
        "restructure",
        help="Propose/execute/abort taxonomy changes",
        description="Manage prior taxonomy restructure proposals.",
    )
    restructure_subparsers = priors_restructure.add_subparsers(dest="restructure_command", required=True)

    restructure_propose = restructure_subparsers.add_parser(
        "propose",
        help="Propose a restructure",
        description="Analyze priors and propose a better folder taxonomy.",
    )
    restructure_propose.add_argument(
        "--path", "-p",
        default="",
        help="Root folder path to analyze (default: root)",
    )
    restructure_propose.add_argument(
        "--comments", "-c",
        default=None,
        help="Optional guidance for the restructurer",
    )

    restructure_execute = restructure_subparsers.add_parser(
        "execute",
        help="Execute a restructure",
        description="Execute a proposal by task ID, from a proposal file, or from a standalone execute body.",
    )
    restructure_execute.add_argument(
        "--task-id",
        default=None,
        help="Task ID from a prior propose step",
    )
    restructure_execute.add_argument(
        "--proposal-file",
        default=None,
        help="JSON file containing a propose response or execute request body",
    )
    restructure_execute.add_argument(
        "--moves-file",
        default=None,
        help="JSON file containing a moves array for an edited execute request",
    )
    restructure_execute.add_argument(
        "--base-path",
        default=None,
        help="Root folder path for standalone execution",
    )
    restructure_execute.add_argument(
        "--snapshot",
        default=None,
        help="State hash for standalone execution",
    )
    restructure_execute.add_argument(
        "--new-folder",
        action="append",
        default=None,
        help="New folder to create during execution; repeat as needed",
    )

    restructure_abort = restructure_subparsers.add_parser(
        "abort",
        help="Abort a restructure",
        description="Abort a pending restructure proposal and release its lock.",
    )
    restructure_abort.add_argument("task_id", help="Task ID from the propose step")

    priors_ls = priors_subparsers.add_parser(
        "ls",
        help="List folder contents",
        description="List immediate child folders and priors at a path.",
    )
    priors_ls.add_argument("path", nargs="?", default="", help="Folder path to list (default: root)")

    priors_mkdir = priors_subparsers.add_parser(
        "mkdir",
        help="Create an empty folder",
        description="Create an empty folder at the given path.",
    )
    priors_mkdir.add_argument("path", help="Folder path to create (e.g. 'beaver/new-folder/')")

    priors_mv = priors_subparsers.add_parser(
        "mv",
        help="Move/rename a folder or move priors by ID",
        description="Move a folder (mv SRC DST) or move priors by ID (mv -i id1,id2 DST).",
    )
    priors_mv.add_argument(
        "-i", "--ids",
        default=None,
        help="Comma-separated prior IDs to move (prior mode)",
    )
    priors_mv.add_argument("paths", nargs="*", help="SRC DST (folder mode) or DST (with -i)")

    priors_cp = priors_subparsers.add_parser(
        "cp",
        help="Copy a folder",
        description="Copy all priors under a folder to a new destination.",
    )
    priors_cp.add_argument("src", help="Source folder path")
    priors_cp.add_argument("dst", help="Destination folder path")

    priors_rm = priors_subparsers.add_parser(
        "rm",
        help="Delete a prior or folder",
        description="Delete a single prior by ID (rm TARGET) or a folder recursively (rm -r PATH).",
    )
    priors_rm.add_argument(
        "-r", "--recursive",
        action="store_true",
        help="Delete folder recursively",
    )
    priors_rm.add_argument("target", help="Prior ID or folder path (with -r)")

    return parser


def main():
    parser = create_parser()
    args = parser.parse_args()

    if args.command == "record":
        record_command(args)
    elif args.command == "probe":
        probe_command(args)
    elif args.command == "runs":
        runs_command(args)
    elif args.command == "edit-and-rerun":
        edit_and_rerun_command(args)
    elif args.command == "install-skill":
        install_skill_command()
    elif args.command == "priors":
        if args.priors_command == "start-server":
            priors_start_server_command(args)
        elif args.priors_command == "list":
            priors_list_command(args)
        elif args.priors_command == "get":
            priors_get_command(args)
        elif args.priors_command == "create":
            priors_create_command(args)
        elif args.priors_command == "update":
            priors_update_command(args)
        elif args.priors_command == "delete":
            priors_delete_command(args)
        elif args.priors_command == "query":
            priors_query_command(args)
        elif args.priors_command == "retrieve":
            priors_retrieve_command(args)
        elif args.priors_command == "migrate":
            priors_migrate_command(args)
        elif args.priors_command == "restructure":
            if args.restructure_command == "propose":
                priors_restructure_propose_command(args)
            elif args.restructure_command == "execute":
                priors_restructure_execute_command(args)
            elif args.restructure_command == "abort":
                priors_restructure_abort_command(args)
        elif args.priors_command == "ls":
            priors_ls_command(args)
        elif args.priors_command == "mkdir":
            priors_mkdir_command(args)
        elif args.priors_command == "mv":
            priors_mv_command(args)
        elif args.priors_command == "cp":
            priors_cp_command(args)
        elif args.priors_command == "rm":
            priors_rm_command(args)


if __name__ == "__main__":
    main()
