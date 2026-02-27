"""
Minimal integration test for onboarding hook infrastructure.

Spawns a real Claude agent (haiku) with the same hooks as the onboarding
orchestrator, but with a trivial prompt that exercises all hook paths:
  - SubagentStart  (worker tracking + log file creation)
  - PreToolUse     (per-worker logging + Write/Edit gate)
  - PostToolUse    (Bash audit)
  - SubagentStop   (worker completion tracking)

Run:  uv run python tests/test_onboarding_hooks.py
Cost: ~$0.02 (haiku, few turns)
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


async def run_test():
    from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions, AgentDefinition, HookMatcher
    from ao.onboarding.hooks import guard_hook, audit_hook
    from ao.onboarding.orchestrator import (
        _on_worker_start,
        _on_worker_stop,
        _worker_log_hook,
        _worker_state,
    )

    # Clear nesting guard (SDK spawns Claude Code as subprocess)
    os.environ.pop("CLAUDECODE", None)

    # Use a temp directory as the session folder for logs
    with tempfile.TemporaryDirectory(prefix="ao-hook-test-") as tmpdir:
        test_file = Path(tmpdir) / "test_output.txt"

        # Reset worker state with our temp log dir
        _worker_state.update(
            started=0, completed=0, id_to_num={}, active_workers={},
            num_to_color={}, task_descs={}, color_index=0,
            log_dir=tmpdir,
        )

        # Auto-approve Write/Edit in test mode (skip stdin prompt)
        async def _auto_approve_write(input_data, tool_use_id, context):
            file_path = input_data.get("tool_input", {}).get("file_path", "")
            print(f"  [test] Write/Edit guard fired for: {file_path}")
            return {}  # Auto-approve everything in test

        options = ClaudeAgentOptions(
            system_prompt=(
                "You are a test orchestrator. Your ONLY job is to spawn one worker "
                "using the Task tool with subagent_type 'onboarding-worker'. "
                "The worker's prompt should tell it to: "
                f"1) Read the file /etc/hostname (or any small file), "
                f"2) Write the text 'hello from worker' to {test_file}, "
                f"3) Run `echo done`. "
                "After the worker finishes, say exactly 'test complete' and stop."
            ),
            allowed_tools=["Task", "Read", "Bash"],
            permission_mode="default",
            model="haiku",
            max_turns=20,
            cwd=tmpdir,
            hooks={
                "PreToolUse": [
                    HookMatcher(matcher="Bash", hooks=[guard_hook]),
                    HookMatcher(matcher="Write", hooks=[_auto_approve_write]),
                    HookMatcher(matcher="Edit", hooks=[_auto_approve_write]),
                    HookMatcher(hooks=[_worker_log_hook]),
                ],
                "PostToolUse": [
                    HookMatcher(matcher="Bash", hooks=[audit_hook]),
                ],
                "SubagentStart": [HookMatcher(hooks=[_on_worker_start])],
                "SubagentStop": [HookMatcher(hooks=[_on_worker_stop])],
            },
            agents={
                "onboarding-worker": AgentDefinition(
                    description="Test worker that reads a file, writes a file, and runs a command.",
                    prompt="Do exactly what your briefing says. Nothing more.",
                    tools=["Bash", "Read", "Write"],
                    model="haiku",
                ),
            },
        )

        print(f"\n{'='*60}")
        print(f"Hook Infrastructure Test")
        print(f"Log dir: {tmpdir}")
        print(f"{'='*60}\n")

        async with ClaudeSDKClient(options=options) as client:
            await client.query("Go.")
            async for message in client.receive_response():
                msg_type = type(message).__name__
                if hasattr(message, "content"):
                    if isinstance(message.content, str):
                        print(f"  [{msg_type}] {message.content[:100]}")
                    elif isinstance(message.content, list):
                        for block in message.content:
                            if hasattr(block, "text"):
                                print(f"  [{msg_type}] {block.text[:100]}")
                            elif hasattr(block, "name"):
                                print(f"  [{msg_type}] Tool: {block.name}")
                elif hasattr(message, "is_error"):
                    cost = f"${message.total_cost_usd:.4f}" if message.total_cost_usd else "?"
                    print(f"  [{msg_type}] {message.num_turns} turns, {cost}")

        # === Verify results ===
        print(f"\n{'='*60}")
        print("Results:")
        print(f"{'='*60}")

        # 1. Worker tracking
        print(f"\n  Workers started:   {_worker_state['started']}")
        print(f"  Workers completed: {_worker_state['completed']}")
        assert _worker_state["started"] >= 1, "No workers were started!"
        assert _worker_state["completed"] >= 1, "No workers completed!"

        # 2. Active workers should be empty after completion
        print(f"  Active workers:    {len(_worker_state['active_workers'])} (should be 0)")
        assert len(_worker_state["active_workers"]) == 0, "Workers still active after completion!"

        # 3. Per-worker log file exists and has content
        log_files = list(Path(tmpdir).glob("worker_*.log"))
        print(f"  Log files created: {[f.name for f in log_files]}")
        assert len(log_files) >= 1, "No worker log files created!"

        for lf in log_files:
            content = lf.read_text()
            lines = [l for l in content.strip().split("\n") if l.strip()]
            print(f"\n  --- {lf.name} ({len(lines)} lines) ---")
            for line in lines:
                print(f"    {line}")

            assert len(lines) >= 3, f"{lf.name} has too few lines (expected >= 3: Started + tools + Finished)"
            assert "Started" in lines[0], f"First line should be 'Started', got: {lines[0]}"
            assert "Finished" in lines[-1], f"Last line should be 'Finished', got: {lines[-1]}"

            # Verify no Task entries leaked into worker log
            task_lines = [l for l in lines if "] Task:" in l]
            assert not task_lines, f"Task tool calls should not appear in worker log: {task_lines}"

        print(f"\n{'='*60}")
        print("ALL CHECKS PASSED")
        print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(run_test())
