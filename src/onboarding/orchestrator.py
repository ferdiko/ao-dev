"""
Onboarding agent orchestrator.

Run via `ao-tool onboard <repo-path>`, which spawns this module under
ao-record so the agent trace is captured in the ao-dev graph.

Uses the Claude Agent SDK to run an orchestrator agent that explores a
repository, validates its understanding with the human, and dispatches
worker sub-agents to process dataset samples and create lessons.
"""

import asyncio
import json
import os
import sys
import uuid
from datetime import datetime
from argparse import ArgumentParser
from pathlib import Path

def _sessions_root() -> Path:
    """Root directory for all onboarding session folders."""
    from ao.common.constants import AO_CACHE
    d = Path(AO_CACHE) / "onboard_sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _session_dir(session_id: str) -> Path:
    """Per-session folder: AO_CACHE/onboard_sessions/<session_id>/."""
    d = _sessions_root() / session_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save_session(run_id: str, args, claude_session_id: str | None = None) -> None:
    """Write a read-only session.json inside the session folder."""
    from datetime import datetime, timezone
    path = _session_dir(run_id) / "session.json"
    data = {
        "run_id": run_id,
        "claude_session_id": claude_session_id,
        "repo_path": str(Path(args.repo_path).resolve()),
        "max_parallel": args.max_parallel,
        "model": args.model,
        "instructions": args.instructions,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(data, indent=2))


def _load_session(identifier: str) -> dict | None:
    """Load session metadata by run_id (folder name) or claude_session_id."""
    # Try direct folder match first (don't create dir)
    path = _sessions_root() / identifier / "session.json"
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    # Search by claude_session_id
    for f in _sessions_root().glob("*/session.json"):
        try:
            data = json.loads(f.read_text())
            if data.get("claude_session_id") == identifier:
                return data
        except (json.JSONDecodeError, OSError):
            continue
    return None


def _find_last_session() -> dict | None:
    """Find the session with the most recent updated_at timestamp."""
    best, best_ts = None, ""
    for f in _sessions_root().glob("*/session.json"):
        try:
            data = json.loads(f.read_text())
            ts = data.get("updated_at", "")
            if ts > best_ts:
                best, best_ts = data, ts
        except (json.JSONDecodeError, OSError):
            continue
    return best


def _load_skill_md() -> str:
    """Load the ao SKILL.md for injection into the worker prompt."""
    import ao

    skill_path = Path(ao.__file__).parent.parent / "SKILL.md"
    if skill_path.exists():
        return skill_path.read_text()
    return ""


def _truncate(text: str, limit: int = 200) -> str:
    """Truncate text for display."""
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


# ANSI terminal formatting
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RED = "\033[31m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"
_RESET = "\033[0m"

# Color palette for workers — assigned dynamically as workers appear
_WORKER_COLORS = [
    "\033[34m",   # blue
    "\033[35m",   # magenta
    "\033[36m",   # cyan
    "\033[33m",   # yellow
    "\033[91m",   # bright red
    "\033[92m",   # bright green
    "\033[94m",   # bright blue
    "\033[95m",   # bright magenta
]


def _tool_detail_from_dict(tool_name: str, tool_input: dict) -> str:
    """Extract a compact detail string from tool name + input dict."""
    if tool_name == "Bash":
        return _truncate(tool_input.get("command", ""), 300)
    if tool_name == "Task":
        return tool_input.get("description", "")
    if tool_name in ("Read", "Write", "Edit"):
        return tool_input.get("file_path", "?")
    if tool_name in ("Glob", "Grep"):
        return tool_input.get("pattern", "")
    return ""


def _tool_detail(block) -> str:
    """Extract the most relevant detail from an SDK tool use block."""
    return _tool_detail_from_dict(block.name, block.input)


