# Onboarding Agent — Implementation Spec

Automated domain knowledge extraction from past interactions. Invoked via `ao-tool onboard <repo-path>`.

## Goal

Given a repository containing an AI agent and a dataset of past interactions (questions + gold answers), the onboarding agent:

1. Understands the repo: what agent, what data, how to run, how to evaluate
2. Ensures a benchmark exists to measure improvement
3. Partitions the dataset and dispatches parallel sub-agents
4. Each sub-agent runs the agent on its samples, diagnoses failures, and creates lessons via the AO playbook API
5. Each lesson is verified to produce measurable improvement before being kept

## Architecture

```
ao-tool onboard /path/to/ao-beaver
        |
        v
+----------------------------------------------------------+
|                    Orchestrator Agent                      |
|              (claude-agent-sdk query() call)               |
|                                                            |
|  System prompt: phases, responsibilities, tools            |
|  Tools: Read, Glob, Grep, Bash, AskUserQuestion, Task     |
|  Model: opus (needs strong reasoning for repo analysis)    |
|                                                            |
|  Phase 0: Explore repo, understand everything              |
|  Phase 1: Verify benchmark exists (hard gate)              |
|  Phase 2: Validate with human, test run command            |
|  Phase 3: Partition data, spawn sub-agents via Task tool   |
|  Phase 4: Collect results, produce summary                 |
+---------------------------+------------------------------+
                            | spawns N sub-agents via Task tool
                            | each gets a different prompt with its briefing
                            v
+-------------------------+  +-------------------------+
|   onboarding-worker     |  |   onboarding-worker     |  ...
|   (AgentDefinition)     |  |   (AgentDefinition)     |
|                          |  |                          |
|   Tools: Bash, Read,    |  |   Tools: Bash, Read,    |
|     Glob, Grep, Write   |  |     Glob, Grep, Write   |
|   Model: sonnet          |  |   Model: sonnet          |
|                          |  |                          |
|   Per-sample loop:      |  |   Per-sample loop:      |
|   run -> eval -> diag   |  |   run -> eval -> diag   |
|   -> lesson -> verify   |  |   -> lesson -> verify   |
+-------------------------+  +-------------------------+
```

Key constraint from the Agent SDK: **sub-agents cannot spawn their own sub-agents** (no `Task` tool). This is fine — sub-agents only need Bash, file tools, and Write.

## Code Structure

```
src/onboarding/
├── __init__.py
├── orchestrator.py       # run_onboarding() — main entry point
├── prompts.py            # System prompts for orchestrator and worker
├── hooks.py              # Guard hook (blocks dangerous commands) + audit hook
└── README.md             # This spec (or a shorter version)
```

CLI entry point: new `onboard` subcommand in `src/cli/ao_tool.py`.

## CLI Entry Point

Added to `ao_tool.py`:

```python
# In create_parser():
onboard = subparsers.add_parser(
    "onboard",
    help="Run onboarding agent to extract domain knowledge",
    description="Analyze a repository's agent and dataset, run the agent on samples, "
                "diagnose failures, and create lessons automatically.",
)
onboard.add_argument("repo_path", help="Path to the target repository")
onboard.add_argument(
    "--max-parallel", type=int, default=4,
    help="Maximum sub-agents running concurrently (default: 4)",
)
onboard.add_argument(
    "--model", default="sonnet",
    choices=["opus", "sonnet", "haiku"],
    help="Model for sub-agents (default: sonnet). Orchestrator always uses opus.",
)

# In main():
elif args.command == "onboard":
    from ao.onboarding.orchestrator import run_onboarding
    run_onboarding(args)
```

## Orchestrator Implementation

`src/onboarding/orchestrator.py`:

