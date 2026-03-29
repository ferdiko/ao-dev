# Priors Implementation Plan

This document turns the priors integration design into a concrete engineering plan.

It assumes the decisions captured in [Priors Integration](priors-integration.md), including:

- priors stay file-backed in v1
- all priors traffic goes through `so-server`
- retrieval is always called first for `llm` nodes
- retrieval caching lives behind the retrieval endpoint in `sovara-db`
- `ao-dev` LLM-call caching happens after priors injection
- `node_kind` is assigned at monkey-patch time
- `prior_retrievals` is a sidecar table keyed by `(run_id, node_uuid)`

## High-Level Execution Order

Recommended implementation sequence:

1. add the internal LLM bridge backed by `src/sovara/server/llm_backend.py`
2. add `so-server` <-> `sovara-db` priors proxy routes
3. add `sovara-db` scope metadata and persisted retrieval cache
4. add AO DB schema changes (`node_kind`, `input_delta_json`, `prior_retrievals`)
5. add strip / delta / retrieve / inject logic in the runner patch pipeline
6. remove direct UI access to `sovara-db`
7. add UI node-kind and priors rendering
8. add tests and harden failure paths

This order reduces risk because it stabilizes the backend boundaries before editing the runner and UI.

## Code Touchpoints

The main files/modules likely to change are:

### `ao-dev`

- [src/sovara/server/llm_backend.py](/Users/jub/ao-dev/src/sovara/server/llm_backend.py)
- [src/sovara/server/app.py](/Users/jub/ao-dev/src/sovara/server/app.py)
- [src/sovara/server/routes/ui.py](/Users/jub/ao-dev/src/sovara/server/routes/ui.py)
- [src/sovara/server/routes/events.py](/Users/jub/ao-dev/src/sovara/server/routes/events.py)
- [src/sovara/server/database_backends/sqlite.py](/Users/jub/ao-dev/src/sovara/server/database_backends/sqlite.py)
- [src/sovara/server/database_manager.py](/Users/jub/ao-dev/src/sovara/server/database_manager.py)
- [src/sovara/server/graph_models.py](/Users/jub/ao-dev/src/sovara/server/graph_models.py)
- [src/sovara/runner/monkey_patching/patching_utils.py](/Users/jub/ao-dev/src/sovara/runner/monkey_patching/patching_utils.py)
- [src/sovara/runner/monkey_patching/api_parser.py](/Users/jub/ao-dev/src/sovara/runner/monkey_patching/api_parser.py)
- [ui/vscode_extension/src/providers/GraphTabProvider.ts](/Users/jub/ao-dev/ui/vscode_extension/src/providers/GraphTabProvider.ts)
- [ui/vscode_extension/src/providers/SidebarProvider.ts](/Users/jub/ao-dev/ui/vscode_extension/src/providers/SidebarProvider.ts)
- [ui/vscode_extension/src/providers/SovaraDBClient.ts](/Users/jub/ao-dev/ui/vscode_extension/src/providers/SovaraDBClient.ts)
- [ui/vscode_extension/src/webview/GraphTabApp.tsx](/Users/jub/ao-dev/ui/vscode_extension/src/webview/GraphTabApp.tsx)
- [ui/vscode_extension/src/webview/PriorsTabApp.tsx](/Users/jub/ao-dev/ui/vscode_extension/src/webview/PriorsTabApp.tsx)

### `sovara-db`

- `/Users/jub/sovara-db/src/sovara_priors/server/app.py`
- `/Users/jub/sovara-db/src/sovara_priors/server/routes/deps.py`
- `/Users/jub/sovara-db/src/sovara_priors/server/routes/query.py`
- `/Users/jub/sovara-db/src/sovara_priors/server/routes/lessons.py`
- `/Users/jub/sovara-db/src/sovara_priors/storage/local.py`
- `/Users/jub/sovara-db/src/sovara_priors/server/folder_lock.py`
- `/Users/jub/sovara-db/src/sovara_priors/llm/lesson_retriever.py`
- `/Users/jub/sovara-db/src/sovara_priors/llm/lesson_validator.py`
- `/Users/jub/sovara-db/src/sovara_priors/llm/lesson_restructurer.py`

## Stage 1: Internal LLM Bridge

### Goal

Make `so-server` the only owner of LLM access, using the newly introduced [llm_backend.py](/Users/jub/ao-dev/src/sovara/server/llm_backend.py).

### Why This First

The priors retriever, validator, and restructurer should not keep their own direct OpenAI client stack. If this boundary is not fixed first, later code will fork between two LLM backends.

### Current State

[llm_backend.py](/Users/jub/ao-dev/src/sovara/server/llm_backend.py) already provides:

- `infer()`
- `infer_text()`
- tier routing
- retries

It already forwards arbitrary `**kwargs` to `litellm.completion()`, which is a good base for structured output, but the current priors stack has three different expectations:

