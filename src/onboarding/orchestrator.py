"""
Onboarding agent orchestrator.

Entry point for `ao-tool onboard <repo-path>`. Uses the Claude Agent SDK
to run an orchestrator agent that explores a repository, validates its
understanding with the human, and dispatches worker sub-agents to process
dataset samples and create lessons.
"""

import asyncio
import os
import sys
from pathlib import Path

from ao.onboarding.prompts import ORCHESTRATOR_PROMPT, build_worker_prompt
from ao.onboarding.hooks import guard_hook, audit_hook


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
                print(block.text, flush=True)
            elif hasattr(block, "name"):
                # ToolUseBlock
                tool_input = block.input
                if block.name == "Bash":
                    cmd = tool_input.get("command", "")
                    print(f"\n--- Bash: {_truncate(cmd, 300)} ---", flush=True)
                elif block.name == "Task":
                    desc = tool_input.get("description", "")
                    print(f"\n--- Task: {desc} ---", flush=True)
                elif block.name == "Read":
                    print(f"\n--- Read: {tool_input.get('file_path', '?')} ---", flush=True)
                elif block.name in ("Glob", "Grep"):
                    pattern = tool_input.get("pattern", "")
                    print(f"\n--- {block.name}: {pattern} ---", flush=True)
                elif block.name == "Write":
                    print(f"\n--- Write: {tool_input.get('file_path', '?')} ---", flush=True)
                elif block.name == "Edit":
                    print(f"\n--- Edit: {tool_input.get('file_path', '?')} ---", flush=True)
                elif block.name == "AskUserQuestion":
                    questions = tool_input.get("questions", [])
                    for q in questions:
                        print(f"\n--- Question: {q.get('question', '?')} ---", flush=True)
                else:
                    print(f"\n--- {block.name} ---", flush=True)
            elif hasattr(block, "tool_use_id"):
                # ToolResultBlock
                content = block.content
                is_error = block.is_error
                if is_error:
                    print(f"  [error] {_truncate(str(content))}", flush=True)
                elif content:
                    print(f"  [result] {_truncate(str(content))}", flush=True)

    elif isinstance(message, UserMessage):
        # Tool results come back as UserMessages
        if isinstance(message.content, list):
            for block in message.content:
                if hasattr(block, "tool_use_id") and block.content:
                    is_err = getattr(block, "is_error", False)
                    prefix = "[error]" if is_err else "[result]"
                    print(f"  {prefix} {_truncate(str(block.content))}", flush=True)

    elif isinstance(message, ResultMessage):
        cost = f"${message.total_cost_usd:.2f}" if message.total_cost_usd else "?"
        print(
            f"\n=== Done: {message.num_turns} turns, "
            f"{message.duration_ms / 1000:.1f}s, cost {cost} ===",
            flush=True,
        )

    elif isinstance(message, SystemMessage):
        if message.subtype not in ("init",):
            print(f"  [system: {message.subtype}]", flush=True)


def run_onboarding(args):
    """Entry point called by ao-tool onboard."""
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
    asyncio.run(_run_onboarding_async(args))


async def _run_onboarding_async(args):
    from claude_agent_sdk import query, ClaudeAgentOptions, AgentDefinition, HookMatcher

    # Agent SDK spawns Claude Code as subprocess; clear nesting guard
    os.environ.pop("CLAUDECODE", None)

    repo_path = str(Path(args.repo_path).resolve())
    max_parallel = args.max_parallel
    worker_model = args.model

    # Load SKILL.md and build the worker prompt with it
    skill_content = _load_skill_md()
    worker_prompt = build_worker_prompt(skill_content)

    prompt_parts = [
        f"Onboard the repository at: {repo_path}",
        f"Maximum parallel workers: {max_parallel}.",
        "Follow the phases described in your instructions.",
    ]
    if getattr(args, "instructions", None):
        prompt_parts.append(f"\nAdditional instructions:\n{args.instructions}")

    prompt_text = "\n".join(prompt_parts)

    async def prompt_stream():
        """AsyncIterable prompt that stays alive to keep stdin open for hooks.

        The SDK's stream_input() closes stdin once this generator returns.
        By blocking after yielding the prompt, stdin stays open and hook
        callbacks work for the entire session. The SDK's task group
        cancellation cleans this up when the session ends.
        """
        yield {
            "type": "user",
            "session_id": "",
            "message": {"role": "user", "content": prompt_text},
            "parent_tool_use_id": None,
        }
        await asyncio.Event().wait()  # Block until cancelled

    async for message in query(
        prompt=prompt_stream(),
        options=ClaudeAgentOptions(
            system_prompt=ORCHESTRATOR_PROMPT,
            allowed_tools=[
                "Read",
                "Glob",
                "Grep",
                "Bash",
                "AskUserQuestion",
                "Task",
            ],
            permission_mode="bypassPermissions",
            model="opus",
            cwd=repo_path,
            hooks={
                "PreToolUse": [
                    HookMatcher(matcher="Bash", hooks=[guard_hook]),
                ],
                "PostToolUse": [
                    HookMatcher(matcher="Bash", hooks=[audit_hook]),
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
        ),
    ):
        _print_message(message)