```python
import asyncio
from pathlib import Path
from claude_agent_sdk import query, ClaudeAgentOptions, AgentDefinition, HookMatcher
from ao.onboarding.prompts import ORCHESTRATOR_PROMPT, build_worker_prompt
from ao.onboarding.hooks import guard_hook, audit_hook


def _load_skill_md() -> str:
    """Load the ao SKILL.md for injection into the worker prompt."""
    import ao
    skill_path = Path(ao.__file__).parent.parent / "SKILL.md"
    if skill_path.exists():
        return skill_path.read_text()
    return ""


def run_onboarding(args):
    """Entry point called by ao-tool onboard."""
    asyncio.run(_run_onboarding_async(args))


async def _run_onboarding_async(args):
    repo_path = args.repo_path
    max_parallel = args.max_parallel
    worker_model = args.model

    # Load SKILL.md and build the worker prompt with it
    skill_content = _load_skill_md()
    worker_prompt = build_worker_prompt(skill_content)

    async for message in query(
        prompt=(
            f"Onboard the repository at: {repo_path}\n"
            f"Maximum parallel workers: {max_parallel}.\n"
            f"Follow the phases described in your instructions."
        ),
        options=ClaudeAgentOptions(
            system_prompt=ORCHESTRATOR_PROMPT,
            allowed_tools=["Read", "Glob", "Grep", "Bash", "AskUserQuestion", "Task"],
            permission_mode="bypassPermissions",
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
        # Stream output to terminal
        if hasattr(message, "content") and message.content:
            for block in message.content:
                if hasattr(block, "text"):
                    print(block.text, end="", flush=True)
        if hasattr(message, "result"):
            print(message.result)
```

## Orchestrator Prompt

The orchestrator's system prompt defines its four phases. It is a Claude agent with full access to the target repo.

```
src/onboarding/prompts.py — ORCHESTRATOR_PROMPT
```

```markdown
You are the onboarding orchestrator. Your job is to extract domain knowledge from
a repository containing an AI agent and a dataset of past interactions.

You work in five phases. Complete each phase fully before moving to the next.

## Phase 0: Repository Discovery

Explore the repository thoroughly. You must determine ALL of the following:

1. **Agent**: Where is the agent implemented? What does it do? What LLM does it use?
2. **Dataset**: Where are the past interactions stored? What format (JSON, CSV, folder
   of files, JSONL, SQLite, etc.)? How many samples are there? What fields does each
   sample have? Is there a train/test split?
3. **Gold standard**: Where are the expected/correct answers? What format?
4. **Running**: How do you run the agent on a single sample? What is the exact
   command? What flags, arguments, environment variables are needed? What package
   manager is used (uv, pip, conda)? What timeout is appropriate?
5. **Evaluation**: How do you check if the agent's output is correct for a given
   sample? Is there an existing evaluation script? How does it compare predicted
   vs. gold?
6. **Lessons integration**: Does the agent already query lessons at runtime
   (e.g., via `inject_lesson()`)? Where are lessons injected into the prompt?
   What folder path does it use?

Read READMEs, scripts, configuration files, and code to figure this out.

## Phase 1: Benchmark Gate

You MUST be able to answer this question before proceeding:

> "Given a sample and the agent's output, can I determine programmatically whether
>  the agent succeeded?"

If YES — you have a working evaluation method.

If NO — STOP. Use AskUserQuestion to collaborate with the human. You need to
establish evaluation infrastructure before onboarding can begin. This might mean:
- Writing an evaluation script together
- Agreeing on an LLM-as-judge prompt
- Defining success/failure criteria

Do NOT proceed without a concrete, testable evaluation method.

## Phase 2: Validation with Human

Before spawning workers, you MUST validate your understanding with the human.
Getting this wrong wastes all sub-agent work. Present your findings clearly
using AskUserQuestion and confirm:

1. **Run command**: "I will run the agent using: `<exact command>`. Is this correct?"
   Get the exact command right — flags, timeouts, package manager, module vs script.

2. **Evaluation method**: "I will evaluate by: `<method>`. Is this correct?"
   Confirm how success/failure is determined.

3. **Dataset scope**: "I found N samples in `<path>`. Should I process all of them,
   or a subset? Is there a train/test split I should respect?"

4. **Lessons integration**: "The agent loads lessons from path `<path>` via
   `inject_lesson()`. New lessons should go there. Correct?"
   If the agent doesn't have lesson integration yet, flag this — lessons won't
   have any effect until the agent queries them.

5. **Special considerations**: Present anything unusual you found — custom flags,
   environment setup, caching mechanisms, known issues.

Also: run the agent on ONE sample yourself to verify the command works end-to-end
before spawning workers. If it fails, debug it with the human until it works.

Do NOT proceed to dispatch until the human confirms your plan and you have
verified the command works on at least one sample.

## Phase 3: Data Partitioning & Dispatch

### Chunk Size

Workers produce the best results when they operate on small chunks — typically
5 to 10 samples each. Larger chunks lead to degraded quality as the worker's
context fills up and focus drifts. You decide the exact chunk size based on
the complexity of the task, but keep chunks small.

This means a dataset of 200 samples produces 20-40 workers, not 4.

### Partitioning

The dataset can have any shape. You must figure out how to divide it so that each
worker can independently load and process its assigned chunk. There is no predefined
strategy — devise one based on what you discovered in Phase 0.

Examples of strategies (adapt as needed):
- If it's a JSON array: write N chunk files to a temp directory
- If it's a folder of files: assign file ranges or glob patterns per worker
- If it's a CSV/JSONL: specify line ranges
- If it's a database: specify query filters

### Dispatch (Queued)

You are given a maximum number of parallel workers (from the user's --max-parallel
setting). You must NOT spawn all workers at once. Instead, manage a queue:

1. Spawn the first batch of workers up to the max-parallel limit
   (multiple Task tool calls in one turn)
2. Wait for any workers to complete
3. Spawn the next batch of workers to fill the freed slots
4. Repeat until all chunks have been processed

Each worker gets a briefing as its prompt. The briefing is a best-effort starting
point — workers have agency to adapt if something doesn't work. Include:

- What the agent does and relevant code locations
- How to load this worker's specific chunk of data
- The exact, validated run command for a single sample
- The exact, validated evaluation method
- How lessons are integrated into the agent (folder path, injection point)
- Any special flags, timeouts, or environment setup
- Any constraints (e.g., train/test split rules)

## Phase 4: Summary

After all workers complete, summarize:
- Total samples processed
- Pass/fail counts before intervention
- Number of lessons created
- Which lessons were created (names and paths)
- Any samples that could not be resolved
```

