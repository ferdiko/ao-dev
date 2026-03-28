# Priors Integration Design

This document defines the v1 system design for integrating `sovara-db` into `ao-dev` as the priors backend.

The design in this document is intentionally concrete. It records the decisions already made, proposes specific data and API shapes for the remaining implementation work, and explicitly lists the few open questions that still need follow-up.

## Status

This is a design draft for implementation. It is not a statement of current behavior.

## Problem Statement

`ao-dev` already has the concept of runtime priors, but the current architecture has several mismatches with the intended product:

- the UI still bypasses `so-server` for priors operations and talks to `sovara-db` directly
- prior retrieval and prior CRUD are not integrated into the main run/node lifecycle
- there is no first-class historical snapshot of which priors were applied to which LLM node
- current caching semantics do not cleanly support the user journey of:
  1. run fails
  2. user creates/updates a prior
  3. user clicks rerun
  4. rerun should retrieve again and inject the new prior
- there is no explicit node-kind classification that distinguishes LLM calls from MCP/tool calls

The goal of this work is to make priors a first-class part of `ao-dev` while keeping the initial implementation operationally simple.

## Scope

### In Scope

- integrate `sovara-db` as a child service of `so-server`
- route all priors-related traffic through `so-server`
- keep priors file-backed for v1 under `SOVARA_HOME`
- inject priors only into LLM nodes
- add priors-world revision semantics for retrieval cache invalidation
- store historical prior snapshots per LLM node
- expose priors state in the UI
- support manual prior CRUD from the priors view

### Out of Scope for V1

- DB-backed priors storage
- PageIndex integration
- backward compatibility or migration from older priors layouts
- diff preview UI for "newly added" priors
- broad redesign of existing trace/chat or inference flows

## Decided Design Principles

The following decisions are fixed for v1:

- `so-server` eagerly starts `sovara-db`.
- If `sovara-db` is unavailable, `so-server` stays up in degraded mode.
- UI and runner never talk to `sovara-db` directly.
- Priors are scoped by `(user_id, project_id)`.
- Priors remain file-backed in v1.
- Only LLM nodes receive priors.
- Priors are injected at the very top of the prompt/context.
- The injected tag is `<sovara-priors> ... </sovara-priors>`.
- Normal node IO should not show the priors block; priors are shown in a dedicated blue box.
- Prior retrieval uses cleaned `to_show` data, fully flattened including list indices.
- Existing priors already in context are ignored during retrieval on cache miss.
- Manual `<sovara-priors>` blocks are stripped and generate a warning.
- `node_kind` is decided at monkey-patch time, not inferred later.

## V1 Architecture

### Process Topology

V1 uses four cooperating processes:

1. User program under `so-record`
2. `so-server`
3. `sovara-db`
4. VS Code extension / webview UI

The communication model is:

- runner <-> `so-server`
- UI <-> `so-server`
- `so-server` <-> `sovara-db`
- `sovara-db` <-> `so-server` for internal LLM requests

The crucial rule is:

- `so-server` is the only front door.

That means:

- the UI never constructs its own priors client to `sovara-db`
- the runner never calls `sovara-db` directly for retrieval
- `sovara-db` does not own user-facing model configuration

### Ownership Boundaries

#### `so-server` Owns

- UI-facing priors API
- runner-facing priors integration
- run lifecycle
- LLM-call cache semantics
- historical per-node prior snapshots
- user/project identity resolution
- model config resolution
- broadcasting priors updates to the UI

#### `sovara-db` Owns

- canonical priors storage and folder semantics
- priors CRUD
- folder operations
- hierarchical locking
- priors retrieval implementation
- priors retrieval cache semantics
- validation/restructure implementation

### UI Event Flow

The main UI channel remains the existing `so-server` WebSocket.

For v1:

- `so-server` maintains one SSE subscription to `sovara-db /api/v1/events`
- `so-server` translates those events into its existing UI WebSocket broadcasts
- priors panels refresh through `so-server` broadcasts

