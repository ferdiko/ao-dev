# Web App v2 Review Report

### P0: Build and lint are failing, so the branch is not in a releasable state

Evidence:

- `src/components/Sidebar.tsx:15` imports `fetchUser` and never uses it
- `src/components/TagDropdown.tsx:4` imports `mockTags` and never uses it
- `src/components/TagDropdown.tsx:235` passes `setNewColor` to a callback typed as `(c: string) => void`, which currently fails type-checking
- `src/data/mock.ts:72` adds `tags` to a `Project` object even though `Project` does not define that property
- `src/pages/RunView.tsx:926` and `src/pages/RunView.tsx:1041` call `offsetTop` on `Element`, which fails strict TS
- `src/App.tsx:28` and `src/components/AttachmentPreview.tsx:56` trigger the Fast Refresh lint rule because they export non-component helpers from component files

Impact:

- `npm run build` exits non-zero
- `npm run lint` exits non-zero
- The frontend cannot be treated as CI-safe or merge-safe

Suggested fix:

- Fix the current TS and ESLint errors before any feature work
- Add a CI gate for `npm run lint && npm run build`
- Move shared helpers/hooks out of component files where Fast Refresh requires it

### P1: The initial `experiment_list` websocket snapshot can be dropped on first load

Evidence:

- `src/components/Sidebar.tsx:78-82` subscribes to `project_list_changed`
- `src/serverEvents.ts:14-41` opens the singleton websocket on the first subscription and dispatches messages only to already-registered listeners
- `src/server/routes/events.py:89-91` sends the initial experiment list immediately after websocket connect
- `src/pages/ProjectPage.tsx:840-848` subscribes to `experiment_list` later, in a separate component

Impact:

- On first project load, the sidebar can open the websocket before `ProjectPage` has registered its `experiment_list` listener
- The initial running-runs snapshot is then lost, so the Running table can stay empty until some later server-side change triggers another broadcast

Suggested fix:

- Do not rely on websocket timing for first-page hydration
- Fetch the initial running list explicitly through REST, or buffer/replay the latest event per type in `serverEvents.ts`
- If keeping the event bus, make initial data loading deterministic instead of subscriber-order dependent

### P1: `Revert` in `RunView` is not implemented and currently lies to the user

Evidence:

- `src/pages/RunView.tsx:955-963` removes the local edited flag and includes `TODO: revert on backend (re-fetch graph node)`

Impact:

- The UI badge disappears, but the edited graph data is not restored
- Users can believe they reverted an edit when the backend still holds the overwritten value

Suggested fix:

- Keep the original input/output payload for each edited node locally and restore it explicitly
- Or add a backend revert endpoint and re-fetch the graph node/session after revert
- Do not show a `Revert` affordance until it is real

### P1: The rerun loading state is wrong and can clear before the rerun finishes

Evidence:

- `src/pages/RunView.tsx:974-980` and `src/pages/RunView.tsx:991-997` set `rerunning` to `true`
- `src/pages/RunView.tsx:999-1004` clears `rerunning` whenever `graphNodes.length > 0`

Impact:

- On any run that already has graph nodes, the spinner can clear immediately on the next render, before the rerun actually completes
- The UI does not reflect real execution state

Suggested fix:

- Key rerun completion off a real event: new session ID, graph revision, websocket status, or explicit backend acknowledgement
- At minimum, compare against a previous graph version/timestamp instead of `graphNodes.length > 0`

### P1: Completed-run bulk selection becomes stale across filtering and pagination

Evidence:

- Selection is stored in `selectedCompleted` at `src/pages/ProjectPage.tsx:856-858`
- It is toggled manually at `src/pages/ProjectPage.tsx:956-969`
- There is no effect that intersects selection with the current `completed` result set
- Actions are driven by `selectedCompleted.size` at `src/pages/ProjectPage.tsx:1051-1067`

Impact:

- Users can keep hidden/off-page runs selected without any visible indication
- Bulk actions can operate on stale selections from a previous page/filter state

Suggested fix:

- Clear or reconcile selection whenever `completed` changes
- If cross-page bulk selection is a real feature, make it explicit in the UI and track it intentionally

### P2: Keyboard and screen-reader accessibility are weak in several core interactions

Evidence:

- `src/components/Sidebar.tsx:132-134` uses a clickable `div` for the logo/home action
- `src/pages/OrgPage.tsx:210-215` makes the entire project card a clickable `div`
- `src/pages/RunView.tsx:795-806` uses `div`/`span` for tabs and close actions
- `src/pages/ProjectPage.tsx:1025` and `src/pages/ProjectPage.tsx:1112` make table rows clickable without keyboard semantics

Impact:

- Keyboard users cannot reliably navigate the app
- Focus management and semantics are weaker than they should be for a frontend headed to production

Suggested fix:

- Use real interactive elements (`button`, `a`, `Link`) for actions and navigation
- Add keyboard handling only where native semantics are not possible
- Audit focus order and visible focus styles before merge

### P2: The codebase is already hard to maintain, and the current shape will slow refactoring

Evidence:

- `src/pages/RunView.tsx` is about 1300 lines
- `src/pages/ProjectPage.tsx` is about 1158 lines
- `src/pages/PriorsPage.tsx` is about 1048 lines
- `src/App.css` is about 5679 lines

Impact:

- Review and refactor cost is high
- Cross-cutting changes will keep getting riskier because logic, layout, and state are tightly coupled

Suggested fix:

- Split the routed pages into page shell + focused subcomponents + custom hooks
- Pull the filter state machine, table state, graph state, and editing state into separate modules
- Break `App.css` into page/component-scoped files or CSS modules before it grows further

### P2: Frontend engineering hygiene is incomplete: no tests, stock README, and prototype drift

Evidence:

- `src/user_interfaces/web_app_v2/package.json` defines `dev`, `build`, `lint`, and `preview`, but no test script
- No Vitest/Jest/Playwright/Cypress packages were found in the frontend package
- `src/user_interfaces/web_app_v2/README.md` is still the default Vite template

Impact:

- There is no safety net for refactors
- The frontend package does not document its real architecture or workflows

Suggested fix:

- Add at least a minimal test stack before merge:
  - unit tests for helpers/state transitions
  - a smoke test for the live routes
  - one end-to-end flow for `Org -> Project -> Run`
- Replace the template README with project-specific setup, architecture, and dev commands

## Suggested Refactor Order

1. Make the package green: fix `build` and `lint`.
4. Fix `RunView` correctness issues (`Revert`, rerun status, selection/state cleanup).
5. Fix websocket initialization so first-load state is deterministic.
6. Start extraction work on `ProjectPage`, `RunView`, and `App.css`.
7. Add a small automated test layer before merging to `main`.

