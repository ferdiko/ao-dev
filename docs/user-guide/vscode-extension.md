# VS Code Extension

The Sovara VS Code extension provides an interactive visual interface for exploring LLM call dataflow graphs.

## Installation

### Building the Extension

1. Install Node.js if you haven't already
2. Navigate to the user interfaces directory:
   ```bash
   cd ui/
   npm run install:all
   ```
3. Build the extension:
   ```bash
   npm run build:extension
   ```

### Running the Extension

1. Open the Sovara project in VS Code
2. From the debugger options (in `launch.json`), select "Run Extension"
3. Press F5 or click the Run button
4. A new VS Code window opens with the extension active

Look for the **bar chart icon** in the VS Code side panel to access the extension.

## Features

### Dataflow Graph

The main view displays a directed graph where:

- **Nodes** represent LLM calls
- **Edges** show data dependencies between calls
- **Layout** is automatically computed for optimal readability

### Node Interactions

Click on any node to:

- **View Input** - See the full prompt sent to the LLM
- **View Output** - See the LLM's response
- **Edit Input** - Modify the input and re-run
- **Edit Output** - Override the output and re-run downstream
- **Navigate to Code** - Jump to the source code location

### Editing Inputs and Outputs

When you edit an input or output:

1. The run re-runs using cached LLM calls (for speed)
2. Your edits are applied at the appropriate point
3. Downstream LLM calls are re-executed with the modified data

This enables rapid iteration and debugging of your LLM pipelines.

### Run History

The extension maintains a history of runs, allowing you to:

- View past graph topologies
- Compare inputs and outputs across runs
- Return to previous states

## Build Commands

| Command | Description |
|---------|-------------|
| `npm run build:all` | Build both extension and webapp |
| `npm run build:extension` | Build VS Code extension only |
| `npm run build:webapp` | Build web app only |

## Troubleshooting

### Clean Install

If you encounter issues:

```bash
npm run clean && npm run install:all
```

### Rebuild Extension

```bash
cd vscode_extension && npm run compile
```

### View Extension Logs

In the VS Code window running the extension:

1. Press `Cmd+Shift+P` (Mac) or `Ctrl+Shift+P` (Windows/Linux)
2. Type "Developer: Toggle Developer Tools"
3. Check the Console tab for logs

### View Web App Logs

If using the web app in Chrome:

1. Right-click anywhere on the page
2. Select "Inspect"
3. Go to the Console tab

## Web App Alternative

Sovara also supports a standalone web application:

### Running the Web App

1. Start or restart the backend:
   ```bash
   uv run so-server restart
   ```

2. In another terminal, start the frontend dev server:
   ```bash
   cd ui/
   npm run dev:webapp
   ```

3. Open the localhost link displayed in your browser

## Next Steps

- [Learn about subruns](subruns.md)
- [Explore example workflows](../examples/index.md)
