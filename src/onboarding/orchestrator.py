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
import time
import uuid
from dataclasses import dataclass, field
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


def _save_session(run_id: str, args, claude_session_id: str | None = None,
                   branch_name: str | None = None) -> None:
    """Write a read-only session.json inside the session folder."""
    from datetime import datetime, timezone
    path = _session_dir(run_id) / "session.json"
    data = {
        "run_id": run_id,
        "claude_session_id": claude_session_id,
        "repo_path": str(Path(args.repo_path).resolve()),
        "max_parallel": args.max_parallel,
        "worker_model": args.worker_model,
        "orchestrator_model": args.orchestrator_model,
        "branch_name": branch_name,
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


def _setup_onboarding_branch(repo_path: str, run_id: str) -> str:
    """Create and checkout an onboarding branch in the target repo.

    On resume, checks out the existing branch. Otherwise creates a new one
    from the current HEAD.  Returns the branch name.
    """
    import subprocess

    branch_name = f"ao-onboard/{run_id[:8]}"

    # Check if branch already exists (resume case)
    result = subprocess.run(
        ["git", "rev-parse", "--verify", branch_name],
        cwd=repo_path, capture_output=True, text=True,
    )
    if result.returncode == 0:
        subprocess.run(
            ["git", "checkout", branch_name],
            cwd=repo_path, check=True, capture_output=True, text=True,
        )
    else:
        subprocess.run(
            ["git", "checkout", "-b", branch_name],
            cwd=repo_path, check=True, capture_output=True, text=True,
        )

    return branch_name


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


@dataclass
class WorkerContext:
    """Per-worker state tracked across the worker's lifetime."""
    num: int
    briefing: str
    batch: int = 0                 # which dispatch_workers call created this worker
    max_turns: int = 200
    client: object = None          # ClaudeSDKClient instance (for interrupt)
    status: str = "pending"        # pending / running / completed / errored / killed
    start_time: float = 0.0
    last_activity: float = 0.0
    recent_actions: list = field(default_factory=list)  # [{time, tool, detail}]
    action_counter: int = 0  # monotonic counter for progress printer tracking
    result_text: str = ""
    error_text: str = ""
    cost_usd: float = 0.0
    num_turns: int = 0
    duration_s: float = 0.0
    kill_reason: str = ""
    last_haiku_check: float = 0.0  # timestamp of last haiku assessment
    last_alerted: float = 0.0     # timestamp of last heartbeat alert (cooldown)


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
        for block in message.content:
            if hasattr(block, "text"):
                lines = block.text.split("\n")
                bordered = "\n".join(f"  {_DIM}{_CYAN}│{_RESET} {l}" for l in lines)
                print(f"\n{bordered}", flush=True)
            elif hasattr(block, "name"):
                detail = _tool_detail(block)
                print(f"\n  {_BOLD}{block.name}{_RESET}  {detail}", flush=True)

    elif isinstance(message, UserMessage):
        if isinstance(message.content, list):
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
    "num_to_color": {},     # worker number -> ANSI color
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


def _append_worker_log(worker_num: int, line: str) -> None:
    """Append a timestamped line to a worker's log file (for persistence)."""
    log_dir = _worker_state.get("log_dir")
    if not log_dir:
        return
    path = Path(log_dir) / f"worker_{worker_num}.log"
    ts = datetime.now().strftime("%H:%M:%S")
    with open(path, "a") as f:
        f.write(f"[{ts}] {line}\n")


async def _run_single_worker(ctx: WorkerContext, worker_prompt: str, worker_model: str, repo_path: str) -> None:
    """Run a single worker as an independent ClaudeSDKClient."""
    from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
    from claude_agent_sdk.types import AssistantMessage, ResultMessage, UserMessage

    ctx.status = "running"
    ctx.start_time = time.time()
    ctx.last_activity = time.time()

    color = _assign_worker_color(ctx.num)

    def _ts():
        return datetime.now().strftime("%H:%M:%S")

    def _wtag():
        return f"{_DIM}[{_ts()}]{_RESET} {color}W{ctx.num}{_RESET}"

    print(f"\n{_wtag()} {color}▶ started{_RESET}", flush=True)
    _append_worker_log(ctx.num, "Started")

    options = ClaudeAgentOptions(
        system_prompt={"type": "preset", "preset": "claude_code", "append": worker_prompt},
        allowed_tools=["Bash", "Read", "Glob", "Grep", "Write"],
        permission_mode="bypassPermissions",
        model=worker_model,
        max_turns=ctx.max_turns,
        cwd=repo_path,
    )

    try:
        async with ClaudeSDKClient(options=options) as client:
            ctx.client = client
            await client.query(ctx.briefing)

            try:
                async for msg in client.receive_response():
                    ctx.last_activity = time.time()

                    if isinstance(msg, AssistantMessage):
                        for block in msg.content:
                            if hasattr(block, "text") and block.text.strip():
                                for line in block.text.split("\n"):
                                    print(f"{_wtag()} {_DIM}{_CYAN}│{_RESET} {line}", flush=True)
                                _append_worker_log(ctx.num, f"[text] {block.text}")
                            elif hasattr(block, "name"):
                                ctx.action_counter += 1
                                detail = _tool_detail(block)
                                action = {
                                    "seq": ctx.action_counter,
                                    "time": time.time(),
                                    "tool": block.name,
                                    "detail": detail,
                                }
                                ctx.recent_actions.append(action)
                                if len(ctx.recent_actions) > 30:
                                    ctx.recent_actions = ctx.recent_actions[-30:]
                                print(f"\n{_wtag()} {_BOLD}{block.name}{_RESET}  {detail}", flush=True)
                                _append_worker_log(ctx.num, f"{block.name}: {detail}")

                    elif isinstance(msg, UserMessage):
                        if isinstance(msg.content, list):
                            for block in msg.content:
                                content = getattr(block, "content", None)
                                if content:
                                    text = str(content) if not isinstance(content, str) else content
                                    is_err = getattr(block, "is_error", False)
                                    rc = _RED if is_err else _DIM
                                    print(f"{_wtag()} {rc}  └ {_truncate(text, 2000)}{_RESET}", flush=True)
                                    _append_worker_log(ctx.num, f"{'ERROR' if is_err else 'result'}: {text}")

                    elif isinstance(msg, ResultMessage):
                        ctx.result_text = msg.result or ""
                        ctx.cost_usd = msg.total_cost_usd or 0.0
                        ctx.num_turns = msg.num_turns
            except Exception:
                pass  # Worker was killed (SIGTERM) — status already set by kill_worker_tool

            if ctx.status == "running":  # don't overwrite "killed"
                ctx.status = "completed"

    except Exception as e:
        if ctx.status == "running":  # don't overwrite "killed"
            ctx.status = "errored"
            ctx.error_text = str(e)

    finally:
        ctx.client = None
        ctx.duration_s = time.time() - ctx.start_time

    status_icon = "✓" if ctx.status == "completed" else "✗"
    status_label = ctx.status
    if ctx.status == "errored":
        status_label = f"errored: {_truncate(ctx.error_text, 100)}"
    print(f"{_wtag()} {color}{status_icon} {status_label}{_RESET}", flush=True)
    _append_worker_log(ctx.num, f"Finished — {ctx.status}")


async def _haiku_assess(ctx: WorkerContext, haiku_client) -> dict:
    """Use haiku to assess whether a worker is making meaningful progress.

    Returns {"stuck": bool, "reason": str}.
    haiku_client is an anthropic.AsyncAnthropic instance (reused across calls).
    """
    if haiku_client is None:
        return {"stuck": False, "reason": "anthropic SDK not available"}

    actions_text = "\n".join(
        f"[{datetime.fromtimestamp(a['time']).strftime('%H:%M:%S')}] {a['tool']}: {a['detail']}"
        for a in ctx.recent_actions[-20:]
    )
    if not actions_text:
        return {"stuck": False, "reason": "no actions to assess"}

    prompt = (
        "Analyze this AI agent worker's recent tool calls and determine if it's making "
        "meaningful progress or if it appears stuck (looping, thrashing, or spinning "
        "without progress).\n\n"
        f"Recent actions (most recent last):\n{actions_text}\n\n"
        'Respond with JSON only: {"stuck": true/false, "reason": "brief explanation"}'
    )

    try:
        response = await haiku_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        # Parse JSON from response (handle markdown code blocks)
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        return json.loads(text)
    except Exception:
        return {"stuck": False, "reason": "assessment failed"}


async def _heartbeat_monitor(
    workers: dict[int, WorkerContext],
    alerts_queue: asyncio.Queue,
    haiku_client,
    check_interval: float = 30.0,
    silence_timeout: float = 1200.0,  # 20 minutes
    haiku_interval: float = 300.0,    # 5 minutes
) -> None:
    """Background task: monitor worker health and put alerts on queue.

    Never kills workers directly — only surfaces alerts for the orchestrator to handle.
    """
    while True:
        await asyncio.sleep(check_interval)

        now = time.time()
        for ctx in list(workers.values()):
            if ctx.status != "running":
                continue

            # Skip if we already alerted about this worker recently (10 min cooldown)
            if now - ctx.last_alerted < 600:
                continue

            # Tier 1: silence detection (Python, zero cost)
            silence = now - ctx.last_activity
            if silence > silence_timeout:
                last_actions = [
                    {"time": datetime.fromtimestamp(a["time"]).strftime("%H:%M:%S"),
                     "tool": a["tool"], "detail": a["detail"]}
                    for a in ctx.recent_actions[-5:]
                ]
                ctx.last_alerted = now
                await alerts_queue.put({
                    "worker_num": ctx.num,
                    "type": "silence",
                    "assessment": f"No activity for {silence / 60:.0f} minutes. "
                                  "Worker may be hanging on a long-running command or has crashed.",
                    "silence_seconds": int(silence),
                    "recent_actions": last_actions,
                })
                continue

            # Tier 2: haiku semantic assessment (every haiku_interval per worker)
            runtime = now - ctx.start_time
            if runtime < haiku_interval:
                continue  # Too early for haiku checks
            if now - ctx.last_haiku_check < haiku_interval:
                continue  # Not time yet

            ctx.last_haiku_check = now
            assessment = await _haiku_assess(ctx, haiku_client)

            if assessment.get("stuck"):
                last_actions = [
                    {"time": datetime.fromtimestamp(a["time"]).strftime("%H:%M:%S"),
                     "tool": a["tool"], "detail": a["detail"]}
                    for a in ctx.recent_actions[-10:]
                ]
                color = _assign_worker_color(ctx.num)
                ts = datetime.now().strftime("%H:%M:%S")
                print(f"\n{_DIM}[{ts}]{_RESET} {color}⚠ W{ctx.num} flagged:{_RESET} {_DIM}{assessment['reason']}{_RESET}", flush=True)
                ctx.last_alerted = now
                await alerts_queue.put({
                    "worker_num": ctx.num,
                    "type": "stuck",
                    "assessment": assessment.get("reason", ""),
                    "silence_seconds": 0,
                    "recent_actions": last_actions,
                })






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

def _build_mcp_server(
    *,
    repo_path: str,
    worker_prompt: str,
    worker_model: str,
    max_parallel: int,
    session_folder: Path,
):
    """Build an in-process MCP server with ask_human, dispatch_workers, and kill_worker.

    State (workers, tasks, heartbeat) persists across tool calls via closure.
    """
    from claude_agent_sdk import tool, create_sdk_mcp_server

    # ── Persistent state across tool calls ──
    workers: dict[int, WorkerContext] = {}
    worker_tasks: dict[int, asyncio.Task] = {}
    heartbeat_alerts: asyncio.Queue = asyncio.Queue()
    pending_queue: list[WorkerContext] = []
    next_worker_num = 0
    heartbeat_task: asyncio.Task | None = None
    current_batch = 0

    # Create shared haiku client for heartbeat assessments (reused across calls)
    try:
        import anthropic as _anthropic
        haiku_client = _anthropic.AsyncAnthropic()
    except ImportError:
        haiku_client = None

    def _next_num():
        nonlocal next_worker_num
        next_worker_num += 1
        return next_worker_num

    def _running_count():
        return sum(1 for t in worker_tasks.values() if not t.done())

    def _fill_slots():
        while pending_queue and _running_count() < max_parallel:
            ctx = pending_queue.pop(0)
            task = asyncio.create_task(
                _run_single_worker(ctx, worker_prompt, worker_model, repo_path)
            )
            worker_tasks[ctx.num] = task

    # ── ask_human ──

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

    # ── dispatch_workers ──

    @tool(
        "dispatch_workers",
        "Start worker agents and wait for completion or heartbeat alert. "
        "Pass worker briefings to start new workers. Omit or pass empty list to "
        "just wait for existing running workers. Returns when all workers complete "
        "or a heartbeat alert fires (stuck/silent worker detected). "
        "After handling an alert, call again (with or without new workers) to resume waiting.",
        {
            "type": "object",
            "properties": {
                "workers": {
                    "type": "array",
                    "description": "New workers to start. Omit to just wait for existing workers.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "briefing": {"type": "string", "description": "Full worker briefing/prompt"},
                            "max_turns": {"type": "integer", "description": "Max turns (default 200)"},
                        },
                        "required": ["briefing"],
                    },
                },
            },
        },
    )
    async def dispatch_workers_tool(args: dict) -> dict:
        nonlocal heartbeat_task, current_batch
        new_workers = args.get("workers") or []

        # Log what was dispatched so the terminal shows orchestrator decisions
        ts = datetime.now().strftime("%H:%M:%S")
        if new_workers:
            print(f"\n{_DIM}[{ts}]{_RESET} {_BOLD}dispatch_workers:{_RESET} {len(new_workers)} new worker(s)", flush=True)
            for i, spec in enumerate(new_workers, 1):
                briefing_preview = _truncate(spec["briefing"], 120)
                turns = spec.get("max_turns", 200)
                print(f"    {_DIM}#{i}: max_turns={turns}, briefing: {briefing_preview}{_RESET}", flush=True)
        else:
            running = _running_count()
            pending = len(pending_queue)
            print(f"\n{_DIM}[{ts}] dispatch_workers: resume-wait ({running} running, {pending} pending){_RESET}", flush=True)

        # Add new workers to the persistent pending queue
        if new_workers:
            current_batch += 1
        for spec in new_workers:
            num = _next_num()
            ctx = WorkerContext(
                num=num,
                briefing=spec["briefing"],
                batch=current_batch,
                max_turns=spec.get("max_turns", 200),
            )
            workers[num] = ctx
            pending_queue.append(ctx)

        _fill_slots()

        # Start heartbeat monitor if not running
        if heartbeat_task is None or heartbeat_task.done():
            heartbeat_task = asyncio.create_task(
                _heartbeat_monitor(workers, heartbeat_alerts, haiku_client)
            )

        # Drain any stale alerts from previous calls
        while not heartbeat_alerts.empty():
            try:
                heartbeat_alerts.get_nowait()
            except asyncio.QueueEmpty:
                break

        # Wait for: all workers done, heartbeat alert, or new queue slot
        while True:
            active_tasks = {num: t for num, t in worker_tasks.items() if not t.done()}

            if not active_tasks and not pending_queue:
                return _format_result("all_done", workers, current_batch)

            # Build wait set: active worker tasks + alert sentinel
            alert_sentinel = asyncio.create_task(heartbeat_alerts.get())
            wait_set = set(active_tasks.values()) | {alert_sentinel}

            done, _ = await asyncio.wait(wait_set, return_when=asyncio.FIRST_COMPLETED)

            if alert_sentinel in done:
                # Heartbeat alert fired — return early to orchestrator
                alert = alert_sentinel.result()
                return _format_result("heartbeat_alert", workers, current_batch, alert=alert)
            else:
                # Cancel the unused alert sentinel
                alert_sentinel.cancel()

            # Some workers finished — refill slots from queue
            _fill_slots()

            # If everything is done now, return results
            if not any(not t.done() for t in worker_tasks.values()) and not pending_queue:
                return _format_result("all_done", workers, current_batch)

    # ── kill_worker ──

    @tool(
        "kill_worker",
        "Kill a specific worker by number. Use after receiving a heartbeat alert "
        "and deciding the worker should be stopped. The worker is interrupted and "
        "its status is set to 'killed'.",
        {"worker_num": int},
    )
    async def kill_worker_tool(args: dict) -> dict:
        num = args["worker_num"]
        ctx = workers.get(num)
        if not ctx:
            return {"content": [{"type": "text", "text": f"Worker {num} not found."}]}
        if ctx.status != "running":
            return {"content": [{"type": "text", "text": f"Worker {num} is not running (status: {ctx.status})."}]}

        # Interrupt the worker
        if ctx.client:
            try:
                await ctx.client.interrupt()
            except Exception:
                pass
        ctx.status = "killed"
        ctx.kill_reason = f"Killed by orchestrator"
        ctx.duration_s = time.time() - ctx.start_time

        color = _assign_worker_color(num)
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"{_DIM}[{ts}]{_RESET} {color}✗ W{num} killed{_RESET}", flush=True)
        _append_worker_log(num, "Killed by orchestrator")

        return {"content": [{"type": "text", "text": f"Worker {num} killed."}]}

    async def cleanup():
        """Cancel background tasks and close shared clients."""
        if heartbeat_task and not heartbeat_task.done():
            heartbeat_task.cancel()
        if haiku_client:
            try:
                await haiku_client.close()
            except Exception:
                pass

    server = create_sdk_mcp_server(
        name="onboarding",
        version="1.0.0",
        tools=[ask_human, dispatch_workers_tool, kill_worker_tool],
    )
    return server, cleanup


