---
name: sovara
description: sovara helps you develop and maintain adaptable agentic systems. It adds context-optimized observability, accelerated A/B testing, and dynamic runtime prior injection. Use when actively developing or improving agentic systems.
---

# sovara

## Overview

- **Integrated Observability** – Record agent traces as dataflow graphs with zero code changes
- **Accelerated A/B Testing** – Edit node inputs/outputs and rerun to see how changes propagate
- **Priors** – Inject learned priors into agent context dynamically at runtime

---

## Setup

1. **Check for caching conflicts**: Scan the user-code for caching mechanisms (such as ad-hoc implementation of LLM-input caching or benchmark caching) that can interfere with the re-run capability. If you encounter such caching, flag this to the user and propose to change it by, for example, being able to disable caching with a `--no-cache` flag. **NOTE:** Caching that happens at the API provider level, for example using `cache_control` in the Anthropic API is OK!

## Integrated Observability

Record agent execution as a graph where nodes are LLM/tool calls and edges are data dependencies.

### Record a script
Run any agent and record the dataflow graph, as well as input/output to each node.

The tool is generally structured like this.

```
usage: so-cli record [-h] [-m] [--run-name RUN_NAME] [--timeout TIMEOUT] script_path ...

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
uv run so-cli record --run-name "OAI-debate-run-1" --timeout 60 example_workflows/debug_examples/openai/debate.py
```

This will return
```json
{
  "status": "completed",
  "run_id": "77772451-2bea-4401-89aa-1b32cb34f688",
  "exit_code": 0,
  "duration_seconds": 16.9
}
```

### Inspect a run
After you ran a script/module you can investigate the input/output of each node (LLM call, tool call) using the `probe` command.

The tool is generally structured like this.

