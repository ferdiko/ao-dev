"""
Guard and audit hooks for the onboarding agent.

The guard hook blocks catastrophic Bash commands (rm -rf /, mkfs, etc.)
while allowing all normal operations. The audit hook logs every Bash
command with a timestamp for post-hoc review.
"""

import os
import re
from datetime import datetime

# Patterns that should never be executed
BLOCKED_PATTERNS = [
    r"rm\s+-[rf]*\s+/\s",
    r"rm\s+-[rf]*\s+~",
    r"rm\s+-[rf]*\s+/Users\b",
    r"rm\s+-[rf]*\s+/home\b",
    r"rm\s+-[rf]*\s+/etc\b",
    r"rm\s+-[rf]*\s+/var\b",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r">\s*/dev/sd",
    r"\bchmod\s+-R\s+777\s+/",
    r"\bcurl\b.*\|\s*\bsudo\s+bash",
]

COMPILED_BLOCKS = [re.compile(p) for p in BLOCKED_PATTERNS]


async def guard_hook(input_data, tool_use_id, context):
    """Block catastrophic Bash commands. Allows everything else."""
    if input_data.get("tool_name") != "Bash":
        return {}

    command = input_data.get("tool_input", {}).get("command", "")

    for pattern in COMPILED_BLOCKS:
        if pattern.search(command):
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        f"Blocked by onboarding guard: command matches "
                        f"dangerous pattern '{pattern.pattern}'"
                    ),
                }
            }

    return {}


async def audit_hook(input_data, tool_use_id, context):
    """Log all Bash commands to an audit file for post-hoc review."""
    if input_data.get("tool_name") == "Bash":
        command = input_data.get("tool_input", {}).get("command", "")
        log_path = os.environ.get(
            "AO_ONBOARD_AUDIT_LOG", "/tmp/ao-onboard-audit.log"
        )
        with open(log_path, "a") as f:
            f.write(f"[{datetime.now().isoformat()}] {command}\n")
    return {}