def _print_message(message) -> None:
    """Print a message from the SDK with clear formatting."""
    from claude_agent_sdk.types import (
        AssistantMessage,
        ResultMessage,
        SystemMessage,
        UserMessage,
    )

    if isinstance(message, AssistantMessage):
        # When workers are active, their tool calls are already logged via
        # _worker_log_hook + _monitor_progress (with W{n} prefix).  Only print
        # orchestrator-level messages here to avoid duplicates.
        is_worker_msg = _active_worker_num() is not None

        for block in message.content:
            if hasattr(block, "text"):
                if is_worker_msg:
                    continue  # Worker text — shown via log monitor
                lines = block.text.split("\n")
                bordered = "\n".join(f"  {_DIM}{_CYAN}│{_RESET} {l}" for l in lines)
                print(f"\n{bordered}", flush=True)
            elif hasattr(block, "name"):
                # Always stash Task metadata (needed by _on_worker_start)
                if block.name == "Task":
                    desc = block.input.get("description", "")
                    if desc:
                        _worker_state["task_descs"][block.id] = desc
                    agent_type = block.input.get("subagent_type", "")
                    if agent_type:
                        _worker_state.setdefault("_task_types", {})[block.id] = agent_type
                if is_worker_msg:
                    continue  # Worker tool use — shown via log monitor
                detail = _tool_detail(block)
                print(f"\n  {_BOLD}{block.name}{_RESET}  {detail}", flush=True)

    elif isinstance(message, UserMessage):
        # Tool results — dim with └ connector, color-coded
        # Skip worker tool results (already shown via log monitor)
        if _active_worker_num() is not None:
            pass
        elif isinstance(message.content, list):
            for block in message.content:
                if hasattr(block, "tool_use_id") and block.content:
                    is_err = getattr(block, "is_error", False)
                    color = _RED if is_err else _GREEN
                    text = _truncate(str(block.content))
                    print(f"  {_DIM}└ {color}{text}{_RESET}", flush=True)

    elif isinstance(message, ResultMessage):
        cost = f"${message.total_cost_usd:.2f}" if message.total_cost_usd else "?"
        print(
            f"\n{_DIM}{'─' * 40}\n"
            f"  {message.num_turns} turns · {message.duration_ms / 1000:.1f}s · {cost}\n"
            f"{'─' * 40}{_RESET}",
            flush=True,
        )

    elif isinstance(message, SystemMessage):
        if message.subtype not in ("init",):
            print(f"  {_DIM}[{message.subtype}]{_RESET}", flush=True)


# ============================================================
# Worker progress tracking
# ============================================================

_worker_state = {
    "started": 0,
    "completed": 0,
    "id_to_num": {},        # agent_id -> worker number
    "active_workers": {},   # agent_id -> worker number (only while running)
    "num_to_color": {},     # worker number -> ANSI color
    "task_descs": {},       # tool_use_id -> description (from Task tool use blocks)
    "color_index": 0,
    "log_dir": None,        # Path to session folder for per-worker log files
}


def _assign_worker_color(worker_num: int) -> str:
    """Assign a color to a worker number. Returns the ANSI color code."""
    if worker_num not in _worker_state["num_to_color"]:
        idx = _worker_state["color_index"] % len(_WORKER_COLORS)
        _worker_state["num_to_color"][worker_num] = _WORKER_COLORS[idx]
        _worker_state["color_index"] += 1
    return _worker_state["num_to_color"][worker_num]


def _is_onboarding_worker(input_data):
    """Check if this sub-agent is an onboarding-worker.

    Uses agent_type from SubagentStart/SubagentStop input_data directly,
    avoiding the race condition of relying on _task_types from the message stream.
    """
    return input_data.get("agent_type") == "onboarding-worker"


def _active_worker_num() -> int | None:
    """Return the worker number if exactly one worker is active, else None.

    SDK hooks share the same session_id for orchestrator and workers, so we
    can't use session_id for attribution. Instead we track which workers are
    between SubagentStart and SubagentStop. With one active worker, all
    non-Task tool calls belong to it. With multiple, we pick the most recently
    started (best-effort — parallel workers interleave).
    """
    active = _worker_state["active_workers"]
    if not active:
        return None
    if len(active) == 1:
        return next(iter(active.values()))
    # Multiple active: return highest worker number (most recently started)
    return max(active.values())


