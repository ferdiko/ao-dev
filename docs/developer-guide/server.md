# Server

The development server is the core of Sovara. It receives events from user processes, manages the dataflow graph, and controls the UI. All communication goes: agent_runner <-> server <-> UI.

## Overview

The server (`app.py` plus `state.py`) handles:

- TCP socket communication with runner processes
- Session and run management
- Dataflow graph construction
- LLM call caching
- User edit management
- UI updates

## Server Runtime

The `so-server` CLI launches a detached FastAPI server process. Git versioning work is scheduled from `ServerState` in background tasks so each run can be tied to a code snapshot stored under `~/.sovara/git`.

## Server Commands

The server starts automatically when you run `so-record` or interact with the UI. It also automatically shuts down after periods of inactivity.

```bash
# Manual server management
so-server start
so-server stop
so-server restart
so-server clear    # Clear all cached data and DB
```

> **Note:** When you make changes to the server code, you need to restart the server for changes to take effect!

## Server Logs

All server logs are written to files (not visible in any terminal). Use these commands to view them:

```bash
so-server logs        # Main server logs
so-server clear-logs  # Clear the log file before a fresh restart
```

## Debugging the Server

Check if the server is running:

```bash
ps aux | grep 'so_server\|uvicorn'
```

Check which processes are using the port:

```bash
lsof -i :5959
```

## Database

The database (SQLite) stores:

- **Cached LLM calls** - For fast replay during re-runs
- **User edits** - Input/output modifications
- **Graph topology** - For reconstructing past runs

See `src/sovara/server/database_backends/sqlite.py` for the DB schema.

### Key Concepts

- **`input_hash`** - LLM calls are cached based on a hash of their inputs, not node IDs (since the graph structure may change)
- **`DatabaseManager`** - Handles all cache operations and user edit storage (see `database_manager.py`)

### Graph Topology Storage

The `graph_topology` column in the `experiments` table stores a dictionary representation of the graph. This allows the server to reconstruct in-memory graph representations for past runs.

## Edge Detection via Content Matching

The server stores a content registry for detecting dataflow edges:

```python
# In-memory registry: session_id -> {node_id -> [output_strings]}
_content_registry: Dict[str, Dict[str, List[str]]] = {}
```

When an LLM call is made:
1. We extract all text strings from the input
2. We check if any previously stored output strings appear as substrings
3. If a match is found, we create an edge from the source node to the current node

This approach runs user code completely unmodified and works with any LLM library.

## Editing and Caching

### User Experience Goals

1. View past runs with their full graphs, inputs, outputs, labels, and colors
2. Edit inputs/outputs and re-run with cached LLM calls (fast)
3. Persist across VS Code restarts

### How Editing Works

1. User clicks "Edit Input" or "Edit Output" in the UI
2. Edit is stored in the database
3. On re-run, the cached LLM call is retrieved
4. The edit is applied at the appropriate point
5. Downstream LLM calls re-execute with modified data

## Session Management

Each `so-record` execution creates a session. Within a session:

- Multiple runs can occur (via subruns or restarts)
- Each run builds its own dataflow graph
- The UI displays the current run's graph

### Communication Flow

```
Runner Process <---> Server <---> UI (VS Code/Web)
     │                  │              │
     │  LLM events      │  Graph       │
     │  ───────────>    │  updates     │
     │                  │  ─────────>  │
     │                  │              │
     │  Edit requests   │              │
     │  <───────────    │  <─────────  │
```

## Extending the Server

When modifying server code:

1. Make your changes to files in `src/sovara/server/`
2. Restart the server: `so-server restart`
3. Changes take effect immediately

## Next Steps

- [Edge detection](edge-detection.md) - How dataflow edges are detected
- [API patching](api-patching.md) - How LLM APIs are intercepted