def _format_result(
    outcome: str,
    workers: dict[int, WorkerContext],
    current_batch: int,
    alert: dict | None = None,
) -> dict:
    """Format worker results as MCP tool response.

    Only includes workers from the current batch (and any still running from
    earlier batches). Historical completed/errored/killed workers are omitted
    to keep the response focused on the current round.
    """
    def _build_entry(ctx: WorkerContext) -> dict:
        entry = {
            "num": ctx.num,
            "status": ctx.status,
            "turns": ctx.num_turns,
            "cost_usd": round(ctx.cost_usd, 4),
            "duration_s": round(ctx.duration_s, 1),
        }
        if ctx.status == "completed":
            entry["result"] = ctx.result_text
        elif ctx.status == "errored":
            entry["error"] = ctx.error_text
        elif ctx.status == "killed":
            entry["kill_reason"] = ctx.kill_reason
        if ctx.status == "running":
            entry["last_activity_seconds_ago"] = round(time.time() - ctx.last_activity, 1)
        return entry

    worker_list = []
    for num in sorted(workers):
        ctx = workers[num]
        # Include current batch + any still-running workers from earlier batches
        if ctx.batch == current_batch or ctx.status in ("running", "pending"):
            worker_list.append(_build_entry(ctx))

    result = {"outcome": outcome, "workers": worker_list}

    if alert:
        result["alert"] = alert

    total_cost = sum(ctx.cost_usd for ctx in workers.values())
    result["total_cost_usd"] = round(total_cost, 4)

    return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}