This keeps the UI topology simple and removes the current direct `SovaraDBClient` bypass.

## Priors Storage Model

### Why File-Backed First

Priors storage stays filesystem-backed in v1 because the indexing and retrieval structure are still being designed. File-backed storage preserves:

- the current folder/tree mental model
- current CRUD and restructure behavior
- current hierarchical locking model
- lower implementation risk while caching and run history are stabilized

DB-backed priors storage is deferred until the retrieval semantics are more stable, i.e. how exactly retrieval is implemented.

### Scope Layout

V1 stores priors under `SOVARA_HOME`, scoped by user and project:

```text
{SOVARA_HOME}/priors/{user_id}/{project_id}/
  .scope.json
  beaver/
    retriever/
      abc123.json
      def456.json
```

The scope root is the canonical priors namespace for a single `(user_id, project_id)` pair.

### Scope Metadata

Each scope root has a metadata file:

```json
{
  "user_id": "user-123",
  "project_id": "project-456",
  "revision": 12,
  "updated_at": "2026-03-28T12:34:56Z"
}
```

This file is not part of the folder UI. It is a private implementation detail.

### Priors Revision

`revision` is a monotonic integer counter for the entire `(user_id, project_id)` priors scope.

The counter increments on any mutation that changes the visible priors corpus for that scope:

- create prior
- update prior
- move prior
- delete prior
- create/delete/move folder
- restructure execution

The revision is not per-prior. It represents "the current visible priors world" for a scope and is used to invalidate the retrieval cache behind the retrieval endpoint.

## Node Classification

### Why Explicit Classification Is Needed

Priors must only apply to LLM nodes. The system therefore needs a reliable distinction between:

- LLM calls
- MCP calls
- non-MCP tool calls

Inferring this later from node labels or parsed model names is too weak. Current name extraction utilities can return:

- actual model IDs
- MCP request names
- tool names from known URLs
- Claude SDK tool names

That is useful for display, but not reliable enough to drive priors injection.

### Decision

`node_kind` is assigned in the monkey patch layer when the node is first created.

V1 uses this enum:

- `llm`
- `mcp`
- `tool`

### Initial Classification Rules

#### `llm`

- known LLM provider requests on whitelisted LLM endpoints
- Claude SDK assistant/model events
- redacted reasoning nodes that still represent a model turn

#### `mcp`

- `MCP.ClientSession.send_request`

#### `tool`

- non-MCP tool calls intercepted through `requests` / `httpx`
- Claude SDK tool invocations

### Consequences

- priors pipeline only runs when `node_kind == 'llm'`
- UI can render an `MCP` pill based on persisted node metadata
- future UI can optionally show a separate `Tool` pill without changing storage

## Priors Injection Semantics

### Top-Level Injection

Auto-injected priors always go at the very top of the prompt/context.

This is important because it makes:

- stripping deterministic
- reconstruction deterministic
- display logic simple

### Managed Block Format

The injected block is system-managed and includes a machine-readable manifest:

```xml
<sovara-priors>
<!-- {"priors":[{"id":"p1","fp":"sha256:..."},{"id":"p2","fp":"sha256:..."}]} -->
## Prior Name
Prior content...

## Another Prior
More prior content...
</sovara-priors>
```

The manifest exists so that:

- already-in-context priors can be parsed reliably on cache miss
- fingerprints can be audited later

### Manual Blocks

If user code already contains `<sovara-priors>`:

- strip the block from the normal request
- attempt to parse the manifest
- if parsing succeeds, use the IDs as inherited priors for retrieval-time ignore behavior
- if parsing fails, still strip the block and record a warning

V1 does not support "manual priors stay in place". The system-managed block format is authoritative.

## Input, Display, and Executed Prompt Model

V1 intentionally separates three representations:

