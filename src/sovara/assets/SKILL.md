---
name: sovara
description: sovara helps you develop and maintain adaptable agentic systems. It extends Claude Code with context-optimized observability, accelerated A/B testing, and dynamic runtime lesson injection. Use when actively developing or improving agentic systems.
---

# sovara

## Overview

- **Integrated Observability** – Record agent traces as dataflow graphs with zero code changes
- **Accelerated A/B Testing** – Edit node inputs/outputs and rerun to see how changes propagate
- **Lessons** – Inject learned lessons into agent context dynamically at runtime

---

## Setup

1. **Check for caching conflicts**: Scan the user-code for caching mechanisms (such as ad-hoc implementation of LLM-input caching or benchmark caching) that can interfere with the re-run capability. If you encounter such caching, flag this to the user and propose to change it by, for example, being able to disable caching with a `--no-cache` flag. **NOTE:** Caching that happens at the API provider level, for example using `cache_control` in the Anthropic API is OK!

## Integrated Observability

Record agent execution as a graph where nodes are LLM/tool calls and edges are data dependencies.

### Record a script
Run any agent and record the dataflow graph, as well as input/output to each node.

The tool is generally structured like this.

```
usage: so-tool record [-h] [-m] [--run-name RUN_NAME] [--timeout TIMEOUT] script_path ...

positional arguments:
  script_path          Script to execute (or module name with -m)
  script_args          Arguments to pass to the script

options:
  -h, --help           show this help message and exit
  -m, --module         Run script_path as a Python module (like python -m)
  --run-name RUN_NAME  Human-readable name for this run
  --timeout TIMEOUT    Timeout in seconds (terminates script if exceeded)
```

Example:

```bash
uv run so-tool record --run-name "OAI-debate-run-1" --timeout 60 example_workflows/debug_examples/openai/debate.py
```

This will return
```json
{
  "status": "completed",
  "session_id": "77772451-2bea-4401-89aa-1b32cb34f688",
  "exit_code": 0,
  "duration_seconds": 16.9
}
```

### Inspect a session
After you ran a script/module you can investigate the input/output of each node (LLM call, tool call) using the `probe` command.

The tool is generally structured like this.

```
usage: so-tool probe [-h] [--node NODE] [--nodes NODES] [--preview] [--input] [--output] [--key-regex KEY_REGEX] session_id

positional arguments:
  session_id            Session ID to probe

options:
  -h, --help            show this help message and exit
  --node NODE           Return detailed info for a single node
  --nodes NODES         Return detailed info for multiple nodes (comma-separated IDs)
  --preview             Truncate string values to 20 characters for a compact overview
  --input               Only show input content (omit output)
  --output              Only show output content (omit input)
  --key-regex KEY_REGEX
                        Filter keys using regex pattern on flattened keys (e.g., 'messages.*content'). Lists use index notation: content.0.hello
```

Examples:
To return the metadata, the nodes in the graph, and the graph topology, run
```bash
uv run so-tool probe b6aaf796-8e25-4e9a-aae6-a47f261ced54
```

This will return a structured JSON with the run metadata and the graph information:
```json
{
  "session_id": "b6aaf796-8e25-4e9a-aae6-a47f261ced54",
  "name": "bench-train-9",
  "status": "finished",
  "timestamp": "2026-01-25 17:55:42.100729",
  "result": "Satisfactory",
  "version_date": null,
  "node_count": 3,
  "nodes": [
    {
      "node_id": "229386ef-fa49-4505-a28a-0049c2a5eb3e",
      "label": "Claude Sonnet 4.5",
      "parent_ids": [],
      "child_ids": []
    },
    <other two nodes omitted>
  ],
  "edges": [
    {
      "source": "00b0e4b8-db1d-4f44-bd5e-23c049c7b8c0",
      "target": "264d1f3e-8799-4752-b707-a4202af21340"
    }
  ]
}
```

Then, after having found the graph topology and the node IDs, you can investigate a node in more detail, but make sure to use preview to not spam your context with unnecessary tokens.

