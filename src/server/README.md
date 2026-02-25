# Server

This is basically the core of the tool. All analysis happens here. It receives messages from the user's agent runner process and controls the UI. I.e., communication goes agent_runner <-> server <-> UI.

 - To check if the server process is still running: `ps aux | grep main_server.py` or check which processes are holding the port: `lsof -i :5959`

## Server processes

1. Main server: Receives all UI and runner messages and forwards them. Core forwarding logic.
2. File watcher: Handles git versioning. On every `ao-record`, it checks if any user files have changed and commits them if so. It adds a version time stamp to the run, so the user knows what version of the code they ran. In the future, we will probably also allow the user to jump between versions. This git versioner is completely independent of any git operations the user performs. It is saved in `~/.cache/ao/git`. We expect it to commit way more frequently than the user, as it commits on any file change once the user runs `ao-record`.

## Server commands and log

Upon running `ao-record` or actions in the UI, the server will be started automatically. It will also automatically shut down after periods of inactivity. Use the following to manually start and stop the server:

 - `ao-server start`
 - `ao-server stop`
 - `ao-server restart`

> [!NOTE]
> When you make changes to the server code, you need to restart such that these changes are reflected in the running server!

If you want to clear all recorded runs and cached LLM calls (i.e., clear the DB), do `ao-server clear`.

To see logs, use these commands:

 - Logs of the main server: `ao-server logs`
 - Logs of the file watcher (git versioning): `ao-server git-logs`

Note that all server logs are printed to files and not visible from any terminal.

## Database

The database uses SQLite. Amongst other things, it stores cached LLM results and user input overrides (see `llm_calls` table). See [sqlite.py](/src/server/database_backends/sqlite.py) for the DB schema.

## Edge Detection via Content Matching

We detect dataflow between LLM calls using **content-based matching**. When an LLM call is made:

1. We extract all text strings from the input
2. We check if any previously stored LLM output strings appear as substrings in the input
3. If a match is found, we create an edge from the source node to the current node

This approach:
- Runs user code completely unmodified
- Works with any LLM library (OpenAI, Anthropic, etc.)
- Is simple and robust

The matching logic is implemented in [string_matching.py](/src/runner/string_matching.py). The content registry (storing outputs for matching) lives in [database_manager.py](/src/server/database_manager.py).