1. Clean input
2. Executed input
3. Historical prior snapshot

The canonical working representation for priors logic is the fully flattened `to_show` dictionary.

### Clean Input

The clean input is the request after all `<sovara-priors>` blocks have been removed.

This is what:

- gets stored in `llm_calls.input`
- appears in the normal node IO view
- participates in diff construction
- is represented canonically as a fully flattened `to_show` dictionary

### Executed Input

The executed input is the clean input plus a newly rendered `<sovara-priors>` block inserted at the top.

This is what is actually sent to the provider when retrieval runs and applies priors.

In practice, execution works in two stages:

1. manipulate the fully flattened `to_show` representation
2. merge the modified `to_show` back into `raw` to reconstruct the executable provider request

### Historical Snapshot

The historical snapshot is the exact applied priors state for a node, stored in `prior_retrievals`.

This includes:

- the ordered applied priors
- the exact rendered priors block
- retrieval metadata

This is what drives the blue priors box in the node IO view.

## Retrieval Context Construction

### Source Data

Retrieval uses cleaned `to_show` data, not raw request bodies.

For v1, the fully flattened `to_show` dictionary is the canonical surface for:

- stripping priors blocks
- computing input deltas
- rendering retrieval context
- selecting an approved injection anchor

### Flattening

The cleaned `to_show` payload is fully flattened, including list indices, for example:

- `body.messages.0.content`
- `body.messages.1.role`
- `tools.0.name`

This is stricter than the current UI-centric list-preserving representation and is intentional. Retrieval diffing and generic strip logic need exact, comparable leaf-level atoms.

### Generic Strip on Flattened `to_show`

Priors stripping is generic.

For `llm` nodes:

1. build the fully flattened `to_show`
2. iterate over every string value in the flattened dict
3. remove any well-formed `<sovara-priors>...</sovara-priors>` block
4. parse inherited prior IDs/fingerprints from the manifest if present
5. record warnings for malformed blocks

This makes priors stripping provider-agnostic.

### Diff Algorithm

For a current LLM node:

1. fully flatten the cleaned current `to_show`
2. fully flatten the cleaned `to_show` of every parent node
3. convert leaf entries into exact textual atoms, for example:
   - `body.messages.0.content: Find the failing SQL clause`
4. build the union of all parent atoms
5. drop every current atom that appears exactly in any parent
6. join the remaining atoms into the retrieval context string

This gives a coarse but deterministic "what is new at this node?" signal.

### Empty Diff

If the resulting diff is empty:

- skip retrieval
- persist `status = 'empty_context'`
- inject nothing

## Cache Semantics

### Core Principle

Priors changes should first invalidate retrieval results, and only invalidate the LLM-call cache if the retrieval output changes the executed prompt.

V1 therefore uses two distinct caches:

1. retrieval cache inside `sovara-db`
2. LLM-call cache inside `ao-dev`

### Retrieval Cache

The retrieval endpoint is called for every LLM node, using the current cleaned input for that node.

The retrieval endpoint itself is responsible for caching retrieval results, and this cache must be persisted across `sovara-db` restarts.

For v1, the recommended implementation is:

- canonical priors remain file-backed
- retrieval cache is stored in a small SQLite DB owned by `sovara-db`
- this DB is derived state, not canonical priors storage

Recommended cache file location:

- `{SOVARA_HOME}/priors/retrieval-cache.sqlite`

The retrieval cache key should include at least:

- cleaned retrieval context
- current priors scope revision
- `ignore_prior_ids`
- retrieval algorithm version
- retrieval model/tier

This means:

- retrieval is always asked for the current node input
- `sovara-db` can return a cached retrieval result when nothing relevant changed
- a priors-world change invalidates retrieval cache without needing a run-scoped revision in `ao-dev`
- retrieval cache survives `sovara-db` restarts

Recommended persisted retrieval cache columns:

- `scope_user_id`
- `scope_project_id`
- `priors_revision`
- `cache_key_hash`
- `context_diff`
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

The retrieval cache does not need active invalidation on priors mutation as long as `priors_revision` is part of the key. Old rows can remain and be garbage-collected later.

### LLM-Call Cache

The LLM-call cache in `ao-dev` runs after retrieval has completed and priors have been injected.

The LLM cache key is therefore based on the executed input, not the clean input.

In practice:

- `llm_calls.input` stores the clean stripped input for display and editing
- `llm_calls.input_hash` is computed from the executed request payload after priors injection

This lets the LLM cache behave naturally:

- if retrieval returns a different priors block, the executed input changes
- if the executed input changes, the LLM cache misses
- if retrieval returns the same priors block, the executed input stays the same and the LLM cache can hit

### No Run-Scoped Priors Revision

V1 does **not** freeze priors revision per run.

If the priors world changes during a run or rerun, that is acceptable. The system assumes the current priors world is the right one to use.

The consequence is:

- retrieval may observe a newer priors revision later in the same run
- later LLM nodes may therefore receive different priors than earlier nodes

This is an intentional product choice.

### Retrieval-Time Ignore Behavior

Inherited prior IDs are not part of the LLM cache key.

They only matter when retrieval actually runs. On every LLM node:

1. strip any existing priors block
2. parse inherited prior IDs from the stripped manifest if present
3. compute retrieval diff from cleaned flattened `to_show`
4. call retrieval with:
   - context diff
   - current priors scope
   - `ignore_prior_ids`
   - timeout
5. persist the result in `prior_retrievals`
6. inject the returned block at the top of the executed input
7. perform the normal LLM-call cache lookup using the executed input

### Why This Matches the User Journey

The target workflow is:

1. run fails
2. user creates/updates a prior
3. user clicks rerun
4. retrieval should see the new priors world
5. the LLM cache should miss only if retrieval changed the executed prompt

Putting caching behind the retrieval endpoint achieves exactly that:

- retrieval is always asked first
- retrieval cache decides whether priors work needs to be recomputed
- LLM cache only sees the final executed prompt

## Database Changes

### `llm_calls`

Add:

- `node_kind TEXT NOT NULL CHECK (node_kind IN ('llm', 'mcp', 'tool'))`

`llm_calls.input` remains the clean, stripped input.

`llm_calls.input_hash` is computed from the executed input after priors injection.

No `runs.priors_revision` column is required in v1.

### `prior_retrievals`

Add a new table keyed by `(run_id, node_uuid)`.

Proposed schema:

```sql
CREATE TABLE prior_retrievals (
    run_id TEXT NOT NULL,
    node_uuid TEXT NOT NULL,
    priors_revision INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN (
            'applied',
            'none',
            'empty_context',
            'timeout',
            'unavailable',
            'error'
        )
    ),
    model TEXT,
    timeout_ms INTEGER,
    latency_ms INTEGER,
    inherited_prior_ids_json TEXT NOT NULL DEFAULT '[]',
    applied_prior_count INTEGER NOT NULL DEFAULT 0,
    applied_priors_json TEXT NOT NULL DEFAULT '[]',
    rendered_priors_block TEXT NOT NULL DEFAULT '',
    context_diff TEXT NOT NULL DEFAULT '',
    warning_message TEXT,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT (datetime('now')),
    updated_at TIMESTAMP DEFAULT (datetime('now')),
    PRIMARY KEY (run_id, node_uuid),
    FOREIGN KEY (run_id, node_uuid) REFERENCES llm_calls (run_id, node_uuid)
);
```

### `applied_priors_json`

Proposed shape:

```json
[
  {
    "id": "p1",
    "fingerprint": "sha256:...",
    "name": "Retry after tool timeout",
    "path": "agent/retriever/",
    "content": "..."
  }
]
```

This is intentionally a historical snapshot, not a live reference lookup.

