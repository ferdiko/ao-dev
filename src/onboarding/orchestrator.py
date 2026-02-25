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
import re
import sys
import tempfile
import uuid
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


def _tool_detail(block) -> str:
    """Extract the most relevant detail from a tool use block."""
    inp = block.input
    if block.name == "Bash":
        return _truncate(inp.get("command", ""), 300)
    if block.name == "Task":
        return inp.get("description", "")
    if block.name in ("Read", "Write", "Edit"):
        return inp.get("file_path", "?")
    if block.name in ("Glob", "Grep"):
        return inp.get("pattern", "")
    return ""


# Tool-use IDs to suppress from output (e.g., worker progress writes)
_suppressed_tool_ids: set = set()


def _is_progress_write(block) -> bool:
    """Check if a tool use block is a worker progress write (should be hidden)."""
    if block.name != "Bash":
        return False
    cmd = block.input.get("command", "")
    return "[W" in cmd and ">>" in cmd


def _print_message(message) -> None:
    """Print a message from the SDK with clear formatting."""
    from claude_agent_sdk.types import (
        AssistantMessage,
        ResultMessage,
        SystemMessage,
        UserMessage,
    )

    if isinstance(message, AssistantMessage):
        for block in message.content:
            if hasattr(block, "text"):
                # Claude's text — left-bordered like a blockquote
                lines = block.text.split("\n")
                bordered = "\n".join(f"  {_DIM}{_CYAN}│{_RESET} {l}" for l in lines)
                print(f"\n{bordered}", flush=True)
            elif hasattr(block, "name"):
                if _is_progress_write(block):
                    _suppressed_tool_ids.add(block.id)
                    continue
                # Stash Task metadata for worker start messages
                if block.name == "Task":
                    desc = block.input.get("description", "")
                    if desc:
                        _worker_state["task_descs"][block.id] = desc
                    agent_type = block.input.get("subagent_type", "")
                    if agent_type:
                        _worker_state.setdefault("_task_types", {})[block.id] = agent_type
                # Tool use header — bold, compact
                detail = _tool_detail(block)
                print(f"\n  {_BOLD}{block.name}{_RESET}  {detail}", flush=True)

    elif isinstance(message, UserMessage):
        # Tool results — dim with └ connector, color-coded
        if isinstance(message.content, list):
            for block in message.content:
                if hasattr(block, "tool_use_id"):
                    if block.tool_use_id in _suppressed_tool_ids:
                        _suppressed_tool_ids.discard(block.tool_use_id)
                        continue
                    if block.content:
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

# Matches lines like "[W1] doing something" or "[W12] anything"
_WORKER_PREFIX_RE = re.compile(r"^\[W(\d+)\]\s*(.*)$")

_worker_state = {
    "started": 0,
    "completed": 0,
    "id_to_num": {},        # agent_id -> worker number
    "num_to_color": {},     # worker number -> ANSI color
    "task_descs": {},       # tool_use_id -> description (from Task tool use blocks)
    "progress_dir": None,
    "color_index": 0,
}


def _assign_worker_color(worker_num: int) -> str:
    """Assign a color to a worker number. Returns the ANSI color code."""
    if worker_num not in _worker_state["num_to_color"]:
        idx = _worker_state["color_index"] % len(_WORKER_COLORS)
        _worker_state["num_to_color"][worker_num] = _WORKER_COLORS[idx]
        _worker_state["color_index"] += 1
    return _worker_state["num_to_color"][worker_num]


def _is_onboarding_worker(input_data, tool_use_id):
    """Check if this sub-agent is an onboarding-worker (not a generic Task)."""
    # Check subagent_type from Task tool input stashed in _print_message
    return _worker_state.get("_task_types", {}).get(tool_use_id) == "onboarding-worker"


async def _on_worker_start(input_data, tool_use_id, context):
    """Hook callback: prints when a worker sub-agent starts."""
    if not _is_onboarding_worker(input_data, tool_use_id):
        return {}
    _worker_state["started"] += 1
    n = _worker_state["started"]
    agent_id = input_data.get("agent_id", "")
    _worker_state["id_to_num"][agent_id] = n
    color = _assign_worker_color(n)
    desc = _worker_state["task_descs"].pop(tool_use_id, "")
    suffix = f" — {desc}" if desc else ""
    print(f"\n  {color}▶ Worker {n} (W{n}) started{suffix}{_RESET}", flush=True)
    return {}


async def _on_worker_stop(input_data, tool_use_id, context):
    """Hook callback: prints when a worker sub-agent finishes."""
    agent_id = input_data.get("agent_id", "")
    if agent_id not in _worker_state["id_to_num"]:
        return {}
    _worker_state["completed"] += 1
    done = _worker_state["completed"]
    total = _worker_state["started"]
    n = _worker_state["id_to_num"].get(agent_id, "?")
    color = _worker_state["num_to_color"].get(n, _GREEN)
    print(f"  {color}✓ Worker {n} (W{n}) done ({done}/{total}){_RESET}", flush=True)
    return {}