```bash
uv run so-tool probe b6aaf796-8e25-4e9a-aae6-a47f261ced54 --node 00b0e4b8-db1d-4f44-bd5e-23c049c7b8c0 --preview
```

This will produce a preview with flattened keys:
```json
{
  "node_id": "00b0e4b8-db1d-4f44-bd5e-23c049c7b8c0",
  "session_id": "b6aaf796-8e25-4e9a-aae6-a47f261ced54",
  "api_type": "httpx.Client.send",
  "label": null,
  "timestamp": "2026-01-25 16:56:25",
  "parent_ids": [],
  "child_ids": [
    "264d1f3e-8799-4752-b707-a4202af21340"
  ],
  "has_input_overwrite": false,
  "stack_trace": [
    "File \"/Users/jub/sovara-beaver/benchmark_runner.py\", line 104, in <module>",
    "evaluate_sample(args.sample_id, max_turns=args.max_turns)",
    "File \"/Users/jub/sovara-beaver/benchmark_runner.py\", line 32, in evaluate_sample",
    "result = run_sql_agent(question, max_turns=max_turns)",
    "File \"/Users/jub/sovara-beaver/src/ao_beaver/sql_agent.py\", line 89, in run_sql_agent",
    "response = client.beta.messages.parse(",
    "File \"/Users/jub/sovara-beaver/.venv/lib/python3.13/site-packages/anthropic/resources/beta/messages/messages.py\", line 1141, in parse",
    "return self._post(",
    "File \"/Users/jub/sovara-beaver/.venv/lib/python3.13/site-packages/anthropic/_base_client.py\", line 1361, in post",
    "return cast(ResponseT, self.request(cast_to, opts, stream=stream, stream_cls=stream_cls))",
    "File \"/Users/jub/sovara-beaver/.venv/lib/python3.13/site-packages/anthropic/_base_client.py\", line 1069, in request",
    "response = self._client.send("
  ],
  "input": {
    "body.max_tokens": 8000,
    "body.messages.0.content": "<lessons>\n## Student...",
    "body.thinking.budget_tokens": 4000,
    "body.thinking.type": "enabled",
    "url": "https://api.anthropi..."
  },
  "output": {
    "content.content.0.thinking": "The user is asking f...",
    "content.content.1.text": "{\"sql_query\": \"SELEC...",
    "content.role": "assistant",
    "content.stop_reason": "end_turn"
  }
}
```

If you then want to investigate a specific key of the input or output (or both) you can do so by passing a `--key-regex` like so

```bash
uv run so-tool probe b6aaf796-8e25-4e9a-aae6-a47f261ced54 --node 00b0e4b8-db1d-4f44-bd5e-23c049c7b8c0 --input --key-regex "body.max_tokens$"
```

This will produce the full result (no preview) of the specific keys that match the regex:
```json
{
  "node_id": "00b0e4b8-db1d-4f44-bd5e-23c049c7b8c0",
  "session_id": "b6aaf796-8e25-4e9a-aae6-a47f261ced54",
  "api_type": "httpx.Client.send",
  "label": null,
  "timestamp": "2026-01-25 16:56:25",
  "parent_ids": [],
  "child_ids": [
    "264d1f3e-8799-4752-b707-a4202af21340"
  ],
  "has_input_overwrite": false,
  "stack_trace": [
    "File \"<frozen runpy>\", line 198, in _run_module_as_main",
    "File \"<frozen runpy>\", line 88, in _run_code",
    "File \"<frozen runpy>\", line 229, in run_module",
    "File \"<frozen runpy>\", line 88, in _run_code",
    "File \"/Users/jub/sovara-beaver/benchmark_runner.py\", line 104, in <module>",
    "evaluate_sample(args.sample_id, max_turns=args.max_turns)",
    "File \"/Users/jub/sovara-beaver/benchmark_runner.py\", line 32, in evaluate_sample",
    "result = run_sql_agent(question, max_turns=max_turns)",
    "File \"/Users/jub/sovara-beaver/src/ao_beaver/sql_agent.py\", line 89, in run_sql_agent",
    "response = client.beta.messages.parse(",
    "File \"/Users/jub/sovara-beaver/.venv/lib/python3.13/site-packages/anthropic/resources/beta/messages/messages.py\", line 1141, in parse",
    "return self._post(",
    "File \"/Users/jub/sovara-beaver/.venv/lib/python3.13/site-packages/anthropic/_base_client.py\", line 1361, in post",
    "return cast(ResponseT, self.request(cast_to, opts, stream=stream, stream_cls=stream_cls))",
    "File \"/Users/jub/sovara-beaver/.venv/lib/python3.13/site-packages/anthropic/_base_client.py\", line 1069, in request",
    "response = self._client.send("
  ],
  "input": {
    "body.max_tokens": 8000
  }
}
```

