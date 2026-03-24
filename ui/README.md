# User Interfaces

This workspace contains the two UI surfaces for sovara:

1. `vscode_extension/`: the VS Code extension
2. `web_app/`: the standalone React/Vite web app

It also contains `shared_components/`, which is still used by the VS Code extension webviews and some shared UI logic.

## Workspace Layout

- `vscode_extension/`: extension source, webpack build, VS Code packaging
- `web_app/`: current standalone frontend
- `shared_components/`: shared types, graph/editor UI pieces, and utilities
- `user-interface.code-workspace`: convenience workspace for opening the UI code in VS Code

## Requirements

- Node.js 20+
- npm
- for the standalone web app, a running sovara backend from the repo root

## Install

From `ui/`:

```bash
npm run install:all
```

## Common Commands

From `ui/`:

- `npm run build:all`: build both the extension and the web app
- `npm run build:extension`: build only the VS Code extension
- `npm run build:webapp`: build only the standalone web app
- `npm run dev:webapp`: start the standalone web app dev server
- `npm run test:webapp`: run the standalone web app tests
- `npm run lint:webapp`: run the standalone web app linter
- `npm run clean`: remove workspace `node_modules`

## Standalone Web App

The standalone app lives in `ui/web_app/`.

Run it like this:

1. From the repo root, start or restart the backend:
   ```bash
   uv run so-server restart
   ```
2. From `ui/`, start the frontend:
   ```bash
   npm run dev:webapp
   ```
3. Open the Vite URL printed in the terminal.

Notes:

- The web app talks directly to the backend over `/ui` and `/ws`.
- If you change backend route shapes or websocket payloads, restart the backend again.
- Frontend-specific details and test commands are documented in [`web_app/README.md`](./web_app/README.md).

## VS Code Extension

Build the extension from `ui/`:

```bash
npm run build:extension
```

Run it from VS Code:

1. Open the repo in VS Code.
2. Use the `Run VS Code Extension` launch configuration.
3. Start debugging.
4. A second VS Code window will open with the extension enabled.

The extension-specific guide lives at [`docs/user-guide/vscode-extension.md`](/Users/jub/sovara/docs/user-guide/vscode-extension.md).

## Troubleshooting

- Clean install: `npm run clean && npm run install:all`
- Rebuild the extension: `cd vscode_extension && npm run compile`
- Rebuild the web app: `cd web_app && npm run build`
- Run web app tests: `cd web_app && npm run test`
- View extension logs: `Developer: Toggle Developer Tools` in the extension host window
- View web app logs: browser devtools console

## Graph Layout

The graph layout logic used by the UI stack is based on the existing shared layout approach. Historical algorithm notes are linked here:

[Graph layout notes](https://drive.google.com/file/d/1eKiijfvaGs_-5sajpeqk923Xbvro7x3X/view?usp=drive_link)
