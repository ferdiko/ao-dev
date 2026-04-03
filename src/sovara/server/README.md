# Server

This is basically the core of the tool. All analysis happens here. It receives messages from the user's agent runner process and controls the UI. I.e., communication goes agent_runner <-> server <-> UI.

 - To check if the server process is still running: `ps aux | grep 'so_server\|uvicorn'` or check which processes are holding the port: `lsof -i :5959`

## Server runtime

The `so-server` CLI launches the FastAPI server, and git versioning work is coordinated from `state.py` in background tasks. On every `so-record`, Sovara can snapshot changed user files into `~/.sovara/git` so runs stay tied to a code version without depending on the user's own git workflow.

## Server commands and log

Upon running `so-record` or actions in the UI, the server will be started automatically. It will also automatically shut down after periods of inactivity. Use the following to manually start and stop the server:

 - `so-server start`
 - `so-server stop`
 - `so-server restart`

> [!NOTE]
> When you make changes to the server code, you need to restart such that these changes are reflected in the running server!

If you want to clear all recorded runs and cached LLM calls (i.e., clear the DB), do `so-server clear`.

To see logs, use these commands:

 - Logs of the main server: `so-server logs`
 - Logs of the inference server: `so-server infer-logs`
 - Clear both log files before a fresh restart: `so-server clear-logs`

Note that all server logs are printed to files and not visible from any terminal.

## Database

The database uses SQLite. Amongst other things, it stores cached LLM results and user input overrides (see `llm_calls` table). See [schema.py](/src/sovara/server/database/sqlite/schema.py) for the DB schema.

## Edge Detection via Content Matching

We detect dataflow between LLM calls using **content-based matching**. When an LLM call is made:

1. We extract all text strings from the input
2. We check if any previously stored LLM output strings appear as substrings in the input
3. If a match is found, we create an edge from the source node to the current node

This approach:
- Runs user code completely unmodified
- Works with any LLM library (OpenAI, Anthropic, etc.)
- Is simple and robust

The matching logic is implemented in [string_matching.py](/src/sovara/runner/string_matching.py). The content registry (storing outputs for matching) lives in [llm_calls.py](/src/sovara/server/database/llm_calls.py).
