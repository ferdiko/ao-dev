# Web App V2

`web_app` is the React/Vite frontend for the ao project workspace. It talks to the local backend over `/ui` HTTP routes and `/ws` websocket events, with the Vite dev server proxying both to `http://127.0.0.1:5959`.

## Requirements

- Node.js 20+
- npm
- a local ao backend running from the repo root

## Scripts

- `npm run dev`: start the Vite dev server
- `npm run build`: type-check and build a production bundle
- `npm run lint`: run ESLint across the frontend
- `npm run test`: run the Vitest unit test suite once
- `npm run preview`: preview the production build locally

## Local Development

1. From the repo root, start or restart the backend with `uv run ao-server restart`.
2. In this directory, run `npm run dev`.
3. Open the Vite URL printed in the terminal.

Backend contract changes are not hot-reloaded by the frontend. If you change a FastAPI route shape or websocket payload, restart the backend again with `uv run ao-server restart`.

## Testing

The frontend uses Vitest with Testing Library for lightweight unit and hook regression tests. Current coverage is intentionally small and focused on extracted shared logic:

- `src/projectRuns.test.ts`: project run mapping, timestamp parsing, and sort behavior
- `src/hooks/useCompletedSelection.test.tsx`: completed-run selection persistence and filter-scope resets

When you extract new shared hooks or helper modules, add targeted tests there instead of trying to test page-sized components end to end.

## Structure

- `src/pages`: route-level screens such as `ProjectPage` and `RunView`
- `src/components`: reusable UI sections extracted from the page files
- `src/hooks`: shared state/effect logic for selection, sorting, run layout, and run session state
- `src/projectRuns.ts`: shared row mapping, timestamp, and sorting helpers for project run tables
- `src/projectFilters.ts`: shared filter types and helpers for the project page
- `src/serverEvents.ts`: websocket event bus used by the frontend