### List and manage experiments
You can manage past runs that you did with the `experiments` command, which is structured in the following way

```
usage: so-tool experiments [-h] [--range RANGE] [--regex REGEX]

List experiments with optional range. Range format: ':50' (first 50), '50:100' (50-99), '10:' (from 10 onwards).

options:
  -h, --help     show this help message and exit
  --range RANGE  Range of experiments to return (default: ':50'). Format: 'start:end', ':end', 'start:'
  --regex REGEX  Filter experiments by name using regex pattern
```

Example:
To list the most recent 2 experiments that match a certain regex, I can do

```bash
uv run so-tool experiments --range :2 --regex "Run \d+$"
```

which produces

```json
{
  "experiments": [
    {
      "session_id": "77772451-2bea-4401-89aa-1b32cb34f688",
      "name": "Run 1023",
      "timestamp": "2026-01-26 09:04:26",
      "result": "",
      "version_date": null
    },
    {
      "session_id": "b5288aae-02ca-4696-89ee-5f4074f4064e",
      "name": "Run 1022",
      "timestamp": "2026-01-26 08:39:28",
      "result": "",
      "version_date": null
    }
  ],
  "total": 1023,
  "range": "0:2"
}
```

### Parallel execution
If you want to execute muliple runs in parallel, invoke `so-tool record` separately multiple times. Example:

```bash
for i in 0 1 2 3 4 5 6 7 8 9; do
  uv run so-tool record -m --run-name "sql-agent-sample-$i" module.some_module -- --sample-id $i 2>&1 &
done
wait
```

---

## Accelerated A/B Testing

Copy a session, edit a single key in a node's input or output, and rerun to see how changes propagate through the graph. The original session is always preserved. The command blocks until completion and passes stdout/stderr through to the terminal.

```
usage: so-tool edit-and-rerun [-h] (--input KEY VALUE | --output KEY VALUE) [--timeout TIMEOUT] [--run-name RUN_NAME] session_id node_id

positional arguments:
  session_id            Session ID containing the node
  node_id               Node ID to edit

options:
  --input KEY VALUE     Edit an input key: --input <flat_key> <value_or_file_path>
  --output KEY VALUE    Edit an output key: --output <flat_key> <value_or_file_path>
  --timeout TIMEOUT     Timeout in seconds (terminates script if exceeded)
  --run-name RUN_NAME   Name for the new run (defaults to 'Edit of <original name>')
```

Keys use flattened dot-notation matching the keys from `probe --preview` output (e.g., `body.messages.0.content`, `body.temperature`). The value can be a literal string or a path to an existing file whose contents will be used.

### Workflow

The typical workflow is: **probe** a node to see its flattened keys → **edit-and-rerun** a specific key → **probe** the downstream nodes to verify the effect.

**Step 1:** Probe a node with `--preview` to see available keys:
```bash
uv run so-tool probe 77772451-2bea-4401-89aa-1b32cb34f688 --node ee5643e0 --preview --input
```
```json
{
  "node_id": "ee5643e0-04e0-474b-bbc5-2d303d02e273",
  "input": {
    "body.input": "Come up with a simpl...",
    "body.model": "gpt-4o-mini",
    "body.temperature": 0,
    "url": "https://api.openai.c..."
  }
}
```