## Worker Prompt

The worker's system prompt is built dynamically: it combines a static behavior
definition with the ao SKILL.md content (loaded at startup from the ao package).
This gives workers full knowledge of ao-tool commands and patterns.

```
src/onboarding/prompts.py — build_worker_prompt(skill_content)
```

```python
# In prompts.py:

WORKER_BEHAVIOR = """..."""  # The behavior prompt below

def build_worker_prompt(skill_content: str) -> str:
    """Build worker system prompt with ao skill injected."""
    parts = [WORKER_BEHAVIOR]
    if skill_content:
        parts.append(f"\n\n## ao-tool Reference\n\n{skill_content}")
    return "\n".join(parts)
```

The behavior prompt:

```markdown
You are an onboarding worker agent. You receive a briefing describing a chunk of
samples to process from a dataset. Your job is to run an AI agent on each sample,
check if it succeeds, and when it fails, create lessons capturing the missing domain
knowledge.

You have full agency: you can read files, run commands, explore the environment.
If the briefing's instructions don't work exactly as described, debug and fix the
issue yourself. Do not give up — adapt.

## Per-Sample Loop

For each sample in your assigned chunk:

### 1. Run the Agent

Execute the agent on this sample using the run command from your briefing.
This returns JSON with session_id and exit status.

If the command fails, debug it. Check error messages, inspect the script,
try alternative approaches. Fix environment issues if needed.

### 2. Evaluate

Check whether the agent produced the correct output using the evaluation
method from your briefing.

If the agent succeeded: record this and move to the next sample.

### 3. Diagnose Failure

If the agent failed, figure out WHY:

- Inspect the agent's output using ao-tool probe (see ao-tool Reference below)
- Look at specific nodes with --preview first, then drill into relevant keys
- Compare the agent's output to the gold standard
- Read the agent's code to understand its reasoning process
- Determine: is this a domain knowledge gap that a lesson could fix?

Not every failure is a lesson opportunity. Skip if:
- The failure is a code bug (not a knowledge gap)
- The failure is due to model limitations (hallucination, instruction following)
- The failure is random/non-deterministic

### 4. Create Lesson

If you identified a domain knowledge gap, formulate a lesson.

#### Lesson Design Principles

1. **Target the root cause, not the symptom.** Don't describe what the agent got
   wrong — identify WHY it got it wrong. The same root cause often produces
   different symptoms across samples. A lesson that addresses the underlying gap
   fixes an entire class of failures.

2. **Generalize beyond the specific case.** If writing the lesson requires
   including the specific answer, you haven't found the real knowledge gap. A good
   lesson should help with samples you haven't seen yet. Ask: "Would this lesson
   still be useful if the specific details of this sample changed?"

3. **Be minimal and precise.** Include only what's necessary to close the knowledge
   gap. Every extra sentence dilutes the signal and consumes context window. A
   three-line lesson that's sharp is better than a page-long lesson that's thorough.

4. **Make it actionable.** A lesson should change the agent's behavior, not just
   state a fact. It should tell the agent what to do differently in a specific
   category of situations.

5. **Capture knowledge the model can't infer.** Don't teach the model things it
   already knows from pre-training. Focus on domain-specific knowledge that is
   genuinely inaccessible without insider context: proprietary schemas, internal
   conventions, undocumented behavior, business rules, terminology specific to
   this organization or system.

6. **Scope the lesson appropriately.** A lesson should apply to a well-defined set
   of situations. Too broad and it becomes noise in unrelated contexts. Too narrow
   and it only helps one case. Ask: "In which situations should the agent recall
   this knowledge?" — the answer should be a category, not a single instance.

7. **Map ambiguous terminology.** Many failures come from the agent misinterpreting
   domain-specific terms. Good lessons clarify how natural-language concepts map to
   technical specifics in this particular system — whether that's column names, API
   parameters, configuration values, or internal jargon.

8. **Only state what is verified and true.** Never include assumptions, guesses, or
   generalizations you haven't confirmed. A false lesson is worse than no lesson —
   it actively misleads the agent and causes failures that are hard to diagnose.
   Every claim in a lesson should be something you verified against the actual
   system, data, or documentation. If you're not certain, don't include it.

#### Creating the lesson

Use ao-tool to create the lesson (see ao-tool Reference below for full syntax):

    ao-tool playbook lessons create \
        --name "..." --summary "..." --content "..." --path "..."

You decide the path based on the nature of the knowledge.

Handle the response:
- **Rejected**: The validator found issues. Read the rejection reason carefully.
  Revise your lesson and retry. Common issues: too vague, conflicts with existing
  lesson, content not actionable.
- **Accepted with validation feedback**: The lesson was created but the validator
  has suggestions. ALWAYS take validator feedback seriously — if the feedback is
  valid, update the lesson even if it wasn't rejected. Use ao-tool to update.
- **Accepted clean**: Proceed to verification.
- **Waiting (lock held)**: Another worker is creating/updating a lesson in the
  same folder. This is handled automatically — the command will wait and eventually
  complete. Be patient.

### 5. Verify Improvement

After creating a lesson, you MUST verify it has a positive impact. Re-run the
agent on the same sample and evaluate again.

A lesson does NOT need to make the sample fully pass. Any measurable improvement
counts as a valid lesson:
- The sample now passes (best case)
- An accuracy or coverage metric improved
- The agent's output is closer to the gold standard (e.g., partially correct
  where it was completely wrong before)
- A specific sub-problem is now solved (e.g., the agent now retrieves the right
  document, selects the right table, calls the correct API — even if the final
  answer is still wrong)
- The agent's reasoning improved (e.g., it now considers the right factors even
  if it reaches the wrong conclusion)

The key question is: "Did the lesson improve the agent's behavior in any
observable way?" If yes, keep it. If the output is identical or worse:
  - Try refining the lesson (update it with better content)
  - Re-verify after the update
  - If after 2 refinement attempts there is no observable improvement: delete
    the lesson and move on. Not every failure can be fixed with a lesson.

### 6. Regression Check

After creating or updating a lesson, re-run any previously passing samples from
your chunk to verify they still pass. Lessons can have unintended side effects —
a lesson that fixes one sample but breaks another is not a net positive.

If a regression is detected:
- The new lesson may be too broad or conflicting with existing knowledge
- Refine the lesson to be more specific
- If the conflict can't be resolved, delete the lesson

### Output

After processing all samples, report:
- How many samples were processed
- How many passed initially (before any lessons)
- How many were fixed by lessons
- How many regressed (and whether regressions were resolved)
- How many could not be resolved
- List of lessons created (id, name, path)
- Any issues encountered
```