async def _run_onboarding_async(args):
    from ao.onboarding.prompts import build_orchestrator_prompt, build_worker_prompt
    from ao.onboarding.hooks import guard_hook, audit_hook
    from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions, HookMatcher

    # Agent SDK spawns Claude Code as subprocess; clear nesting guard
    os.environ.pop("CLAUDECODE", None)

    repo_path = str(Path(args.repo_path).resolve())
    max_parallel = args.max_parallel
    worker_model = args.worker_model
    orchestrator_model = args.orchestrator_model

    # Set up per-session folder (reuse existing on resume, new UUID otherwise)
    run_id = getattr(args, "_run_id", None) or str(uuid.uuid4())
    session_folder = _session_dir(run_id)
    state_file = session_folder / "onboarding.md"
    print(f"{_DIM}Run: {run_id}{_RESET}", flush=True)
    print(f"{_DIM}State: {state_file}{_RESET}", flush=True)

    # Create/checkout onboarding branch in target repo
    branch_name = _setup_onboarding_branch(repo_path, run_id)
    print(f"{_DIM}Branch: {branch_name}{_RESET}", flush=True)

    # Save session metadata early (claude_session_id filled in after first turn)
    _save_session(run_id, args, branch_name=branch_name)

    # Load SKILL.md and build prompts (constant strings, cached via preset mode)
    skill_content = _load_skill_md()
    orchestrator_prompt = build_orchestrator_prompt(skill_content)
    worker_prompt = build_worker_prompt(skill_content)

    # Set up worker state (color assignment + log dir)
    _worker_state.update(num_to_color={}, color_index=0, log_dir=str(session_folder))

    # Build MCP server with ask_human, dispatch_workers, kill_worker
    mcp_server, mcp_cleanup = _build_mcp_server(
        repo_path=repo_path,
        worker_prompt=worker_prompt,
        worker_model=worker_model,
        max_parallel=max_parallel,
        session_folder=session_folder,
    )

    prompt_parts = [
        f"Onboard the repository at: {repo_path}",
        f"Maximum parallel workers: {max_parallel}.",
        f"State file: {state_file}",
        f"Onboarding branch: {branch_name}",
        "Follow the process described in your instructions.",
    ]
    if getattr(args, "instructions", None):
        prompt_parts.append(f"\nAdditional instructions:\n{args.instructions}")

    prompt_text = "\n".join(prompt_parts)

    resume_session = getattr(args, "resume", None)
    fork_session = getattr(args, "fork", False)

    options = ClaudeAgentOptions(
        system_prompt={"type": "preset", "preset": "claude_code", "append": orchestrator_prompt},
        allowed_tools=[
            "Read",
            "Glob",
            "Grep",
            "Bash",
            "Task",
            "Write",
            "Edit",
            "mcp__onboarding__ask_human",
            "mcp__onboarding__dispatch_workers",
            "mcp__onboarding__kill_worker",
        ],
        mcp_servers={"onboarding": mcp_server},
        permission_mode="default",
        model=orchestrator_model,
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
            ],
            "PostToolUse": [
                HookMatcher(matcher="Bash", hooks=[audit_hook]),
            ],
        },
    )

    loop = asyncio.get_event_loop()

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
                    _save_session(run_id, args, claude_session_id=session_id, branch_name=branch_name)

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
        await mcp_cleanup()


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
    parser.add_argument("--worker-model", default="sonnet", choices=["opus", "sonnet", "haiku"],
                        help="Model for worker agents")
    parser.add_argument("--orchestrator-model", default="opus", choices=["opus", "sonnet", "haiku"],
                        help="Model for the orchestrator agent")
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
        if args.worker_model == "sonnet":  # default wasn't overridden
            args.worker_model = saved["worker_model"]
        if args.orchestrator_model == "opus":  # default wasn't overridden
            args.orchestrator_model = saved.get("orchestrator_model", "opus")
        if not args.instructions and saved.get("instructions"):
            args.instructions = saved["instructions"]
        print(f"Resuming session: {args.resume[:8]}... (run: {args._run_id[:8]})")

    if not args.repo_path:
        print("Error: repo_path is required (provide it or use --resume with a saved session).", file=sys.stderr)
        sys.exit(1)

    asyncio.run(_run_onboarding_async(args))


if __name__ == "__main__":
    main()
