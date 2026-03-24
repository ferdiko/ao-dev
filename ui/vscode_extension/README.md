# Sovara for VS Code

Inspect, edit, and replay agent workflows without leaving VS Code.

Sovara turns recorded runs into an interactive graph inside the editor so you can trace prompts, outputs, dependencies, and cached reruns in one place.

## Features

- Browse recent runs from the Sovara sidebar
- Open full graph tabs for individual runs
- Inspect inputs, outputs, attachments, and code locations
- Edit a node and rerun only downstream work
- Reconnect to the local Sovara server automatically

## Requirements

- VS Code `1.74+`
- A Python environment with `sovara` installed
- A project you run through `so-record`

## Quick Start

1. Install `sovara` in the Python environment VS Code should use:

   ```bash
   uv add --dev sovara
   # or
   pip install sovara
   ```

2. Open your project in VS Code.
3. Record a run:

   ```bash
   so-record python your_script.py
   ```

4. Open the Sovara icon in the Activity Bar and select a run.

By default the extension connects to `127.0.0.1:5959`. It can start `so-server` automatically when `sovara` is installed in the selected Python environment. If you prefer to start it yourself:

```bash
so-server start
```

## Settings

- `sovara.pythonServerHost`: Host for the local Sovara server
- `sovara.pythonServerPort`: Port for the local Sovara server

## Command

- `Sovara: Open Sidebar`

## Support

- Repository: https://github.com/SovaraLabs/sovara
- Issues: https://github.com/SovaraLabs/sovara/issues
- Email: hello@sovara-labs.com