## How It Fits Together

### Execution Flow

```
1. User runs: ao-tool onboard /path/to/ao-beaver --max-parallel 4

2. orchestrator.py starts a query() with the orchestrator prompt.
   Worker prompt includes SKILL.md loaded from ao package.
   Working directory is set to /path/to/ao-beaver.

3. Orchestrator (Phase 0): reads README, scripts, data files
   Discovers: "This is a text-to-SQL agent using Claude. Dataset is in
   data/mini_dev_sqlite.json (200 samples). Agent runs via:
   uv run ao-tool record -m benchmark_runner -- --sample_id=X --timeout 300.
   Gold standard in data/mini_dev_sqlite_gold.sql. Lessons are loaded via
   inject_lesson(path='beaver/') in src/ao_beaver/sql_agent.py.
   There's a train/test split in data/test-train-split.json."

4. Orchestrator (Phase 1): confirms evaluation exists
   "benchmark_runner.py compares SQL query results. Exit code 0 = pass."

5. Orchestrator (Phase 2): validates with human via AskUserQuestion
   "I plan to run the agent using:
     uv run ao-tool record -m benchmark_runner -- --sample_id={id} --timeout 300
   Is this correct?"
   Human confirms (or corrects).

   "I found 200 samples with a train/test split. I'll process only the 150
   train samples. Correct?"
   Human confirms.

   Orchestrator runs one sample to verify the command works end-to-end.
   If it fails, debugs with the human until it works.

6. Orchestrator (Phase 3): partitions data into small chunks (e.g., 8 samples each)
   150 train samples / 8 = 19 chunks → 19 workers total
   Writes 19 chunk files to /tmp/ao-onboard-chunks/

   Dispatches in waves (max-parallel = 4):

   Wave 1: Spawns 4 Task tool calls in parallel (chunks 0-3)
   Task(
     subagent_type="onboarding-worker",
     description="Process train samples 0-7",
     prompt="""
       BRIEFING:
       You are working on a text-to-SQL agent in /path/to/ao-beaver.
       Agent code: src/ao_beaver/sql_agent.py
       Lessons are injected via inject_lesson(path='beaver/') in sql_agent.py
       Your data: /tmp/ao-onboard-chunks/chunk_0.json (8 train samples)
       Each sample has fields: question, evidence, db_id, SQL (gold)

       Run command (verified working):
         uv run ao-tool record -m benchmark_runner -- --sample_id={sample_id} --timeout 300

       Evaluate: exit code 0 means pass, non-zero means fail.
       Gold SQL: data/mini_dev_sqlite_gold.sql (line N = sample N)
       Database files: data/dev_databases/{db_id}/{db_id}.sqlite

       CONSTRAINT: Only use train samples for lesson creation.
     """
   )

   Wave 2: When wave 1 workers complete, spawns next batch (chunks 4-7)
   Wave 3: ...and so on until all 19 chunks are processed

7. Workers process samples independently
   Each worker:
   - Loads its chunk file
   - Runs the agent per sample
   - Diagnoses failures using ao-tool probe
   - Creates/verifies lessons via ao-tool playbook commands
   - Checks for regressions on previously passing samples

8. Orchestrator (Phase 4): collects reports from all 19 workers
   Prints summary to terminal.
```

