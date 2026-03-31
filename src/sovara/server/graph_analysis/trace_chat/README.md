# Sovara Agent

ReAct agent for analyzing AI agent execution traces and editing prompts or input text within them.

## Architecture

```
main.py                     ReAct loop, prefetch, chat interface
tools/
  __init__.py               Tool registry + OpenAI-format schemas + dispatch
  get_trace_overview.py     Structural summary (no LLM)
  get_step_snapshot.py      Raw step snapshot with full/new_input scopes (no LLM)
  search.py                 Substring search across rendered trace content (no LLM)
  get_step_overview.py      Per-step summary + expandable content-unit overview
  summarize_trace.py        Full trace narrative via parallel summaries + synthesis (LLM)
  verify.py                 Correctness verdict per step (LLM, cached)
  ask_step.py               Targeted Q&A about a single step (LLM)
  prompt_edit.py            Content-unit editing + structural edits with undo (LLM)
utils/
  trace.py                  Trace/TraceRecord/DiffedRecord parsing and diffing
  context.py                Message history compaction
  editable_content.py       Editable content extraction and labeling
```

Shared server module:

```
../../llm_backend.py        LiteLLM wrapper with tier routing and retries
```

## Debug CLI

For local debugging you can run the trace chat agent directly in the terminal:

```bash
python src/sovara/server/graph_analysis/trace_chat/main.py \
  src/sovara/server/graph_analysis/trace_chat/example_traces/weather_agent.jsonl
```

You can also pass the trace with `--trace ...`. The CLI opens a simple `input()` REPL and loads the JSONL trace from disk before starting the chat loop.

### ReAct loop (`main.py`)

`handle_question` runs up to 10 iterations. Each iteration: call LLM with tool schemas, execute any tool calls concurrently via ThreadPoolExecutor, append results, compact if over budget, repeat. When the LLM responds without tool calls, that's the final answer.

All tools share the signature `f(trace: Trace, **params) -> str` and are registered in `tools/__init__.py` as both a Python dispatch dict and an OpenAI-format schema list. LiteLLM translates schemas to each provider's native format.

### Trace model (`utils/trace.py`)

A trace is JSONL — one record per LLM call or tool invocation. Each record has a system prompt, input messages, output, and optional metadata (correct, label, summary).

`Trace.from_string()` parses records and computes a **diff view**: records sharing a system prompt form a conversation, and `DiffedRecord.new_messages` contains only messages appended since the previous turn in that conversation. This avoids loading the full growing message history for later turns. Conversation identity is tracked via `prompt_id` (SHA-256 hash of the system prompt text).

`prompt_registry` maps each `prompt_id` to its full text — one canonical copy per unique prompt regardless of how many turns use it.

## Scenarios

### Trace Q&A

User asks a question about the trace. The agent picks tools based on specificity:

- Broad questions ("what happened?") — the **prefetched trace summary** (injected into the system prompt) may suffice with zero tool calls.
- Structural questions ("how many steps?") — `get_trace_overview` returns step count, conversation grouping, and per-step size/name metadata. No LLM cost.
- Targeted questions ("what did step 3 do?") — `ask_step` sends the step's content to an LLM and returns just the answer. More context-efficient than `get_step_snapshot` + reasoning.
- Content search ("which step mentions retry?") — `search` does case-insensitive substring matching across all prompts, inputs, and outputs.
- Verification ("is step 5 correct?") — `verify` uses an LLM judge. Can verify a single step or all steps in parallel.

### Prompt editing

User asks to change prompt or input text. The agent follows an overview-first workflow:

1. **`get_trace_overview()`** — optional first pass when you need to understand the trace or choose a step.
2. **`get_step_overview(step_id)`** — shows the cached step summary plus `content_id` handles for the visible content units in that step; longer content is summarized.
3. **`get_content_unit(step_id, content_id)`** — retrieves the full text behind one visible content unit when needed.
4. **`edit_content(step_id, content_id, instruction)`** — rewrites one visible input content unit.
5. **`delete_content_unit(step_id, content_id)`** — exact structural removal of one content unit.
6. **`undo(step_id)`** — reverts the last edit. Can be called repeatedly.

## Key design choices

### Content-unit view with expandable summaries

Editable input text and visible output content are exposed as step-global content units. Every visible content unit receives a `content_id`. Short content is shown inline under that `content_id`; longer content is summarized into 4-5 word labels. The same `content_id` can be used for drill-down, and input content IDs can also be used for editing.

This editable content view is cached on the `Trace` object (`editable_content_cache`) and created lazily on first access to any prompt-aware tool.

### Edit at first occurrence

The `prompt_registry` stores each unique prompt once. Edits modify the canonical copy there. Later turns in the trace that reuse the same prompt reference the same `prompt_id` — they don't get separate copies that could drift. This mirrors how `DiffedRecord` tracks `prompt_is_new` to avoid duplicating prompt content.

### Undo via snapshots

Every mutating tool (`edit_content`, `delete_content_unit`) deep-copies the cached editable content state before modifying. `undo` pops the last snapshot. Cheap because the editable units are small strings.

### Prefetched trace summary

On startup, a background thread generates a full trace summary (overview + parallel per-step summaries + synthesis). When the user asks their first question, the summary is injected into the system prompt. For broad questions, the agent can answer directly without tool calls.

### Context compaction (`utils/context.py`)

As the ReAct loop accumulates tool results, total message size grows. After each iteration, `compact_tool_results` checks whether tool results exceed 16K chars. If so, it replaces older results (never the most recent) with 1-2 sentence LLM-generated summaries, preserving key findings while freeing context budget.

### Two-tier model routing (`../../llm_backend.py`)

`infer()` accepts a `tier` parameter. `tier="expensive"` uses the user's configured primary model, while `tier="cheap"` uses the user's configured lower-cost helper model. Helper operations (labeling, summarization, verification, compaction) use the cheap tier. The ReAct planner and edit operations use the expensive tier.

### Caching

Four independent caches live on the `Trace` object:
- `step_semantic_summary_cache` — cached 3-sentence per-step summaries
- `step_overview_cache` — rendered `get_step_overview` outputs
- `summary_cache` — compatibility cache for older per-step summary callers
- `verdict_cache` — per-step correctness verdicts
- `editable_content_cache` — editable content view with undo stacks

All are lazily populated and persist for the session lifetime.
