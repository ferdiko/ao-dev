# Sovara - LLM Dataflow Graph System

Sovara is a development tool that creates interactive dataflow graphs of LLM calls, enabling visualization, editing, and debugging of data flow in agentic AI applications. Each node in the data flow graph is an LLM or tool call and edges denote the output of one LLM/tool call forming part of the input of another.

## Edit & Rerun

The core goal is **interactive debugging of LLM workflows**:
1. Run your script once to capture the dataflow graph
2. Inspect any node's input/output in the UI
3. Edit an LLM's input or output directly
4. Rerun to see how changes propagate through the graph

On rerun, cached outputs are returned for unchanged inputs, and edited values are respected. This enables rapid iteration without re-calling LLMs unnecessarily.

## Project Structure

- @src/sovara/cli/ - CLI tools (`so-record`, `so-server`, `so-config`)
- @src/sovara/common/ - Shared utilities (config, constants, logger, utils)
- @src/sovara/server/ - Core server (app, state, database_manager)
- @src/sovara/runner/ - Runtime execution (agent_runner, string_matching, context_manager)
- @src/sovara/runner/monkey_patching/ - API interception (patches/, api_parsers/)
- @ui/ - VS Code extension and web app
- @tests/billable/ - Tests that make LLM API calls
- @example_workflows/ - AI workflow examples (bird-bench, human_eval, swe_bench, debug_examples, etc.)
- @docs/ - Documentation for mkdocs site

## Quick File References

VSCode extension files:
- @ui/vscode_extension/src/ – Contains relevant source code for the extensions.

Core system files:
- @src/sovara/server/app.py - FastAPI app factory for the local server
- @src/sovara/server/database_manager.py - Manages communication with the database and content registry for edge detection
- @src/sovara/server/state.py - In-memory state, git versioning, and process coordination
- @src/sovara/runner/agent_runner.py - Runtime environment setup
- @src/sovara/runner/string_matching.py - Content-based edge detection algorithm
- @src/sovara/runner/monkey_patching/patches/httpx_patch.py - LLM API interception example
- @src/sovara/runner/README.md - Overall runner system documentation

## How It Works

1. **Runtime Setup**: @src/sovara/runner/agent_runner.py establishes server connection and applies monkey patches
2. **LLM Interception**: @src/sovara/runner/monkey_patching/patches/ intercept API calls (httpx, requests, etc.)
3. **Edge Detection**: @src/sovara/runner/string_matching.py checks if previous outputs appear in current input
4. **Visualization**: Interactive graph shows LLM calls as nodes and content matches as edges

## Installation & Setup

## Before you start
Check if you are working on the main branch. If not, check the main branch for updates. If there are updates, **DO NOT PROCEED**. Let the user know there are updates in the main branch and ask him to pull the main branch and merge into the current branch.

## Key Commands

```bash
# Running (replace python with so-record)
so-record script.py

# Server management
so-server start/stop/restart/clear/logs

# Testing
python -m pytest -v tests/billable/  # Tests that make LLM API calls
```

## Dos and Do Nots
- The code base implements several interacting components. Keeping their interfaces, structuring and implementations lean, simple and clean is an absolute core concer when writing code. When you make changes, explain me why this is the most straight-forward way to implement something and how it fits into the rest of the code base and (if applicable) matches existing patterns. When refining code iteratively (including the user asking to add things on top of existing code), always revise your changes and make sure that they lead to the simplest implementation overall. This might involve removing or modifying existing code, e.g., as the requested changes may present opportunities to simplify existing code.
- **Do NOT** consider backwards compatability. The code has no users yet, which allows you to write cleaner, more concise code.
- Remain critical and skeptical about my thinking at all times. Maintain consistent intellectual standards throughout our conversation. Don't lower your bar for evidence or reasoning quality just because we've been talking longer or because I seem frustrated. If I'm making weak arguments, keep pointing that out even if I've made good ones before.