### ao-tool Commands Used by Workers

```bash
# Run the agent on a sample
python -m ao.cli.ao_tool record workflow/main.py --sample_id=5

# Inspect the session
python -m ao.cli.ao_tool probe <session_id>

# Inspect a specific node's output
python -m ao.cli.ao_tool probe <session_id> --node <node_id> --output

# Create a lesson
python -m ao.cli.ao_tool playbook lessons create \
    --name "Table aliases in BIRD benchmark" \
    --summary "Database X uses non-standard column naming" \
    --content "When querying database X, note that the revenue column..." \
    --path "bird-bench/schema-quirks/"

# Update a lesson after validator feedback
python -m ao.cli.ao_tool playbook lessons update <lesson_id> \
    --content "Revised content..."

# Delete a lesson that didn't help
python -m ao.cli.ao_tool playbook lessons delete <lesson_id>

# List existing lessons (to check for conflicts before creating)
python -m ao.cli.ao_tool playbook lessons ls "bird-bench/"
```

### Playbook Server Locking

When a worker calls `ao-tool playbook lessons create`, the playbook server
acquires a hierarchical lock on the target folder. If another worker is already
writing to the same folder, the command blocks and prints "Waiting for lock..."
to stderr. This is handled transparently via SSE — the worker's Bash command
simply takes longer to complete. No special handling needed in the worker prompt
or code.

