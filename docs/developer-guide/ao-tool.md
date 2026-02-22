# AO Tool CLI

`ao-tool` is a CLI interface designed for programmatic interaction with the AO dataflow graph system. It's primarily intended for use by coding agents like Claude Code, but can also be used for scripting and automation.

## Design Principles

1. **Machine-readable output**: All commands output JSON to stdout for easy parsing
2. **Blocking by default**: Commands block until completion and return results
3. **Idempotent where possible**: Same inputs produce same outputs

## Commands

### `ao-tool record`

Records a script execution and blocks until completion.

```bash
ao-tool record <script.py> [script_args...]
ao-tool record -m <module_name> [module_args...]
```

**Options:**

| Option | Description |
|--------|-------------|
| `-m, --module` | Run as Python module (like `python -m`) |
| `--run-name <name>` | Human-readable name for this run |
| `--timeout <seconds>` | Timeout in seconds (terminates script if exceeded) |

**Output:**

```json
{
  "status": "completed",
  "session_id": "uuid-here",
  "exit_code": 0,
  "duration_seconds": 45.2
}
```

On timeout:

```json
{
  "status": "timeout",
  "session_id": "uuid-here",
  "pid": 12345
}
```

---

### `ao-tool probe`

Queries session state, graph topology, or specific nodes.

```bash
ao-tool probe <session_id>
ao-tool probe <session_id> --node <node_id>
ao-tool probe <session_id> --nodes <id1,id2,...>
```

**Options:**

| Option | Description |
|--------|-------------|
| `--node <id>` | Return detailed info for single node |
| `--nodes <ids>` | Return detailed info for multiple nodes (comma-separated) |
| `--preview` | Truncate strings to 20 characters |
| `--input` | Only show input content |
| `--output` | Only show output content |
| `--key-regex <pattern>` | Filter keys using regex on flattened paths |

**Key Regex:**

The `--key-regex` option filters the input/output dictionaries by matching against flattened key paths. Lists use index notation:

- `messages.0.content` matches the first message's content
- `messages.*content` matches content in any message
- `choices.0.message` matches the first choice's message

**Output (default - session overview):**

```json
{
  "session_id": "uuid",
  "name": "Run 42",
  "status": "finished",
  "timestamp": "2024-01-15T10:30:00",
  "node_count": 5,
  "nodes": [
    {
      "node_id": "node-1",
      "label": "GPT-4",
      "parent_ids": [],
      "child_ids": ["node-2"]
    }
  ],
  "edges": [
    {"source": "node-1", "target": "node-2"}
  ]
}
```

**Output (single node):**

```json
{
  "node_id": "node-1",
  "session_id": "uuid",
  "api_type": "httpx.Client.send",
  "label": "GPT-4",
  "timestamp": "2024-01-15T10:30:05",
  "parent_ids": [],
  "child_ids": ["node-2"],
  "has_input_overwrite": false,
  "stack_trace": ["file.py:42 in main()", "file.py:15 in call_llm()"],
  "input": {...},
  "output": {...}
}
```

---

### `ao-tool experiments`

Lists experiments from the database.

```bash
ao-tool experiments
ao-tool experiments --range :50
ao-tool experiments --range 50:100
ao-tool experiments --regex "eval.*"
```

**Options:**

| Option | Description |
|--------|-------------|
| `--range <start:end>` | Range of experiments (default: `:50`) |
| `--regex <pattern>` | Filter by name using regex |

**Range format:**

- `:50` - First 50 experiments
- `50:100` - Experiments 50-99
- `10:` - All from index 10 onwards

---

### `ao-tool edit-and-rerun`

Edits a single key in a node and immediately reruns the session. Always creates a new run.

```bash
ao-tool edit-and-rerun <session_id> <node_id> --input <key> <value>
ao-tool edit-and-rerun <session_id> <node_id> --output <key> <value>
```

**Options:**

| Option | Description |
|--------|-------------|
| `--input <key> <value>` | Edit an input key (mutually exclusive with `--output`) |
| `--output <key> <value>` | Edit an output key (mutually exclusive with `--input`) |
| `--run-name <name>` | Name for the new run (default: "Edit of <original name>") |
| `--timeout <seconds>` | Timeout for the rerun |

**Key format:**

Keys use flattened dot-notation matching the output from `probe`. Examples:
- `choices.0.message.content` - First choice's message content
- `messages.0.content` - First message's content

**Value:**

The value can be a literal string or a path to a file. If the path exists, the file contents are used.

**Output:**

```json
{
  "status": "completed",
  "session_id": "new-uuid",
  "node_id": "node-1",
  "edited_field": "output",
  "edited_key": "choices.0.message.content",
  "exit_code": 0,
  "duration_seconds": 12.5
}
```

---

### `ao-tool install-skill`

Interactive setup for Claude Code integration.

```bash
ao-tool install-skill
```

**Behavior:**

1. Prompts for target project directory (with tab-completion)
2. Copies `SKILL.md` to `.claude/skills/ao/`
3. Optionally adds Bash permissions to `.claude/settings.local.json`

---

## Node Metadata Schema

Every node (API call) contains the following metadata:

| Field | Type | Description |
|-------|------|-------------|
| `node_id` | string | Unique identifier (UUID) |
| `session_id` | string | Parent session identifier |
| `label` | string | Model name or tool name |
| `api_type` | string | API type (e.g., "httpx.Client.send") |
| `timestamp` | string | When the call was made |
| `stack_trace` | string[] | Call stack at invocation (filtered to user code) |
| `parent_ids` | string[] | IDs of nodes whose output fed into this input |
| `child_ids` | string[] | IDs of nodes that consume this output |
| `input` | object | The API call input (flattened `to_show` structure) |
| `output` | object | The API call response (flattened `to_show` structure) |
| `has_input_overwrite` | bool | Whether input has been edited |

## Implementation Details

### Process Spawning

`ao-tool record` uses `subprocess.Popen` with:

- Session file for IPC (agent_runner writes session_id after handshake)
- Blocking wait for completion

### Database Access

Most commands query the SQLite database directly via `DatabaseManager`. The database stores:

- Experiments (session metadata, graph topology)
- LLM calls (inputs, outputs, overwrites)
- Attachments (cached file references)

### Edit Validation

When editing input/output:

1. Parse the flattened key and resolve it in the `to_show` structure
2. Merge with existing `raw` structure using `merge_filtered_into_raw()`
3. For outputs, validate conversion to API object type
4. Store as overwrite (preserves original)

### Stack Trace Filtering

Stack traces are captured at LLM call time and filtered to show only user code:

- Removes AO infrastructure frames (agent_runner, database_manager)
- Removes frames from `ao-dev/` directory (unless developing AO itself)
- Returns as list of strings for readability
