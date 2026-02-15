# Claude Code Integration

AO integrates with [Claude Code](https://docs.anthropic.com/en/docs/claude-code) to accelerate agent development. Instead of manually inspecting logs or stepping through debuggers, Claude Code can directly query your agent's dataflow graph, understand what happened, and help you iterate faster.

![AO x Claude Code](../media/cc_and_ao.png)

## Why Use This Integration?

- **Keep context clean**: Agent runs produce verbose logs that quickly pollute Claude's context window. With `ao-tool`, Claude queries only the specific nodes it needs.
- **Structured access**: Claude gets structured JSON data (inputs, outputs, graph topology) rather than parsing raw logs.
- **Edit and rerun**: Claude can programmatically edit an LLM's input or output and trigger a rerun to test hypotheses.

## Setup

Run the interactive setup command:

```bash
ao-tool install-skill
```

This will:

1. Ask for your project directory (with tab-completion)
2. Copy the AO skill file to `.claude/skills/ao/SKILL.md`
3. Optionally add Bash permissions to `.claude/settings.local.json` so Claude can run `ao-tool` commands without prompts

After setup, restart Claude Code to load the new skill.

## Available Commands

Once set up, Claude Code can use these commands:

### Record an Agent Run

```bash
ao-tool record agent.py                    # Record and block until complete
ao-tool record --timeout 60 agent.py       # With 60s timeout
ao-tool record -m module_name              # Run as Python module
ao-tool record --run-name "my run" agent.py  # With custom name
```

### Query Session State

```bash
# List recent experiments
ao-tool experiments --range :10

# Get session overview (graph topology with nodes and edges)
ao-tool probe <session_id>

# Get full node details
ao-tool probe <session_id> --node <node_id>

# Get multiple nodes
ao-tool probe <session_id> --nodes <id1,id2,id3>

# Get truncated preview (20 char strings)
ao-tool probe <session_id> --node <node_id> --preview

# Filter keys with regex
ao-tool probe <session_id> --node <node_id> --key-regex "messages.*content"

# Only show input or output
ao-tool probe <session_id> --node <node_id> --input
ao-tool probe <session_id> --node <node_id> --output
```

### Edit and Rerun

Edit commands use flattened key notation (e.g., `messages.0.content`) and always create a new run:

```bash
# Edit an output key and rerun
ao-tool edit-and-rerun <session_id> <node_id> --output <key> <value>

# Edit an input key and rerun
ao-tool edit-and-rerun <session_id> <node_id> --input <key> <value>

# With custom run name
ao-tool edit-and-rerun <session_id> <node_id> --output <key> <value> --run-name "variant A"

# With timeout
ao-tool edit-and-rerun <session_id> <node_id> --output <key> <value> --timeout 60
```

**Examples:**

```bash
# Change the model's response content
ao-tool edit-and-rerun abc-123 node-1 --output "choices.0.message.content" "New response text"

# Modify a prompt message
ao-tool edit-and-rerun abc-123 node-1 --input "messages.0.content" "Updated prompt"

# Value can also be a path to a file
ao-tool edit-and-rerun abc-123 node-1 --output "choices.0.message.content" ./new_response.txt
```

## Workflow Examples

### Debug a Failing Agent

1. Claude records the agent: `ao-tool record agent.py`
2. Inspects the graph: `ao-tool probe <session_id>`
3. Examines the failing node: `ao-tool probe <session_id> --node <failing_node>`
4. Fixes and reruns: `ao-tool edit-and-rerun <session_id> <node_id> --output <key> <new_value>`

### A/B Test a Prompt Change

1. Run original: `ao-tool record agent.py`
2. Inspect the node to edit: `ao-tool probe <session_id> --node <node_id>`
3. Create variant: `ao-tool edit-and-rerun <session_id> <node_id> --input <key> <value> --run-name "variant"`
4. Compare the two sessions

### Iterate on LLM Output

1. Run agent and find a suboptimal response
2. Edit the output to what you want: `ao-tool edit-and-rerun <session_id> <node_id> --output <key> <value>`
3. See how downstream nodes react to the improved output
4. Use insights to improve your prompts

## Output Format

All `ao-tool` commands output JSON for easy parsing. Examples:

**Successful record:**
```json
{
  "status": "completed",
  "session_id": "abc-123",
  "exit_code": 0,
  "duration_seconds": 12.5
}
```

**Probe session:**
```json
{
  "session_id": "abc-123",
  "name": "Run 42",
  "status": "finished",
  "node_count": 5,
  "nodes": [
    {"node_id": "node-1", "label": "GPT-4", "parent_ids": [], "child_ids": ["node-2"]}
  ],
  "edges": [
    {"source": "node-1", "target": "node-2"}
  ]
}
```

**Error:**
```json
{
  "status": "error",
  "error": "Session not found: xyz"
}
```
