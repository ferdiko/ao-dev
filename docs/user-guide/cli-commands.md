# CLI Commands

Sovara provides three main CLI commands for running and managing your LLM applications.

## so-record

The primary command for running Python scripts with Sovara analysis.

### Basic Usage

```bash
# Run a script
so-record script.py

# Run a script with arguments
so-record script.py --arg1 value1 --arg2 value2

# Run a module (like you would with python -m mypackage.mymodule)
so-record -m mypackage.mymodule

# Run with environment variables
ENV_VAR=value so-record script.py
```

### Options

| Option | Description |
|--------|-------------|
| `--config-file` | Path to configuration file |
| `--run-name` | Name for this run (for organizing in the UI) |

### Examples

```bash
# Run a simple script
so-record my_agent.py

# Run a module from a package
so-record -m agents.research_agent

# Run with a custom run name
so-record --run-name "experiment-v1" my_agent.py

# Pass arguments to your script
so-record my_agent.py --model gpt-4 --temperature 0.7
```

## so-server

Manage the Sovara development server.

### Commands

```bash
# Start the server
so-server start

# Stop the server
so-server stop

# Restart the server (useful after code changes)
so-server restart

# Clear all recorded runs and cached LLM calls
so-server clear

# View server logs
so-server logs

# Clear all log files
so-server clear-logs
```

### Notes

- The server automatically starts when you run `so-record` if it's not already running
- If you make changes to server code, run `so-server restart` to apply them
- Log files are stored in `~/.sovara/logs/`:
  - `main_server.log` - Main server logs

### Troubleshooting

Check if the server process is running:

```bash
ps aux | grep 'so_server\|uvicorn'
```

Check which processes are using the server port:

```bash
lsof -i :5959
```

## so-config

Configure Sovara settings interactively.

### Usage

```bash
so-config
```

This launches an interactive configuration wizard that prompts you for:

- **Project root directory** - The root of your Python project
- **Database URL** - Configuration for result caching

### When to Use

Run `so-config` when:

- Setting up Sovara for a new project
- Changing the project root directory
- Configuring database settings for caching

!!! tip "Project Root"
    For some example workflows, you may need to set the project root to the example's directory. Run `so-config` and set it to the root of the example repo.

## Environment Variables

Sovara respects the following environment variables:

### Core Variables

| Variable | Description |
|----------|-------------|
| `SOVARA_SESSION_ID` | Current session identifier |
| `SOVARA_SEED` | Random seed for reproducibility |

### Server Configuration

| Variable | Description |
|----------|-------------|
| `HOST` | Server host (default: `127.0.0.1`) |
| `PYTHON_PORT` | Server port (default: `5959`) |

### Path Customization

| Variable | Description |
|----------|-------------|
| `SOVARA_HOME` | Base directory for Sovara files (default: `~/.sovara`) |
| `SOVARA_CONFIG` | Path to config file (default: `~/.sovara/config.yaml`) |
| `SOVARA_CACHE` | Cache directory (default: `~/.cache/.sovara`) |
| `SOVARA_LOG_DIR` | Log directory (default: `~/.sovara/logs`) |
| `SOVARA_DB_PATH` | Database directory (default: `~/.sovara/db`) |
| `SOVARA_GIT_DIR` | Git versioning directory (default: `~/.sovara/git`) |

## Next Steps

- [Learn about the VS Code extension](vscode-extension.md)
- [Create subruns for batch processing](subruns.md)