def _worker_log_path(worker_num: int) -> Path | None:
    """Return the log file path for a given worker number."""
    log_dir = _worker_state.get("log_dir")
    if not log_dir:
        return None
    return Path(log_dir) / f"worker_{worker_num}.log"


def _append_worker_log(worker_num: int, line: str) -> None:
    """Append a timestamped line to a worker's log file."""
    path = _worker_log_path(worker_num)
    if not path:
        return
    ts = datetime.now().strftime("%H:%M:%S")
    with open(path, "a") as f:
        f.write(f"[{ts}] {line}\n")




async def _on_worker_start(input_data, tool_use_id, context):
    """Hook callback: track worker and print start message."""
    if not _is_onboarding_worker(input_data):
        return {}
    _worker_state["started"] += 1
    n = _worker_state["started"]
    agent_id = input_data.get("agent_id", "")
    _worker_state["id_to_num"][agent_id] = n
    _worker_state["active_workers"][agent_id] = n
    # Create empty log file
    path = _worker_log_path(n)
    if path:
        path.touch()
    color = _assign_worker_color(n)
    desc = _worker_state["task_descs"].pop(tool_use_id, "")
    suffix = f" — {desc}" if desc else ""
    print(f"\n  {color}▶ Worker {n} (W{n}) started{suffix}{_RESET}", flush=True)
    _append_worker_log(n, f"Started{suffix}")
    return {}


async def _on_worker_stop(input_data, tool_use_id, context):
    """Hook callback: print stop message and finalize worker log."""
    agent_id = input_data.get("agent_id", "")
    if agent_id not in _worker_state["id_to_num"]:
        return {}
    _worker_state["active_workers"].pop(agent_id, None)
    _worker_state["completed"] += 1
    done = _worker_state["completed"]
    total = _worker_state["started"]
    n = _worker_state["id_to_num"].get(agent_id, "?")
    color = _worker_state["num_to_color"].get(n, _GREEN)
    print(f"  {color}✓ Worker {n} (W{n}) done ({done}/{total}){_RESET}", flush=True)
    _append_worker_log(n, f"Finished ({done}/{total})")
    return {}


async def _worker_log_hook(input_data, tool_use_id, context):
    """PreToolUse hook: log every worker tool action to per-worker log files.

    Uses PreToolUse (not PostToolUse) because PostToolUse doesn't fire reliably
    for all tool types in sub-agents. Skips Task calls (always orchestrator).
    """
    tool_name = input_data.get("tool_name", "?")
    if tool_name == "Task":
        return {}  # Orchestrator spawning a worker — not a worker action
    worker_num = _active_worker_num()
    if worker_num is None:
        return {}  # No active workers — orchestrator tool call
    tool_input = input_data.get("tool_input", {})
    detail = _tool_detail_from_dict(tool_name, tool_input)
    _append_worker_log(worker_num, f"{tool_name}: {detail}")
    return {}


async def _write_edit_guard_hook(input_data, tool_use_id, context):
    """PreToolUse hook: prompt user to approve Write/Edit tool calls."""
    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    file_path = tool_input.get("file_path", "?")

    # Auto-approve writes to the session folder (state file, log files)
    log_dir = _worker_state.get("log_dir")
    if log_dir and file_path.startswith(str(log_dir)):
        return {}

    # Show details and prompt
    if tool_name == "Edit":
        old = tool_input.get("old_string", "")
        new = tool_input.get("new_string", "")
        print(f"\n  {_YELLOW}Edit {file_path}{_RESET}")
        print(f"  {_DIM}{_RED}- {_truncate(old, 300)}{_RESET}")
        print(f"  {_DIM}{_GREEN}+ {_truncate(new, 300)}{_RESET}")
    else:
        content = tool_input.get("content", "")
        print(f"\n  {_YELLOW}Write {file_path}{_RESET} ({len(content)} chars)")

    print(f"  {_YELLOW}Allow? [Y/n]{_RESET} ", end="", flush=True)
    loop = asyncio.get_event_loop()
    line = await loop.run_in_executor(None, sys.stdin.readline)
    answer = line.strip().lower() if line else ""

    if answer in ("", "y", "yes"):
        return {}  # Allow

    # Denied — prompt for instructions to feed back to the agent
    print(f"  {_YELLOW}Instructions for agent (or Enter to skip):{_RESET} ", end="", flush=True)
    instr_line = await loop.run_in_executor(None, sys.stdin.readline)
    instructions = instr_line.strip() if instr_line else ""
    reason = instructions or "User denied this change."

    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