### Lesson Validator Feedback Loop

The playbook server validates lessons using an LLM before accepting them.
The `ao-tool playbook lessons create` command returns JSON with one of:

```json
{"status": "success", "lesson": {...}}
```
```json
{"status": "success", "lesson": {...}, "validation": {"feedback": "Consider being more specific about..."}}
```
```json
{"status": "rejected", "reason": "This conflicts with existing lesson X", "hint": "..."}
```

The worker parses this JSON output and acts accordingly (revise, update, or
move on). The worker prompt instructs it to handle all three cases.

## Permissions & Sandboxing

### Permission Mode: `bypassPermissions`

The onboarding agent uses `bypassPermissions` — all tool calls are auto-approved
with no user prompts. This is necessary because:
- Workers run hundreds of Bash commands autonomously (ao-tool, Python, evaluation)
- The orchestrator needs to read/write files and run commands during discovery
- Any permission prompt would block the entire pipeline

The security boundary is the user explicitly invoking `ao-tool onboard`.

### No Sandbox, Guard Hook Instead

Claude Code's Bash sandbox (`sandbox-exec` on macOS) restricts filesystem and
network access. A path allowlist is not supported by the Agent SDK, and the
onboarding agent needs access outside the project directory:
- `ao-tool` needs `~/.ao/` config dirs, AO server socket, temp files
- `uv run` / `pip` need `~/.cache/uv/`, site-packages
- The target agent may need API keys, network access, arbitrary paths

Instead of sandboxing, we use a **PreToolUse guard hook** that blocks
catastrophic commands while allowing normal operation. This runs on every
Bash command before execution.

```python
# src/onboarding/hooks.py

import os
import re

# Patterns that should never be executed
BLOCKED_PATTERNS = [
    r"rm\s+-[rf]*\s+/\s",        # rm -rf /
    r"rm\s+-[rf]*\s+~",           # rm -rf ~
    r"rm\s+-[rf]*\s+/Users\b",    # rm -rf /Users
    r"rm\s+-[rf]*\s+/home\b",     # rm -rf /home
    r"rm\s+-[rf]*\s+/etc\b",      # rm anything in /etc
    r"rm\s+-[rf]*\s+/var\b",      # rm anything in /var
    r"\bmkfs\b",                   # format filesystem
    r"\bdd\s+if=",                 # raw disk write
    r">\s*/dev/sd",                # overwrite block device
    r"\bchmod\s+-R\s+777\s+/",    # chmod 777 on root paths
    r"\bcurl\b.*\|\s*\bsudo\s+bash",  # pipe curl to sudo bash
]

COMPILED_BLOCKS = [re.compile(p) for p in BLOCKED_PATTERNS]


async def guard_hook(input_data, tool_use_id, context):
    """Block catastrophic Bash commands. Allows everything else."""
    tool_name = input_data.get("tool_name", "")
    if tool_name != "Bash":
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
    tool_name = input_data.get("tool_name", "")
    if tool_name == "Bash":
        command = input_data.get("tool_input", {}).get("command", "")
        log_path = os.environ.get(
            "AO_ONBOARD_AUDIT_LOG", "/tmp/ao-onboard-audit.log"
        )
        with open(log_path, "a") as f:
            from datetime import datetime
            f.write(f"[{datetime.now().isoformat()}] {command}\n")
    return {}
```

