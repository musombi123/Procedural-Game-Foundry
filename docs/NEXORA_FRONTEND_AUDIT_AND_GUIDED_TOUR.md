# NEXORA Frontend Productivity Audit + Guided Tour

## Implemented on branch
`nexora-frontend-productivity-tour`

## First-login tour
- `apps/web/src/nexoraTourConfig.ts`: centralized English 9-step content.
- `apps/web/src/NexoraGuidedTour.tsx`: spotlight, arrow, Back/Next/Skip, keyboard arrows/Escape, focus trap, responsive bottom-sheet.
- Triggered on first browser session when no tour-state key exists; replay is available from the sidebar Help button.
- State (completed/skipped/last step) is stored in browser localStorage. This build does **not** yet persist tour state to the server account profile because the inspected frontend does not expose an authenticated profile/tour-state endpoint. It is browser-local only.
- Tour completion is not a gate. Escape and Skip dismiss it. Start my first game creates a project through the existing project creation API.
- Tour targets reflect the existing interface. PC pairing, readiness/permission meters, plans/payment, priced export checkout and the requested export entitlement panel are not implemented by this frontend yet; the tour does not fabricate them.

## Tests
- `npm run build` (TypeScript + Vite) is the frontend CI gate.
- Desktop and paired PC app interactive acceptance still requires a real browser/Windows PC agent. No remote interaction environment is available in this implementation session.

## Remaining requested productivity work
Command palette, global shortcut registry, undo/redo spanning timeline/assets, dockable layout persistence, recent-project resume point, asset bulk selection/favorites/tags, shared task queue pause/resume/cancel, project progress checklist, contextual hints, and notification center are not implemented by this patch. They should be tracked as follow-on slices rather than represented as complete.