async def _monitor_progress(log_dir: Path, stop_event: asyncio.Event) -> None:
    """Background task: tail per-worker log files and print updates.

    Dynamically discovers new worker_*.log files as workers start.
    """
    file_positions: dict[str, int] = {}  # filename -> file position

    while not stop_event.is_set():
        try:
            for log_file in sorted(log_dir.glob("worker_*.log")):
                name = log_file.name
                pos = file_positions.get(name, 0)
                with open(log_file) as f:
                    f.seek(pos)
                    new_lines = f.readlines()
                    file_positions[name] = f.tell()

                if not new_lines:
                    continue

                # Extract worker number from filename (worker_3.log -> 3)
                try:
                    wnum = int(name.split("_")[1].split(".")[0])
                except (IndexError, ValueError):
                    wnum = 0
                color = _assign_worker_color(wnum)

                for raw_line in new_lines:
                    line = raw_line.strip()
                    if line:
                        print(f"\n{color}W{wnum}{_RESET} {_DIM}{line}{_RESET}", flush=True)
        except Exception:
            pass

        await asyncio.sleep(0.5)


# ============================================================
# Turn-end classification
# ============================================================


def _classify_turn_end(result_msg) -> str:
    """Classify why the agent's turn ended. Returns one of:
    - "error": API or execution error — should auto-retry
    - "done": agent signalled onboarding is complete — exit
    - "continue": agent was working and stopped — auto-continue

    User interaction is handled structurally via the ask_human MCP tool,
    not by heuristically detecting question marks in the agent's text.
    """
    if result_msg is None:
        return "continue"

    # Transient / API errors → auto-retry
    if result_msg.is_error:
        return "error"

    result = getattr(result_msg, "result", None) or ""

    # Agent explicitly finished onboarding
    if any(phrase in result.lower() for phrase in [
        "onboarding complete",
        "onboarding is complete",
        "onboarding finished",
    ]):
        return "done"

    # Default: agent was working, let it continue
    return "continue"


# ============================================================
# Main orchestrator
# ============================================================

def _build_ask_human_server():
    """Build an in-process MCP server with an ask_human tool.

    This replaces AskUserQuestion (which doesn't work through the SDK's subprocess
    transport) with a custom tool that prints to stdout and reads from stdin.
    """
    from claude_agent_sdk import tool, create_sdk_mcp_server

    @tool(
        "ask_human",
        "Ask the human operator a question and wait for their answer. "
        "Use this whenever you need clarification, confirmation, or input from the human. "
        "The question will be displayed in the terminal and execution blocks until they respond.",
        {"question": str},
    )
    async def ask_human(args: dict) -> dict:
        question = args["question"]
        loop = asyncio.get_event_loop()
        print(f"\n{_YELLOW}Agent asks:{_RESET} {question}", flush=True)
        print(f"{_YELLOW}>>>{_RESET} ", end="", flush=True)
        line = await loop.run_in_executor(None, sys.stdin.readline)
        answer = line.strip() if line else ""
        if not answer:
            answer = "(no response)"
        return {"content": [{"type": "text", "text": answer}]}

    return create_sdk_mcp_server(
        name="onboarding",
        version="1.0.0",
        tools=[ask_human],
    )