```
usage: so-cli probe [-h] [--node NODE] [--nodes NODES] [--preview] [--input] [--output] [--key-regex KEY_REGEX] run_id

positional arguments:
  run_id            Run ID to probe

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

`run_id`, `--node`, and `--nodes` accept full UUIDs or any unambiguous prefix. Start with the first 8 hex characters; if that is ambiguous, use a longer prefix.

Examples:
To return the metadata, the nodes in the graph, and the graph topology, run
```bash
uv run so-cli probe b6aaf796-8e25-4e9a-aae6-a47f261ced54
```

This will return a structured JSON with the run metadata and the graph information:
```json
{
  "run_id": "b6aaf796-8e25-4e9a-aae6-a47f261ced54",
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

Important: use `--preview` together with `--node` or `--nodes`. Running `probe <run_id> --preview` only shows run topology; it does not show the flattened input/output keys inside a node.

```bash
uv run so-cli probe b6aaf796-8e25-4e9a-aae6-a47f261ced54 --node 00b0e4b8-db1d-4f44-bd5e-23c049c7b8c0 --preview
```

This will produce a preview with flattened keys:
```json
{
  "node_id": "00b0e4b8-db1d-4f44-bd5e-23c049c7b8c0",
  "run_id": "b6aaf796-8e25-4e9a-aae6-a47f261ced54",
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
    "body.messages.0.content": "<sovara-priors>\n## Student...",
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
uv run so-cli probe b6aaf796-8e25-4e9a-aae6-a47f261ced54 --node 00b0e4b8-db1d-4f44-bd5e-23c049c7b8c0 --input --key-regex "body.max_tokens$"
```

This will produce the full result (no preview) of the specific keys that match the regex:
```json
{
  "node_id": "00b0e4b8-db1d-4f44-bd5e-23c049c7b8c0",
  "run_id": "b6aaf796-8e25-4e9a-aae6-a47f261ced54",
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

### List and manage runs
You can manage past runs that you did with the `runs` command, which is structured in the following way

```
usage: so-cli runs [-h] [--range RANGE] [--regex REGEX] [--status {all,running,finished}]

List runs with optional range. Range format: ':50' (first 50), '50:100' (50-99), '10:' (from 10 onwards).

options:
  -h, --help                              show this help message and exit
  --range RANGE                           Range of runs to return (default: ':50'). Format: 'start:end', ':end', 'start:'
  --regex REGEX                           Filter runs by name using regex pattern
  --status {all,running,finished}         Filter runs by runtime status
```

Example:
To list the most recent 2 runs that match a certain regex, I can do

```bash
uv run so-cli runs --range :2 --regex "Run \d+$"
```

which produces

```json
{
  "runs": [
    {
      "run_id": "77772451-2bea-4401-89aa-1b32cb34f688",
      "name": "Run 1023",
      "timestamp": "2026-01-26 09:04:26",
      "result": "",
      "version_date": null
    },
    {
      "run_id": "b5288aae-02ca-4696-89ee-5f4074f4064e",
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
If you want to execute muliple runs in parallel, invoke `so-cli record` separately multiple times. Example:

```bash
for i in 0 1 2 3 4 5 6 7 8 9; do
  uv run so-cli record -m --run-name "sql-agent-sample-$i" module.some_module -- --sample-id $i 2>&1 &
done
wait
```

---

## Accelerated A/B Testing

Copy a run, edit a single key in a node's input or output, and rerun to see how changes propagate through the graph. The original run is always preserved. The command blocks until completion and passes stdout/stderr through to the terminal.

```
usage: so-cli edit-and-rerun [-h] (--input KEY VALUE | --output KEY VALUE) [--timeout TIMEOUT] [--run-name RUN_NAME] run_id node_id

positional arguments:
  run_id            Run ID containing the node
  node_id               Node ID to edit

options:
  --input KEY VALUE     Edit an input key: --input <flat_key> <value_or_file_path>
  --output KEY VALUE    Edit an output key: --output <flat_key> <value_or_file_path>
  --timeout TIMEOUT     Timeout in seconds (terminates script if exceeded)
  --run-name RUN_NAME   Name for the new run (defaults to 'Edit of <original name>')
```

Keys use flattened dot-notation matching the keys from `probe --preview` output (e.g., `body.messages.0.content`, `body.temperature`). The value can be a literal string or a path to an existing file whose contents will be used.

`run_id` and `node_uuid` accept full UUIDs or any unambiguous prefix. Start with the first 8 hex characters; if that is ambiguous, use a longer prefix.

### Workflow

The typical workflow is: **probe** a node to see its flattened keys → **edit-and-rerun** a specific key → **probe** the downstream nodes to verify the effect.

**Step 1:** Probe a node with `--preview` to see available keys:
```bash
uv run so-cli probe 77772451-2bea-4401-89aa-1b32cb34f688 --node ee5643e0 --preview --input
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

**Step 2:** Edit a key and rerun. This creates a new run, applies the edit, and reruns the script — downstream nodes recompute while unchanged nodes return cached results:
```bash
uv run so-cli edit-and-rerun 77772451-2bea-4401-89aa-1b32cb34f688 ee5643e0-04e0-474b-bbc5-2d303d02e273 \
  --input body.input "What is the best programming language?" \
  --run-name "test-new-question"
```
```json
{
  "status": "completed",
  "run_id": "b7df883a-d5f9-4e5a-8743-48dc3536b57c",
  "exit_code": 0,
  "duration_seconds": 18.73,
  "node_id": "ee5643e0-04e0-474b-bbc5-2d303d02e273",
  "edited_field": "input",
  "edited_key": "body.input"
}
```

**Step 3:** Probe downstream nodes in the new run to verify the effect of the change.

If `--key-regex` returns an empty `input` or `output` object, do not guess the field names. Re-run `probe` with `--preview` on that node first and inspect the flattened keys that actually exist for that API call.

### Using file contents as value
For longer edits (e.g., replacing a system prompt), write the new value to a file and pass the path:
```bash
uv run so-cli edit-and-rerun <run_id> <node_id> \
  --input body.messages.0.content /path/to/new_system_prompt.txt
```

### Parallel A/B testing
To test multiple variations of the same input in parallel, launch several `edit-and-rerun` commands concurrently. Each creates its own run copy, so they don't interfere:
```bash
SESSION=77772451-2bea-4401-89aa-1b32cb34f688
NODE=ee5643e0-04e0-474b-bbc5-2d303d02e273

uv run so-cli edit-and-rerun $SESSION $NODE --input body.temperature 0 --run-name "temp-0" &
uv run so-cli edit-and-rerun $SESSION $NODE --input body.temperature 0.5 --run-name "temp-0.5" &
uv run so-cli edit-and-rerun $SESSION $NODE --input body.temperature 1.0 --run-name "temp-1.0" &
wait
```
Then compare results across the three runs using `so-cli probe` and `so-cli runs --regex "temp-"`.

---

## Priors

Priors are small snippets that augment a context at runtime to inform the agent of specifics like company policies, specific domain knowledge, or conventions. Priors are organized in folders (e.g. `beaver/retriever/`) so different parts of an agent system can have their own priors. `so-cli` provides capability to create and manage priors.

### When to use
If injecting additional information that resolves ambiguity, introduces domain knowledge, or specifies company policy, can resolve the issue – construct a prior.
The ideal prior has three properties:

  1. It fixes the problem at hand
  2. generalizes well to other scenarios where the same problem could occur in a slightly different way
  3. and it does not conflict with other existing priors.

Once you have constructed a prior, check if the problem is solved by doing A/B testing. You should inject the prior at any point you see fit, and use the `edit-and-rerun` functionality. If you want to try different versions of the prior, run `edit-and-rerun` in parallel.
Once you verified that the prior addresses the problem, retrieve the available priors, and check if you introduced a conflict with another prior. If so, resolve the conflict by iteratively tuning and running the agent with the adapted priors, until you are satisfied.

### How to use

First, inject priors into the context by modifying the user code.

```python
from sovara.runner.priors import inject_priors

# Inject all priors from a specific folder into a <sovara-priors> block
priors_context = inject_priors(path="beaver/retriever/")

# Prepend to your prompt
prompt = f"{priors_context}\n\n{user_query}" if priors_context else user_query

response = client.messages.create(
    model="claude-sonnet-4-20250514",
    messages=[{"role": "user", "content": prompt}],
)
```

If you want LLM-filtered retrieval instead of loading all priors in a path:

```python
priors_context = inject_priors(
    path="beaver/retriever/",
    context=user_query,
    method="retrieve",
)
```

**Note:** Ignore the warning that `inject_priors` is not available.

### CLI

`so-cli priors` mirrors the public priors API exposed by the main `so-server`.

```
usage: so-cli priors [-h] {start-server,list,get,create,update,delete,query,retrieve,migrate,restructure,ls,mkdir,mv,cp,rm} ...
```

The main commands are:

- `list`: list priors, optionally filtered by `--path`
- `get <prior_id>`: fetch one prior
- `create`: create a prior; supports `--creation-trace-id` and `--trace-source`
- `update <prior_id>`: update `--name`, `--summary`, `--content`, and/or `--path`
- `delete <prior_id>`: delete one prior
- `query`: return all priors in a path plus an injected `<sovara-priors>` block
- `retrieve "<context>"`: use the LLM retriever to select relevant priors
- `migrate`: move root-level priors into the default retrieval folder
- `restructure {propose,execute,abort}`: manage taxonomy restructure proposals
- `ls`, `mkdir`, `mv`, `cp`, `rm`: folder and bulk-prior operations

Examples:

```bash
so-cli priors list --path "beaver/retriever/"
so-cli priors get <prior_id>
so-cli priors create --name "<name>" --summary "<summary>" --content "<content>" --path "beaver/retriever/"
so-cli priors update <prior_id> --content "<new_content>" --path "beaver/validator/"
so-cli priors delete <prior_id>
so-cli priors query --path "beaver/retriever/"
so-cli priors retrieve "Find SQL validation guidance" --path "beaver/"
so-cli priors migrate
so-cli priors restructure propose --path "beaver/" --comments "Group priors by subsystem" > proposal.json
so-cli priors restructure execute --proposal-file proposal.json
so-cli priors restructure abort <task_id>
so-cli priors ls beaver/
so-cli priors mv -i abc123,def456 beaver/dest/
so-cli priors cp beaver/retriever/ beaver/retriever-backup/
so-cli priors rm -r beaver/old/
```

Restructure workflow:

1. Run `so-cli priors restructure propose` to get a proposal with `task_id`, `moves`, `new_folders`, and `snapshot`.
2. Optionally inspect or edit the JSON proposal file.
3. Run `so-cli priors restructure execute --proposal-file proposal.json` to execute it.
4. If you do not want to apply it, run `so-cli priors restructure abort <task_id>` to release the lock.

Representative outputs:

`so-cli priors list` returns a JSON array:

```json
[
  {
    "id": "24d90294",
    "name": "Rate Limiting Best Practices",
    "summary": "How to implement exponential backoff for API rate limits",
    "content": "When dealing with rate limits, implement exponential backoff...",
    "path": "beaver/retriever/"
  }
]
```

`so-cli priors create` returns the server's creation response:

```json
{
  "status": "created",
  "id": "<prior_id>",
  "name": "<name>",
  "summary": "<summary>",
  "content": "<content>",
  "path": "beaver/retriever/"
}
```

`so-cli priors query` returns all priors in a path plus the injected context:

```json
{
  "path": "beaver/retriever/",
  "priors": [
    {
      "id": "<prior_id>",
      "name": "<name>",
      "summary": "<summary>",
      "content": "<content>",
      "path": "beaver/retriever/"
    }
  ],
  "injected_context": "<sovara-priors>\n<!-- {\"priors\":[{\"id\":\"<prior_id>\"}]} -->\n## <name>\n<content>\n</sovara-priors>"
}
```

`so-cli priors retrieve` returns the retriever result:

```json
{
  "context": "Find SQL validation guidance",
  "base_path": "beaver/",
  "priors": [
    {
      "id": "<prior_id>",
      "name": "<name>",
      "summary": "<summary>",
      "content": "<content>",
      "path": "beaver/validator/"
    }
  ],
  "prior_count": 1
}
```

`so-cli priors restructure propose` returns a proposal you can review or edit:

```json
{
  "task_id": "<task_id>",
  "summary": "<summary>",
  "new_folders": ["beaver/validator/"],
  "removed_folders": [],
  "moves": [
    {
      "prior_id": "<prior_id>",
      "current_path": "beaver/",
      "new_path": "beaver/validator/",
      "reason": "<reason>"
    }
  ],
  "redundant_prior_ids": [],
  "total_priors": 4,
  "snapshot": "<snapshot>"
}
```

`so-cli priors ls` returns folder metadata plus child priors:

```json
{
  "path": "beaver/",
  "folders": [
    {
      "path": "beaver/retriever/",
      "prior_count": 3
    }
  ],
  "priors": [
    {
      "id": "abc123",
      "name": "Some Prior",
      "summary": "...",
      "content": "...",
      "path": "beaver/"
    }
  ],
  "prior_count": 4
}
```

`mkdir`, `mv`, `cp`, `rm`, `delete`, and `migrate` return status objects shaped like the SovaraDB API, for example:

```json
{
  "status": "moved",
  "dst": "beaver/dest/",
  "moved_count": 2
}
```

---

## Troubleshooting

### Sandboxed / restricted filesystem

**Problem:** You are running inside a sandboxed environment and Sovara commands fail because they try to write under `~/.sovara`, `~/.cache`, or Python cache locations.

**Solution:** Redirect all writable runtime state into `/tmp` before invoking the CLI:

```bash
export SOVARA_HOME=/tmp/sovara-home
export SOVARA_CACHE=/tmp/sovara-cache
export SOVARA_GIT_DIR=/tmp/sovara-git
export UV_CACHE_DIR=/tmp/uv-cache
export PYTHONPYCACHEPREFIX=/tmp/pycache
```

This is the most important variable:

- `SOVARA_HOME=/tmp/sovara-home`

because it moves the default config, DB, and logs out of `~/.sovara`. The other variables avoid cache writes outside the sandbox's writable area.

**Important limitation:** this only fixes filesystem permission issues. If the sandbox also forbids binding a localhost port, server-backed commands like `runs`, `probe`, and `edit-and-rerun` may still fail until Sovara supports a no-daemon / in-process CLI transport.

### Priors server not reachable

**Problem:** `so-cli priors ...` fails because the main Sovara server cannot be reached.

**Check:** Confirm the main Sovara server is running and that `PRIORS_SERVER_URL` points at the correct host. If you set `PRIORS_SERVER_URL` in your shell config, remember that non-interactive shells may not load files like `~/.zshrc`.

**Solution:** Put your `PRIORS_SERVER_URL` export in a file that is sourced for all shell invocations:

| OS | Recommended location |
|-----|----------------------|
| macOS (zsh) | `~/.zshenv` |
| Linux (zsh) | `~/.zshenv` |
| Linux (bash) | `~/.bashrc` or `~/.profile` |
| Windows | System Environment Variables (GUI or `[System.Environment]::SetEnvironmentVariable("PRIORS_SERVER_URL", "http://your-host:5959", "User")` in PowerShell) |

After making this change, restart your agent shell/session for the new environment to take effect.

---

- You executed a code using  `uv run so-cli --help`
but you get: `error: Failed to spawn: so-cli` &rarr; You need to add sovara to your `uv` dependencies.

- You executed `so-cli record some_script.py` and a module is not found &rarr; You need to add the module to your virtual environment.

---

## Feedback

When you are using this tool and you encounter an issue (a command that should work didn't), propose opening an issue at [github.com/SovaraLabs/sovara](https://github.com/SovaraLabs/sovara) or emailing `support@sovara-labs.com`. Propose the exact, nicely formatted text the user should use.