## Graph Payload Changes

Graph nodes should carry lightweight priors metadata so the graph view can render immediately without extra fetches:

- `node_kind`
- `prior_count`
- `prior_status`

Example:

```json
{
  "uuid": "...",
  "label": "Claude Sonnet 4.6",
  "node_kind": "llm",
  "prior_count": 2,
  "prior_status": "applied"
}
```

The full applied priors snapshot is fetched lazily when the user opens/selects a node.

## API Design

### UI-Facing API (`so-server`)

The UI talks only to `so-server`.

Recommended endpoints:

- `GET /ui/config`
- `POST /ui/priors/folders/ls`
- `GET /ui/priors/{prior_id}`
- `GET /ui/priors`
- `POST /ui/priors`
- `PUT /ui/priors/{prior_id}`
- `DELETE /ui/priors/{prior_id}`
- `GET /ui/prior-retrieval/{run_id}/{node_uuid}`

The existing UI WebSocket remains the real-time channel for:

- `priors_refresh`
- run/graph updates
- warnings and status refreshes if needed

### `so-server` -> `sovara-db`

`so-server` calls `sovara-db` over REST and injects scope context itself.

Recommended internal headers:

- `X-Sovara-User-Id`
- `X-Sovara-Project-Id`

These headers are not trusted from the UI. They are only set by `so-server`.

Recommended `sovara-db` endpoints:

- `GET /health`
- `GET /api/v1/events`
- `GET /api/v1/priors`
- `GET /api/v1/priors/{prior_id}`
- `POST /api/v1/priors`
- `PUT /api/v1/priors/{prior_id}`
- `DELETE /api/v1/priors/{prior_id}`
- `POST /api/v1/priors/folders/ls`
- `POST /api/v1/priors/retrieve`
- `GET /api/v1/priors/scope`

The scope endpoint should return at least:

```json
{
  "user_id": "user-123",
  "project_id": "project-456",
  "revision": 12
}
```

The retrieval endpoint should also be able to return the scope revision it used and whether its own internal retrieval cache hit, for example:

```json
{
  "status": "applied",
  "cache_hit": true,
  "priors_revision": 12,
  "applied_prior_count": 2,
  "applied_priors": [...],
  "rendered_priors_block": "<sovara-priors>...</sovara-priors>"
}
```

### `sovara-db` -> `so-server` LLM Access

`so-server` is the only owner of LLM configuration.

`sovara-db` therefore does not read user LLM config directly. Instead it asks `so-server` to perform the actual model call.

Recommended generic internal endpoint:

- `POST /internal/llm/chat`

Body:

```json
{
  "purpose": "priors_retrieval",
  "tier": "weak",
  "messages": [...],
  "response_format": {...},
  "timeout_ms": 30000
}
```

Initial policy:

- retrieval -> weak model by default
- validation -> strong model
- restructure -> strong model

This generic endpoint avoids baking priors-specific model logic into `sovara-db`.

## Runtime Flow

### Run Start

1. runner registers with `so-server`
2. `so-server` resolves `(user_id, project_id)`
3. no priors revision is frozen onto the run in v1

### Non-LLM Node

If `node_kind != 'llm'`:

- no priors logic runs
- normal cache and graph behavior continue

### LLM Node Retrieval + Cache Pipeline

1. monkey patch classifies the node as `llm`
2. helper strips `<sovara-priors>` from the request
3. helper produces clean input
4. parse inherited prior IDs from stripped block if present
5. build flattened cleaned `to_show` diff
6. if diff empty:
   - write `prior_retrievals.status = 'empty_context'`
   - do not inject priors
7. otherwise call retrieval with:
   - context diff
   - `ignore_prior_ids`
   - timeout = `30000`
8. persist `prior_retrievals`
9. render the managed block
10. select a provider-approved injection anchor key in the flattened clean `to_show`
11. prepend the rendered block into that anchor value
12. merge the modified flattened `to_show` back into `raw`
11. compute the LLM cache key from the executed request
12. if the LLM cache hits:
   - reuse cached output