async def _run_onboarding_async(args):
    from ao.onboarding.prompts import build_orchestrator_prompt, build_worker_prompt
    from ao.onboarding.hooks import guard_hook, audit_hook
    from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions, AgentDefinition, HookMatcher

    # Agent SDK spawns Claude Code as subprocess; clear nesting guard
    os.environ.pop("CLAUDECODE", None)

    repo_path = str(Path(args.repo_path).resolve())
    max_parallel = args.max_parallel
    worker_model = args.model

    # Set up per-session folder (reuse existing on resume, new UUID otherwise)
    run_id = getattr(args, "_run_id", None) or str(uuid.uuid4())
    session_folder = _session_dir(run_id)
    state_file = session_folder / "onboarding.md"
    print(f"{_DIM}Run: {run_id}{_RESET}", flush=True)
    print(f"{_DIM}State: {state_file}{_RESET}", flush=True)

    # Save session metadata early (claude_session_id filled in after first turn)
    _save_session(run_id, args)

    # Load SKILL.md and build prompts with it
    skill_content = _load_skill_md()
    orchestrator_prompt = build_orchestrator_prompt(skill_content, state_file=str(state_file))
    worker_prompt = build_worker_prompt(skill_content)

    # Set up worker state tracking (per-worker logs live in session folder)
    _worker_state.update(
        started=0, completed=0, id_to_num={}, active_workers={},
        num_to_color={}, task_descs={}, color_index=0,
        log_dir=str(session_folder),
    )

    # Build the ask_human MCP server (must be created before options)
    ask_human_server = _build_ask_human_server()

    prompt_parts = [
        f"Onboard the repository at: {repo_path}",
        f"Maximum parallel workers: {max_parallel}.",
        "Follow the process described in your instructions.",
    ]
    if getattr(args, "instructions", None):
        prompt_parts.append(f"\nAdditional instructions:\n{args.instructions}")

    prompt_text = "\n".join(prompt_parts)

    resume_session = getattr(args, "resume", None)
    fork_session = getattr(args, "fork", False)

    options = ClaudeAgentOptions(
        system_prompt=orchestrator_prompt,
        allowed_tools=[
            "Read",
            "Glob",
            "Grep",
            "Bash",
            "Task",
            "Write",
            "Edit",
            "mcp__onboarding__ask_human",
        ],
        mcp_servers={"onboarding": ask_human_server},
        permission_mode="default",
        model="opus",
        max_turns=1000,
        max_buffer_size=100_000_000,  # 100MB — default 1MB is too small for large tool results
        cwd=repo_path,
        resume=resume_session,
        fork_session=fork_session,
        hooks={
            "PreToolUse": [
                HookMatcher(matcher="Bash", hooks=[guard_hook]),
                HookMatcher(matcher="Write", hooks=[_write_edit_guard_hook]),
                HookMatcher(matcher="Edit", hooks=[_write_edit_guard_hook]),
                HookMatcher(hooks=[_worker_log_hook]),
            ],
            "PostToolUse": [
                HookMatcher(matcher="Bash", hooks=[audit_hook]),
            ],
            "SubagentStart": [
                HookMatcher(hooks=[_on_worker_start]),
            ],
            "SubagentStop": [
                HookMatcher(hooks=[_on_worker_stop]),
            ],
        },
        agents={
            "onboarding-worker": AgentDefinition(
                description=(
                    "Onboarding worker agent. Spawned to process a chunk of "
                    "samples from the dataset. Runs the agent on each sample, "
                    "evaluates results, diagnoses failures, creates and verifies "
                    "lessons via ao-tool."
                ),
                prompt=worker_prompt,
                tools=["Bash", "Read", "Glob", "Grep", "Write"],
                model=worker_model,
            ),
        },
    )

    loop = asyncio.get_event_loop()

    # Start progress monitor (tails per-worker log files in session folder)
    stop_monitor = asyncio.Event()
    monitor_task = asyncio.create_task(_monitor_progress(session_folder, stop_monitor))

    try:
        async with ClaudeSDKClient(options=options) as client:
            if resume_session:
                # Resuming — prompt for guidance before continuing
                print(f"\n{_YELLOW}Resuming session {resume_session[:8]}...{_RESET}", flush=True)
                print(f"{_YELLOW}Enter guidance for the agent (or press Enter to continue as-is):{_RESET}", flush=True)
                print(f"{_YELLOW}>>>{_RESET} ", end="", flush=True)
                line = await loop.run_in_executor(None, sys.stdin.readline)
                guidance = line.strip() if line else ""
                await client.query(guidance or "Continue where you left off.")
            else:
                await client.query(prompt_text)

            while True:
                # Receive agent's full response (until ResultMessage)
                session_id = None
                result_msg = None
                async for message in client.receive_response():
                    _print_message(message)
                    if hasattr(message, "session_id"):
                        session_id = message.session_id
                    if hasattr(message, "is_error"):
                        result_msg = message

                if session_id:
                    print(f"\n{_DIM}Session: {session_id} (run: {run_id[:8]}){_RESET}", flush=True)
                    _save_session(run_id, args, claude_session_id=session_id)

                # Decide what to do based on how the turn ended
                action = _classify_turn_end(result_msg)

                if action == "error":
                    print(f"\n  {_RED}Agent hit an error. Auto-retrying...{_RESET}", flush=True)
                    await client.query("An error occurred. Please continue where you left off.")

                elif action == "done":
                    print(f"\n  {_GREEN}Onboarding complete.{_RESET}", flush=True)
                    break

                else:  # "continue"
                    await client.query("Continue.")
    finally:
        stop_monitor.set()
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass


def main():
    """Entry point when run under ao-record."""
    try:
        import claude_agent_sdk  # noqa: F401
    except ImportError:
        print(
            "Error: claude-agent-sdk is not installed.\n"
            "Install it with: pip install claude-agent-sdk\n"
            "Or from ao-dev: uv sync --extra onboard",
            file=sys.stderr,
        )
        sys.exit(1)

    parser = ArgumentParser(description="Onboarding orchestrator agent")
    parser.add_argument("repo_path", nargs="?", default=None, help="Path to the target repository")
    parser.add_argument("--max-parallel", type=int, default=4)
    parser.add_argument("--model", default="sonnet", choices=["opus", "sonnet", "haiku"])
    parser.add_argument("--instructions", default=None)
    parser.add_argument("--resume", default=None, help="Session ID to resume (or 'last')")
    parser.add_argument("--fork", action="store_true", help="Fork into a new session when resuming")
    args = parser.parse_args()

    if args.resume:
        if args.resume == "last":
            saved = _find_last_session()
            if not saved:
                print("No previous session found.", file=sys.stderr)
                sys.exit(1)
        else:
            saved = _load_session(args.resume)
        if not saved:
            print(f"No saved session found for '{args.resume}'.", file=sys.stderr)
            sys.exit(1)
        # Restore claude_session_id for SDK resume and run_id for folder reuse
        args.resume = saved["claude_session_id"]
        args._run_id = saved["run_id"]
        # Restore saved args (CLI flags override if explicitly provided)
        args.repo_path = args.repo_path or saved["repo_path"]
        if args.max_parallel == 4:  # default wasn't overridden
            args.max_parallel = saved["max_parallel"]
        if args.model == "sonnet":  # default wasn't overridden
            args.model = saved["model"]
        if not args.instructions and saved.get("instructions"):
            args.instructions = saved["instructions"]
        print(f"Resuming session: {args.resume[:8]}... (run: {args._run_id[:8]})")

    if not args.repo_path:
        print("Error: repo_path is required (provide it or use --resume with a saved session).", file=sys.stderr)
        sys.exit(1)

    asyncio.run(_run_onboarding_async(args))


if __name__ == "__main__":
    main()