Both hooks are wired into the orchestrator's `ClaudeAgentOptions`:

```python
# In orchestrator.py:
from claude_agent_sdk import ClaudeAgentOptions, HookMatcher
from ao.onboarding.hooks import guard_hook, audit_hook

ClaudeAgentOptions(
    permission_mode="bypassPermissions",
    hooks={
        "PreToolUse": [
            HookMatcher(matcher="Bash", hooks=[guard_hook]),
        ],
        "PostToolUse": [
            HookMatcher(matcher="Bash", hooks=[audit_hook]),
        ],
    },
    # ...
)
```

The guard hook blocks commands matching dangerous patterns (deleting system
directories, formatting disks, etc.) while allowing all normal operations
including `rm` within the project. The audit hook logs every Bash command
with a timestamp for post-hoc review.

Sub-agents inherit hooks from the parent, so workers are also protected.

## Agent SDK Tools Reference

| Tool | What it does | Used by |
|------|-------------|---------|
| **Read** | Read any file (code, data, configs, images, PDFs) | Both |
| **Write** | Create new files | Workers (temp scripts, chunk files) |
| **Edit** | Precise string replacement in existing files | — |
| **Bash** | Run any shell command | Both (core tool) |
| **Glob** | Find files by pattern (`**/*.py`) | Both |
| **Grep** | Regex search across file contents | Both |
| **AskUserQuestion** | Ask user with multiple-choice options | Orchestrator only (Phase 1) |
| **Task** | Spawn sub-agents | Orchestrator only |

There is no "run inline Python" tool. Workers execute Python via Bash:

```bash
# Quick inline Python (e.g., debug a SQL query)
python -c "import sqlite3; conn = sqlite3.connect('db.sqlite'); ..."

# Or write and run a temp script for more complex logic
python /tmp/debug_query.py
```

## Design Decisions

### Why Bash for ao-tool instead of custom MCP tools?

Sub-agents call ao-tool via Bash (`python -m ao.cli.ao_tool ...`). This is
simpler than building custom MCP tools because:
- ao-tool already has a complete CLI with JSON output
- No additional code to maintain
- Workers can also run arbitrary commands for debugging
- The Claude agent is good at parsing JSON from command output

Custom MCP tools could be added later for a tighter interface, but Bash
is sufficient and keeps the implementation lean.

### Why opus for orchestrator, sonnet for workers?

The orchestrator needs strong reasoning to analyze an unfamiliar repository,
devise a data partitioning strategy, and generate good briefings. This is a
one-time cost per onboarding run.

Workers do more repetitive work (run, evaluate, diagnose, create lesson) across
many samples. Sonnet is capable enough for this and keeps costs down. The
`--model` flag allows overriding this.

### Why the orchestrator doesn't prescribe lesson paths

The worker is the one who understands the specific failure — what went wrong,
what domain knowledge is missing, and how it should be categorized. Prescribing
a path from the orchestrator would be premature since the orchestrator hasn't
seen the failures yet. Workers independently decide lesson organization based
on the nature of each knowledge gap they discover.

### Why workers must verify improvement

Creating a lesson that sounds right but doesn't actually help is worse than
no lesson (it pollutes the knowledge base). Mandatory verification ensures
every lesson has demonstrated impact. If a lesson doesn't improve the sample
after 2 refinement attempts, it gets deleted.

### Why the benchmark gate is a hard stop

Without a way to measure improvement, the entire feedback loop breaks:
- Workers can't know if the agent succeeded
- Workers can't verify if lessons helped
- The orchestrator can't report meaningful results

The orchestrator must either find existing evaluation infrastructure or
collaborate with the human to build it before proceeding.