**Step 2:** Edit a key and rerun. This creates a new session, applies the edit, and reruns the script — downstream nodes recompute while unchanged nodes return cached results:
```bash
uv run so-tool edit-and-rerun 77772451-2bea-4401-89aa-1b32cb34f688 ee5643e0-04e0-474b-bbc5-2d303d02e273 \
  --input body.input "What is the best programming language?" \
  --run-name "test-new-question"
```
```json
{
  "status": "completed",
  "session_id": "b7df883a-d5f9-4e5a-8743-48dc3536b57c",
  "exit_code": 0,
  "duration_seconds": 18.73,
  "node_id": "ee5643e0-04e0-474b-bbc5-2d303d02e273",
  "edited_field": "input",
  "edited_key": "body.input"
}
```

**Step 3:** Probe downstream nodes in the new session to verify the effect of the change.

### Using file contents as value
For longer edits (e.g., replacing a system prompt), write the new value to a file and pass the path:
```bash
uv run so-tool edit-and-rerun <session_id> <node_id> \
  --input body.messages.0.content /path/to/new_system_prompt.txt
```

### Parallel A/B testing
To test multiple variations of the same input in parallel, launch several `edit-and-rerun` commands concurrently. Each creates its own session copy, so they don't interfere:
```bash
SESSION=77772451-2bea-4401-89aa-1b32cb34f688
NODE=ee5643e0-04e0-474b-bbc5-2d303d02e273

uv run so-tool edit-and-rerun $SESSION $NODE --input body.temperature 0 --run-name "temp-0" &
uv run so-tool edit-and-rerun $SESSION $NODE --input body.temperature 0.5 --run-name "temp-0.5" &
uv run so-tool edit-and-rerun $SESSION $NODE --input body.temperature 1.0 --run-name "temp-1.0" &
wait
```
Then compare results across the three sessions using `so-tool probe` and `so-tool experiments --regex "temp-"`.

---

## Lessons

Lessons are small snippets that augment a context at runtime to inform the agent of specifics like company policies, specific domain knowledge, or conventions. Lessons are organized in folders (e.g. `beaver/retriever/`) so different parts of an agent system can have their own lessons. `so-tool` provides capability to create and manage lessons.

### When to use
If injecting additional information that resolves ambiguity, introduces domain knowledge, or specifies company policy, can resolve the issue – construct a lesson.
The ideal lesson has three properties:

  1. It fixes the problem at hand
  2. generalizes well to other scenarios where the same problem could occur in a slightly different way
  3. and it does not conflict with other existing lessons.

Once you have constructed a lesson, check if the problem is solved by doing A/B testing. You should inject the lesson at any point you see fit, and use the `edit-and-rerun` functionality. If you want to try different versions of the lesson, run `edit-and-rerun` in parallel.
Once you verified that the lesson addresses the problem, retrieve the available lessons, and check if you introduced a conflict with another lesson. If so, resolve the conflict by iteratively tuning and running the agent with the adapted lessons, until you are satisfied.

### How to use

First, you need to inject the lessons into the context by modifying the user-code.
Example:

```python
from sovara.runner.lessons import inject_lesson

# Inject all lessons from a specific folder into a <lessons> block
lessons_context = inject_lesson(path="beaver/retriever/")

# lessons_context now contains:
# <lessons>
# ## Rate Limiting Best Practices
# When dealing with rate limits, implement exponential backoff...
#
# ## Always Validate SQL
# Before executing generated SQL, validate syntax...
# </lessons>

# Prepend to your prompt
prompt = f"{lessons_context}\n\n{user_query}" if lessons_context else user_query

# Use in your LLM call
response = client.messages.create(
    model="claude-sonnet-4-20250514",
    messages=[{"role": "user", "content": prompt}]
)
```
**Note:** Ignore the warning that `inject_lesson` is not available.

The lessons tool is generally structured like this.

```
usage: so-tool playbook lessons [-h] {list,get,create,update,delete,query,ls,mkdir,mv,cp,rm} ...

CRUD operations and folder management for user lessons.

positional arguments:
  {list,get,create,update,delete,query,ls,mkdir,mv,cp,rm}
    list                List all lessons
    get                 Get a specific lesson
    create              Create a new lesson
    update              Update a lesson
    delete              Delete a lesson
    query               Query lessons by folder path
    ls                  List folder contents
    mkdir               Create an empty folder
    mv                  Move/rename folder or lessons
    cp                  Copy a folder
    rm                  Delete a lesson or folder

options:
  -h, --help            show this help message and exit
```