- retriever uses `chat.completions.create(..., response_format=json_schema)`
- validator uses `chat.completions.create(..., response_format=json_schema)`
- restructurer uses `responses.parse(..., text_format=PydanticModel)`

So the bridge should not stay generic here. It should explicitly standardize priors-side structured inference.

### Required Work

#### 1. Standardize priors-side structured inference on JSON schema

Recommended v1 decision:

- `so-server` exposes one structured JSON inference surface for priors workloads
- retriever and validator keep their existing JSON-schema style
- restructurer is migrated away from `responses.parse(...)` to an explicit JSON schema so it uses the same bridge

This reduces the moving pieces to:

- one transport contract between `sovara-db` and `so-server`
- one structured helper in [llm_backend.py](/Users/jub/ao-dev/src/sovara/server/llm_backend.py)
- one local validation path

The important compatibility rule is:

- native structured output is preferred but optional
- local JSON parse plus schema validation is required as a supported path
- this is necessary for deployments that rely on vLLM-backed models such as Qwen3.5

#### 2. Add a normalized internal endpoint in `so-server`

Recommended endpoint:

- `POST /internal/llm/infer`

Body:

```json
{
  "purpose": "priors_retrieval",
  "tier": "cheap",
  "model": "anthropic/claude-sonnet-4-6",
  "messages": [...],
  "response_format": {...},
  "timeout_ms": 30000
}
```

Response:

```json
{
  "raw_text": "...",
  "parsed": {...},
  "structured_mode": "native",
  "model_used": "openai/gpt-5.4-mini"
}
```

Recommended request semantics:

- `response_format` carries a JSON schema for priors retrieval / validation / restructure tasks
- `parsed` is present only when the result passed schema validation
- `structured_mode` is one of:
  - `native`
  - `local_parse`
  - `retry_repaired`
  - `failed`

#### 3. Add a structured helper on top of `llm_backend`

Recommended helper:

- `infer_structured_json(messages, model, tier="expensive", response_format=None, **kwargs)`

Behavior:

1. call `infer(..., response_format=response_format, **kwargs)`
2. inspect the provider response for native structured output or JSON text
3. if native structured output succeeded, return parsed data
4. otherwise extract raw text, parse JSON locally, and validate against the provided schema
5. if parsing or validation fails, optionally retry with an explicit repair prompt
6. if validation still fails after bounded retries, surface a structured error to the caller

The helper should return a normalized object such as:

```python
{
    "raw_text": str,
    "parsed": dict | None,
    "structured_mode": "native" | "local_parse" | "retry_repaired" | "failed",
    "model_used": str,
}
```

### Structured Decoding Recommendation

#### Retriever

The retriever schema is small and simple. For v1:

- prefer native structured output through `response_format`
- require a compatibility fallback mode:
  - ask for JSON
  - parse text locally
  - validate against the expected schema
  - optionally retry once or twice with repair prompting

This avoids blocking the retriever on perfect provider-side structured decoding while still keeping the return type deterministic.

#### Validator / Restructurer

These are more structured and more safety-sensitive.

Recommendation:

- still prefer native structured output
- use the same local-parse fallback path only if schema validation succeeds
- allow bounded repair retries
- fail closed if validation still fails

For the restructurer specifically:

- replace the current `responses.parse(..., text_format=RestructureProposal)` usage
- add an explicit JSON schema derived from `RestructureProposal`
- validate the returned object locally before constructing the domain model

### Concrete Touchpoints

- add endpoint in a new internal route module or extend an existing internal server route surface
- extend [src/sovara/server/llm_backend.py](/Users/jub/ao-dev/src/sovara/server/llm_backend.py)
- update `/Users/jub/sovara-db/src/sovara_priors/llm/lesson_retriever.py`
- update `/Users/jub/sovara-db/src/sovara_priors/llm/lesson_validator.py`
- update `/Users/jub/sovara-db/src/sovara_priors/llm/lesson_restructurer.py`
- add tests for:
  - cheap/expensive tier routing
  - structured native path
  - structured fallback path
  - restructurer JSON-schema migration path

## Stage 2: `so-server` <-> `sovara-db` Proxy Layer

### Goal

Route all priors traffic through `so-server` and remove the current UI bypass.

### Required Work

#### 1. Add UI-facing priors routes to `so-server`

Suggested routes:

- `GET /ui/priors`
- `GET /ui/priors/{prior_id}`
- `POST /ui/priors`
- `PUT /ui/priors/{prior_id}`
- `DELETE /ui/priors/{prior_id}`
- `POST /ui/priors/folders/ls`
- `GET /ui/prior-retrieval/{run_id}/{node_uuid}`

#### 2. Add a small internal priors client in `ao-dev`

This client should replace the direct VS Code `SovaraDBClient` usage. It should:

- call `sovara-db`
- inject trusted `user_id` / `project_id`
- translate errors into `so-server` responses

#### 3. Subscribe to `sovara-db` SSE inside `so-server`

`so-server` should:

- keep one SSE subscription to `/api/v1/events`
- translate those events into existing UI WebSocket broadcasts

### Concrete Touchpoints

- [src/sovara/server/routes/ui.py](/Users/jub/ao-dev/src/sovara/server/routes/ui.py)
- [src/sovara/server/routes/events.py](/Users/jub/ao-dev/src/sovara/server/routes/events.py)
- [src/sovara/server/app.py](/Users/jub/ao-dev/src/sovara/server/app.py)
- [ui/vscode_extension/src/providers/GraphTabProvider.ts](/Users/jub/ao-dev/ui/vscode_extension/src/providers/GraphTabProvider.ts)
- [ui/vscode_extension/src/providers/SovaraDBClient.ts](/Users/jub/ao-dev/ui/vscode_extension/src/providers/SovaraDBClient.ts)

### Exit Criteria

- the UI no longer connects to `sovara-db` directly
- all priors CRUD works through `so-server`
- priors refresh events still reach the UI

## Stage 3: `sovara-db` Scope Metadata and Retrieval Cache

### Goal

Keep priors file-backed while adding:

- project/user scope metadata
- persisted retrieval caching

### Required Work

#### 1. Add scope metadata file management

At each scope root:

- create `.scope.json`
- persist `revision`
- increment it on all visible priors mutations

#### 2. Add global persisted retrieval cache

Implement a SQLite DB owned by `sovara-db`, for example:

- `{SOVARA_HOME}/priors/retrieval-cache.sqlite`

Use a single global table with:

- `scope_user_id`
- `scope_project_id`
- `priors_revision`
- `cache_key_hash`
- `retrieval_context`
- `ignore_prior_ids_json`
- `model`
- `algorithm_version`
- `result_status`
- `applied_prior_count`
- `applied_priors_json`
- `rendered_priors_block`
- `latency_ms`
- `created_at`
- `last_accessed_at`

The cache key should include:

- scope revision
- cleaned retrieval context
- ignored IDs
- retrieval model/tier
- algorithm version

#### 3. Change retriever/validator/restructurer to use the internal LLM bridge

Replace direct OpenAI client dependencies with calls to `so-server`’s internal LLM endpoint.

The intended end state is:

- retriever -> internal structured JSON endpoint
- validator -> internal structured JSON endpoint
- restructurer -> internal structured JSON endpoint after migrating off `responses.parse(...)`

### Concrete Touchpoints

- `/Users/jub/sovara-db/src/sovara_priors/server/routes/deps.py`
- `/Users/jub/sovara-db/src/sovara_priors/server/routes/query.py`
- `/Users/jub/sovara-db/src/sovara_priors/storage/local.py`
- `/Users/jub/sovara-db/src/sovara_priors/llm/lesson_retriever.py`
- `/Users/jub/sovara-db/src/sovara_priors/llm/lesson_validator.py`
- `/Users/jub/sovara-db/src/sovara_priors/llm/lesson_restructurer.py`

### Exit Criteria

- priors CRUD increments scope revision
- retrieval cache survives `sovara-db` restart
- retriever no longer depends on its old direct LLM client stack
- validator and restructurer no longer depend on their old direct LLM client stack

## Stage 4: AO DB and Graph Model Changes

### Goal

Persist generic node metadata and priors-sidecar history.

### Schema Changes

#### `llm_calls`

Add:

- `node_kind`
- `input_delta_json`
- optionally `input_delta_count`

#### `prior_retrievals`

Add sidecar table keyed by `(run_id, node_uuid)` with:

- `status`
- `priors_revision`
- `model`
- `timeout_ms`
- `latency_ms`
- `inherited_prior_ids_json`
- `applied_prior_count`
- `applied_priors_json`
- `rendered_priors_block`
- `retrieval_context`
- `injection_anchor_json`
- `warning_message`
- `error_message`

### Graph Payload Changes

Graph nodes should expose:

- `node_kind`
- `prior_count`
- `prior_status`

### Concrete Touchpoints

- [src/sovara/server/database_backends/sqlite.py](/Users/jub/ao-dev/src/sovara/server/database_backends/sqlite.py)
- [src/sovara/server/database_manager.py](/Users/jub/ao-dev/src/sovara/server/database_manager.py)
- [src/sovara/server/graph_models.py](/Users/jub/ao-dev/src/sovara/server/graph_models.py)

## Stage 5: Runner Strip / Delta / Retrieve / Inject Pipeline

### Goal

Implement priors behavior in the interception pipeline without corrupting the existing edit/caching model.

### Canonical Working Surface

