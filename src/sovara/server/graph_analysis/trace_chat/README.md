# Sovara Agent

ReAct agent for analyzing AI agent execution traces and editing the system prompts within them.

## Architecture

```
main.py                     ReAct loop, prefetch, chat interface
tools/
  __init__.py               Tool registry + OpenAI-format schemas + dispatch
  get_trace_overview.py     Structural summary (no LLM)
  get_turn.py               Turn content with full/diff/output views (no LLM)
  search.py                 Substring search across trace + prompt sections (no LLM)
  get_step_overview.py      Per-step 3-sentence summary + expandable input-content overview
  summarize_trace.py        Full trace narrative via parallel summaries + synthesis (LLM)
  verify.py                 Correctness verdict per turn (LLM, cached)
  ask_turn.py               Targeted Q&A about a single turn (LLM)
  prompt_edit.py            Section-level prompt editing with undo (LLM)
utils/
  trace.py                  Trace/TraceRecord/DiffedRecord parsing and diffing
  context.py                Message history compaction
  prompt_sections.py        Section/PromptSections splitting and labeling
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
- Structural questions ("how many turns?") — `get_trace_overview` returns turn count, conversation grouping, and per-turn size/name metadata. No LLM cost.
- Targeted questions ("what did turn 3 do?") — `ask_turn` sends the turn's content to an LLM and returns just the answer. More context-efficient than `get_turn` + reasoning.
- Content search ("which turn mentions retry?") — `search` does case-insensitive substring matching across all prompts, inputs, and outputs.
- Verification ("is turn 5 correct?") — `verify` uses an LLM judge. Can verify a single turn or all turns in parallel.

### Prompt editing

User asks to change a system prompt. The agent follows a section-based workflow:

1. **`get_step_overview(step_id)`** — shows the cached step summary plus step-global `content_id` handles for every visible input and output content unit; longer content is summarized.
2. **`get_content(content_id)`** — retrieves the full text behind one visible content unit. `path` is optional for validation, and paragraph refs remain available for compatibility.
3. **`edit_content(content_id, instruction)`** — rewrites one visible input content unit. `path` is optional for validation, and the edit LLM handles faithful rewriting.
4. **`insert_content_paragraph`**, **`delete_content_paragraph`**, **`move_content_paragraph`** — structural paragraph changes.
5. **`undo`** — reverts the last edit. Can be called repeatedly.

If `prompt_id` is omitted and the trace has exactly one prompt, it's used automatically.

## Key design choices

### Path-level content view with expandable summaries

Editable input text and visible output content are exposed as step-global content units. Every visible content unit receives a `content_id`. Short content is shown inline under that `content_id`; longer content is summarized into 4-5 word labels. The same `content_id` can be used for drill-down, and input content IDs can also be used for editing.

The flattened section view is cached on the `Trace` object (`prompt_sections_cache`) and created lazily on first access to any prompt-aware tool.

### Edit at first occurrence

The `prompt_registry` stores each unique prompt once. Edits modify the canonical copy there. Later turns in the trace that reuse the same prompt reference the same `prompt_id` — they don't get separate copies that could drift. This mirrors how `DiffedRecord` tracks `prompt_is_new` to avoid duplicating prompt content.

### Undo via snapshots

Every mutating tool (`edit_content`, `insert_content_paragraph`, `delete_content_paragraph`, `move_content_paragraph`) deep-copies the sections list before modifying. `undo` pops the last snapshot. Cheap because sections are small strings.

### Prefetched trace summary

On startup, a background thread generates a full trace summary (overview + parallel per-turn summaries + synthesis). When the user asks their first question, the summary is injected into the system prompt. For broad questions, the agent can answer directly without tool calls.

### Context compaction (`utils/context.py`)

As the ReAct loop accumulates tool results, total message size grows. After each iteration, `compact_tool_results` checks whether tool results exceed 16K chars. If so, it replaces older results (never the most recent) with 1-2 sentence LLM-generated summaries, preserving key findings while freeing context budget.

### Two-tier model routing (`../../llm_backend.py`)

`infer()` accepts a `tier` parameter. `tier="expensive"` uses the configured model; `tier="cheap"` routes to a smaller model (e.g., Haiku instead of Sonnet). Helper operations (labeling, summarization, verification, compaction) use the cheap tier. Only the ReAct planner and direct Q&A use the expensive model.

### Caching

Four independent caches live on the `Trace` object:
- `step_semantic_summary_cache` — cached 3-sentence per-step summaries
- `step_overview_cache` — rendered `get_step_overview` outputs
- `summary_cache` — compatibility cache for older per-step summary callers
- `verdict_cache` — per-turn correctness verdicts
- `prompt_sections_cache` — sectioned/labeled prompts with undo stacks

All are lazily populated and persist for the session lifetime.