13. otherwise:
   - execute the LLM call

## UI Design

### Priors Sidebar / Priors Tab

The priors management UI remains folder-centric:

- folder tree
- CRUD operations
- project-scoped priors only

The priors tab is only available in a project context.

### Graph View

Each node receives lightweight priors metadata from the graph payload:

- `node_kind`
- `prior_count`
- `prior_status`

For LLM nodes with priors applied:

- render a blue GitHub-style header above the node
- the header shows only the count of priors attached to that node

For MCP nodes:

- render a small yellow `MCP` pill in node IO

Non-MCP tools can be persisted as `tool` now and surfaced later.

### Node IO View

The normal input area shows the clean stripped input.

If the node has a `prior_retrievals` record:

- render a blue priors box at the top
- lazy-fetch the full snapshot from `GET /ui/prior-retrieval/{run_id}/{node_uuid}`
- show the full effective priors for that node

If retrieval timed out or failed:

- the status is visible in the UI
- the blue box can show `Timeout`, `Unavailable`, or `Error`

## Logging and Observability

### Principle

Priors retrieval should be observable, but this should not spam the main `so-server` log.

### Proposed Split

#### Operational Logs

- `so-server` operational issues remain in the main server log
- `sovara-db` operational issues remain in its own log file

#### Semantic Retrieval Records

- retrieval metadata is stored in `prior_retrievals`
- this becomes the main source of truth for:
  - what retrieval ran
  - what it ignored
  - what it applied
  - whether it timed out or failed

This is enough for v1. A separate retrieval-events table can be added later if needed.

## Failure Handling

### `sovara-db` Unavailable

- `so-server` stays up
- priors CRUD routes return degraded errors
- LLM calls proceed without priors on cache miss
- `prior_retrievals.status = 'unavailable'`

### Retrieval Timeout

- timeout is initially `30000ms`
- LLM call proceeds without priors
- `prior_retrievals.status = 'timeout'`
- timeout is visible in the UI

### Manual/Invalid Priors Block

- strip the block
- record `warning_message`
- continue

### Unknown `node_kind`

This should be treated as a patch-layer bug.

Fail-safe behavior:

- default to non-LLM behavior
- never inject priors
- log the classification failure

## Implementation Plan

Recommended implementation order:

1. Remove UI direct-to-`sovara-db` access and proxy priors through `so-server`
2. Add scope metadata and file-backed project/user priors layout in `sovara-db`
3. Add `node_kind` classification at monkey-patch time
4. Add `prior_retrievals`
5. Add strip / parse / inject helpers
6. Add retrieval endpoint caching inside `sovara-db`
7. Change LLM-call hashing to use executed input after priors injection
8. Add graph payload priors metadata
9. Add lazy node snapshot endpoint and blue priors UI
10. Add timeout/unavailable visibility in the UI

## Open Questions

These items remain intentionally open:

- exact field-level strip/inject adapters per provider request shape
- exact `node_kind` classification rules for every Claude SDK event subtype
- whether to show a `Tool` pill in the UI immediately or only persist it for now
- exact shape of the generic internal LLM endpoint once strong/weak model config is implemented
- PageIndex retrieval design and whether one prior or one subtree should become the index unit

## Summary

V1 deliberately optimizes for semantic correctness and implementation tractability:

- keep priors file-backed
- make `so-server` the only front door
- classify node kind at the monkey-patch layer
- cache retrieval behind the retrieval endpoint
- always run retrieval first for LLM nodes
- ignore inherited prior IDs only during retrieval
- store exact historical prior snapshots per node
- keep normal IO clean and show priors in a dedicated UI box

This gives a coherent foundation for later work on DB-backed priors storage and PageIndex without mixing those storage concerns into the first integration pass.