The canonical surface for priors logic is the fully flattened `to_show` dict.

Use it for:

- stripping priors blocks
- collecting inherited prior IDs
- computing `input_delta_json`
- rendering `retrieval_context`
- selecting a provider-approved injection anchor key

### Required Work

#### 1. Add `node_kind` classification in patching helpers

This should happen at monkey-patch time and be shared across providers.

#### 2. Add generic flattened `to_show` strip helper

For `llm` nodes only:

- walk all string leaves in flattened `to_show`
- strip well-formed `<sovara-priors>` blocks
- extract inherited prior IDs/fingerprints
- record malformed-block warnings

#### 3. Add generic `input_delta_json` computation

Use cleaned flattened `to_show` and parent cleaned flattened `to_show` values.

#### 4. Add provider-approved anchor selection

Do not inject into arbitrary strings.

Each provider adapter should define allowed flattened `to_show` anchor keys.

If no anchor exists:

- skip retrieval entirely
- persist `status='uninjectable'`

#### 5. Call retrieval before LLM cache for injectable `llm` nodes

Send:

- rendered retrieval context
- `ignore_prior_ids`
- scope info
- timeout

#### 6. Reconstruct executable request

- prepend rendered priors block into the chosen anchor key in flattened `to_show`
- merge modified `to_show` back into `raw`
- compute `input_hash` from the executed request

### Concrete Touchpoints

- [src/sovara/runner/monkey_patching/patching_utils.py](/Users/jub/ao-dev/src/sovara/runner/monkey_patching/patching_utils.py)
- [src/sovara/runner/monkey_patching/api_parser.py](/Users/jub/ao-dev/src/sovara/runner/monkey_patching/api_parser.py)
- parser-specific files under `src/sovara/runner/monkey_patching/api_parsers/`
- [src/sovara/server/database_manager.py](/Users/jub/ao-dev/src/sovara/server/database_manager.py)

### Exit Criteria

- injectable `llm` nodes run retrieval before LLM cache
- tool/MCP nodes never run priors logic
- `llm_calls.input` remains clean
- `llm_calls.input_hash` hashes executed input

## Stage 6: UI Integration

### Goal

Expose priors state cleanly in the graph and node views.

### Required Work

#### 1. Remove direct priors client usage in the extension

The extension should call only `so-server`.

#### 2. Show `node_kind`

- persist all three kinds now
- render at least the `MCP` pill immediately

#### 3. Add priors metadata to graph nodes

- count
- status

#### 4. Add lazy node priors fetch

When a node is selected:

- fetch `prior_retrievals` snapshot lazily
- render the blue priors box

#### 5. Surface failure states

At minimum:

- `timeout`
- `unavailable`
- `uninjectable`

### Concrete Touchpoints

- [ui/vscode_extension/src/providers/GraphTabProvider.ts](/Users/jub/ao-dev/ui/vscode_extension/src/providers/GraphTabProvider.ts)
- [ui/vscode_extension/src/providers/SidebarProvider.ts](/Users/jub/ao-dev/ui/vscode_extension/src/providers/SidebarProvider.ts)
- [ui/vscode_extension/src/webview/GraphTabApp.tsx](/Users/jub/ao-dev/ui/vscode_extension/src/webview/GraphTabApp.tsx)
- [ui/vscode_extension/src/webview/PriorsTabApp.tsx](/Users/jub/ao-dev/ui/vscode_extension/src/webview/PriorsTabApp.tsx)

## Stage 7: Testing

### Must-Have Test Cases

#### Runner / Caching

- `llm` node calls retrieval first
- `mcp` / `tool` nodes skip priors logic
- stripping removes managed priors block and preserves normal text
- input delta is computed from cleaned flattened `to_show`
- executed input hash changes when retrieved priors change

#### Retrieval Cache

- retrieval cache hit with same context + same scope revision
- retrieval cache miss after priors mutation increments revision
- retrieval cache survives service restart

#### Failure Paths

- manual malformed block -> warning + strip
- no approved anchor -> `uninjectable`
- retrieval timeout -> status visible, no crash
- `sovara-db` unavailable -> degraded mode, no crash

#### UI

- graph node shows priors count/status
- node details lazy-loads historical priors snapshot
- timeout/uninjectable states are visible
- MCP pill renders for MCP nodes

## Suggested Merge Strategy

To reduce integration risk, land this work in small slices:

1. DB schema + `node_kind` only
2. proxy routes + UI bypass removal
3. internal LLM bridge
4. `sovara-db` scope metadata + retrieval cache
5. runner strip/delta/retrieval pipeline
6. UI priors node rendering
7. cleanup and hardening

## Open Questions

Only a few items should remain open while implementation starts:

- exact allowed injection anchor keys per provider
- whether to surface `tool` as a pill in the first UI pass or just persist it

Everything else is now concrete enough to start building.