### List Lessons
List all lessons, optionally filtered by folder path.
```
usage: so-tool playbook lessons list [-h] [--path PATH]

List all lessons with their IDs, names, summaries, and paths.

options:
  --path, -p    Folder path to filter by (e.g. 'beaver/retriever/')
```

Examples:
```bash
so-tool playbook lessons list                              # All lessons
so-tool playbook lessons list --path "beaver/retriever/"   # Only lessons in that folder
```

This returns:
```json
{
  "status": "success",
  "lessons": [
    {
      "id": "24d90294",
      "name": "Rate Limiting Best Practices",
      "summary": "How to implement exponential backoff for API rate limits",
      "path": "beaver/retriever/"
    }
  ]
}
```

### Get Lesson
Retrieve a specific lesson by ID.

```
usage: so-tool playbook lessons get [-h] lesson_id

Get full details of a lesson by its ID.

positional arguments:
  lesson_id   The lesson ID to retrieve
```

This returns:
```json
{
  "status": "success",
  "lesson": {
    "id": "<lesson_id>",
    "name": "<name>",
    "summary": "<summary>",
    "content": "<content in markdown>",
    "path": "<folder path>"
  }
}
```

### Create Lesson
Create a new lesson with a name, summary, content, and folder path.

```
usage: so-tool playbook lessons create [-h] --name NAME --summary SUMMARY --content CONTENT [--path PATH]

options:
  --name, -n      Lesson name (max 200 chars, required)
  --summary, -s   Brief summary (max 1000 chars, required)
  --content, -c   Full lesson content in markdown (required)
  --path, -p      Folder path (e.g. 'beaver/retriever/'). Defaults to root.
```

Example:
```bash
so-tool playbook lessons create \
  --name "<name>" \
  --summary "<summary>" \
  --content "<content>" \
  --path "beaver/retriever/"
```

This returns:
```json
{
  "status": "success",
  "lesson": {
    "id": "<lesson_id>",
    "name": "<name>",
    "summary": "<summary>",
    "content": "<content>",
    "path": "beaver/retriever/"
  }
}
```

### Update Lesson
Update an existing lesson's name, summary, content, or path. At least one field must be provided.

```
usage: so-tool playbook lessons update [-h] [--name NAME] [--summary SUMMARY] [--content CONTENT] lesson_id

positional arguments:
  lesson_id   The lesson ID to update

options:
  --name, -n      New lesson name
  --summary, -s   New summary
  --content, -c   New content
```

Examples:
```bash
so-tool playbook lessons update <lesson_id> --name "<new_name>"
so-tool playbook lessons update <lesson_id> --content "<new_content>"
so-tool playbook lessons update <lesson_id> --name "<name>" --summary "<summary>" --content "<content>"
```

This returns the updated lesson:
```json
{
  "status": "success",
  "lesson": {
    "id": "<lesson_id>",
    "name": "<name>",
    "summary": "<summary>",
    "content": "<content>",
    "path": "<folder path>"
  }
}
```

### Delete Lesson
Delete a lesson by its ID.

```
usage: so-tool playbook lessons delete [-h] lesson_id

positional arguments:
  lesson_id   The lesson ID to delete
```

Example:
```bash
so-tool playbook lessons delete <lesson_id>
```

This returns:
```json
{
  "status": "success",
  "deleted": "<lesson_id>"
}
```

### Query Lessons
Get all lessons in a folder and return them as injectable context (a `<lessons>` block).

```
usage: so-tool playbook lessons query [-h] [--path PATH]

options:
  --path, -p    Folder path to retrieve lessons from (omit for all lessons)
```

Examples:
```bash
so-tool playbook lessons query                              # All lessons
so-tool playbook lessons query --path "beaver/retriever/"   # Lessons in that folder
```