def _setup_progress_dir() -> Path:
    """Create a temp directory for worker progress files."""
    d = Path(tempfile.mkdtemp(prefix="ao-onboard-"))
    _worker_state["progress_dir"] = d
    return d


async def _monitor_progress(progress_file: Path, stop_event: asyncio.Event) -> None:
    """Background task: tail progress file and print colored worker updates.

    Workers append free-form lines prefixed with [WN]:
        [W1] Running agent on sample bird-042
        [W3] Lesson created: table_alias_convention
        [W1] Sample bird-042: PASS

    Lines without a [WN] prefix are printed dimmed with no worker attribution.
    """
    file_pos = 0

    while not stop_event.is_set():
        try:
            if progress_file.exists():
                with open(progress_file) as f:
                    f.seek(file_pos)
                    new_lines = f.readlines()
                    file_pos = f.tell()

                for raw_line in new_lines:
                    line = raw_line.strip()
                    if not line:
                        continue

                    m = _WORKER_PREFIX_RE.match(line)
                    if m:
                        wnum = int(m.group(1))
                        text = m.group(2)
                        color = _assign_worker_color(wnum)
                        print(
                            f"\n{color}W{wnum}{_RESET} {_DIM}{text}{_RESET}",
                            flush=True,
                        )
                    else:
                        # No worker prefix — print dimmed
                        print(f"{_DIM}{line}{_RESET}", flush=True)
        except Exception:
            pass

        await asyncio.sleep(0.5)


# ============================================================
# Main orchestrator
# ============================================================

async def _approve_code_changes(tool_name, input_data, context):
    """Prompt user to approve file writes and edits."""
    from claude_agent_sdk.types import PermissionResultAllow, PermissionResultDeny

    if tool_name not in ("Write", "Edit"):
        return PermissionResultAllow(updated_input=input_data)

    file_path = input_data.get("file_path", "?")
    if tool_name == "Edit":
        old = input_data.get("old_string", "")
        new = input_data.get("new_string", "")
        print(f"\n  {_YELLOW}Edit {file_path}{_RESET}")
        print(f"  {_DIM}{_RED}- {_truncate(old, 300)}{_RESET}")
        print(f"  {_DIM}{_GREEN}+ {_truncate(new, 300)}{_RESET}")
    else:
        content = input_data.get("content", "")
        print(f"\n  {_YELLOW}Write {file_path}{_RESET} ({len(content)} chars)")

    print(f"  {_YELLOW}Allow? [Y/n]{_RESET} ", end="", flush=True)
    loop = asyncio.get_event_loop()
    line = await loop.run_in_executor(None, sys.stdin.readline)
    answer = line.strip().lower() if line else ""

    if answer in ("", "y", "yes"):
        return PermissionResultAllow(updated_input=input_data)
    return PermissionResultDeny(message="User denied this change.")


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

    # Set up progress tracking
    _worker_state.update(
        started=0, completed=0, id_to_num={}, num_to_color={}, task_descs={}, color_index=0,
    )
    progress_dir = _setup_progress_dir()
    progress_file = progress_dir / "progress.log"

    prompt_parts = [
        f"Onboard the repository at: {repo_path}",
        f"Maximum parallel workers: {max_parallel}.",
        f"Progress file for workers: {progress_file}",
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
        ],
        permission_mode="default",
        model="opus",
        max_turns=1000,
        max_buffer_size=100_000_000,  # 100MB — default 1MB is too small for large tool results
        cwd=repo_path,
        resume=resume_session,
        fork_session=fork_session,
        can_use_tool=_approve_code_changes,
        hooks={
            "PreToolUse": [
                HookMatcher(matcher="Bash", hooks=[guard_hook]),
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

    # Start progress monitor
    stop_monitor = asyncio.Event()
    monitor_task = asyncio.create_task(_monitor_progress(progress_file, stop_monitor))

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
                async for message in client.receive_response():
                    _print_message(message)
                    if hasattr(message, "session_id"):
                        session_id = message.session_id

                if session_id:
                    print(f"\n{_DIM}Session: {session_id} (run: {run_id[:8]}){_RESET}", flush=True)
                    _save_session(run_id, args, claude_session_id=session_id)

                # Agent stopped — prompt for human input
                print(f"\n{_YELLOW}Type your response (or press Enter to end):{_RESET}", flush=True)
                print(f"{_YELLOW}>>>{_RESET} ", end="", flush=True)
                line = await loop.run_in_executor(None, sys.stdin.readline)

                if not line or not line.strip():
                    break

                await client.query(line.strip())
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