This returns lessons and the formatted injected context:
```json
{
  "status": "success",
  "lessons": [
    {
      "id": "<lesson_id>",
      "name": "<name>",
      "summary": "<summary>",
      "content": "<content>",
      "path": "beaver/retriever/"
    }
  ],
  "injected_context": "<lessons>\n## <name>\n<content>\n</lessons>"
}
```

### Folder Commands

Unix-style commands for organizing lessons into folders.

#### List Folder Contents
List immediate child folders and lessons at a path.

```
usage: so-tool playbook lessons ls [path]

positional arguments:
  path    Folder path to list (default: root)
```

Examples:
```bash
so-tool playbook lessons ls                    # List root
so-tool playbook lessons ls beaver/            # List beaver/ folder
```

Returns:
```json
{
  "status": "success",
  "path": "beaver/",
  "folders": ["retriever/", "validator/"],
  "lessons": [
    {"id": "abc123", "name": "Some Lesson", "summary": "...", "path": "beaver/"}
  ],
  "lesson_count": 1
}
```

#### Create Folder
Create an empty folder.

```
usage: so-tool playbook lessons mkdir path

positional arguments:
  path    Folder path to create (e.g. 'beaver/new-folder/')
```

Example:
```bash
so-tool playbook lessons mkdir beaver/new-folder/
```

#### Move / Rename
Move or rename a folder, or move individual lessons by ID.

```
usage: so-tool playbook lessons mv [-i IDS] paths [paths ...]

positional arguments:
  paths             SRC DST (folder mode) or DST (with -i)

options:
  -i, --ids IDS     Comma-separated lesson IDs to move (lesson mode)
```

Examples:
```bash
so-tool playbook lessons mv beaver/old/ beaver/new/         # Rename/move folder
so-tool playbook lessons mv -i abc123,def456 beaver/dest/   # Move lessons by ID
```

#### Copy Folder
Copy all lessons under a folder to a new destination with new IDs.

```
usage: so-tool playbook lessons cp src dst

positional arguments:
  src    Source folder path
  dst    Destination folder path
```

Example:
```bash
so-tool playbook lessons cp beaver/retriever/ beaver/retriever-backup/
```

#### Delete
Delete a single lesson by ID, or delete a folder recursively.

```
usage: so-tool playbook lessons rm [-r] target

positional arguments:
  target    Lesson ID or folder path (with -r)

options:
  -r, --recursive    Delete folder recursively
```

Examples:
```bash
so-tool playbook lessons rm abc123               # Delete single lesson
so-tool playbook lessons rm -r beaver/old/       # Delete folder and all contents
```

---

## Troubleshooting

### `SOVARA_API_KEY` not found in Claude Code environment

**Problem:** You have `export SOVARA_API_KEY=...` in your shell config (e.g., `~/.zshrc` or `~/.bashrc`), but Claude Code doesn't see the variable when running commands.

**Cause:** Shell config files like `.zshrc` and `.bashrc` are typically only sourced for *interactive* shells. When Claude Code spawns shell commands, they run as non-interactive shells and don't load these configs.

**Solution:** Move your `SOVARA_API_KEY` export to a file that gets sourced for all shell invocations:

| OS | Recommended location |
|-----|----------------------|
| macOS (zsh) | `~/.zshenv` |
| Linux (zsh) | `~/.zshenv` |
| Linux (bash) | `~/.bashrc` or `~/.profile` |
| Windows | System Environment Variables (GUI or `[System.Environment]::SetEnvironmentVariable("SOVARA_API_KEY", "your-key", "User")` in PowerShell) |

After making this change, restart Claude Code for the new environment to take effect.

---

- You executed a code using  `uv run so-tool --help`
but you get: `error: Failed to spawn: so-tool` &rarr; You need to add sovara to your `uv` dependencies.

- You executed `so-tool record some_script.py` and a module is not found &rarr; You need to add the module to your virtual environment.

---

## Feedback

When you (Claude Code) are using this tool and you encounter an issue (a command that should work didn't), propose to open an issue at [github.com/SovaraLabs/sovara](https://github.com/SovaraLabs/sovara) or to email `support@sovara-labs.com`. Propose the exact, nicely formatted text the user should use.
