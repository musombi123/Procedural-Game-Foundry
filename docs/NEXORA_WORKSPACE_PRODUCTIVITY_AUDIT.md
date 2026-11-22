# NEXORA Workspace Productivity Audit

## Scope and test standard

This audit was performed against the existing apps/web workspace on the nexora-workspace-productivity-tour branch. The workspace was extended in place; it was not rebuilt. Source inspection and automated CI are not substitutes for a live browser session, a paired Windows PC, or physical device testing.

## Audit status

| Area | Initial status | Current status | Cause / change |
|---|---|---|---|
| Sidebar and panel navigation | FAIL | FIXED / PARTIAL | Added Help and Shortcuts, command palette navigation, and real panel anchors. Full panel-by-panel browser console test remains pending. |
| Local PC connection | FAIL | FIXED / PARTIAL | Default engine URL now targets the Local Agent mount; paired token is shared across API panels; added PC health, hardware capability, workload readiness and CPU/RAM/GPU device-access status. Live PC pairing still needs acceptance testing. |
| Video upload | FAIL | FIXED / PARTIAL | The default API base now routes through 127.0.0.1:8765/engine; Movie Pipeline upload uses the shared paired-token fetch helper. Local storage behavior must be confirmed on a paired PC. |
| Asset Collection Center | PARTIAL | PARTIAL | Existing search, category filters, grid/list, upload, delete, preview and retry messaging retained. Bulk select/tag, favorites, drag-to-level and virtualization remain absent. |
| Project resume | FAIL | FIXED / PARTIAL | Last selected project ID is remembered and restored after the local project list loads. World autosaves to the local engine folder with a browser recovery copy on disconnect. |
| Saved-state indicator | FAIL | FIXED | Added debounced local-engine autosave and an explicit save/recovery status. IDE retains its separate file-level save indicator. |
| Undo/redo | FAIL | FIXED / PARTIAL | Added a bounded 100-state undo/redo history for world and scene edits, with Ctrl+Z, Ctrl+Y and Ctrl+Shift+Z. Timeline and asset-registry mutations are not yet included. |
| Command palette | FAIL | FIXED | Ctrl+K opens a searchable palette for workspace navigation, assets, IDE, monetization and Help. |
| Keyboard help | FAIL | FIXED / PARTIAL | Added a Help and Shortcuts panel. New-level and export shortcuts are intentionally not listed as active because those actions are not yet exposed in this frontend. |
| Project checklist | FAIL | FIXED / PARTIAL | Added a project checklist derived from persisted video and pipeline stage states. Exported status remains untracked rather than being inferred. |
| Guided tour | FAIL | FIXED / PARTIAL | Added config-driven 9-step tour, first-run launch, skip/finish persistence, replay from Help, spotlight, arrow, mobile sheet, keyboard navigation, focus trap and screen-reader dialog labels. |
| Account profile tour sync | FAIL | FIXED / PARTIAL | Added an account-owned PostgreSQL progress table and authenticated profile endpoints; Local Agent proxies using its in-memory paired account credential. Requires cloud deployment and a paired account for end-to-end verification. |
| Responsive layout | PARTIAL | PARTIAL | Existing breakpoints retained and new panels have mobile layouts. No visual pass at 1366×768, 1920×1080, ultrawide or 4K has been performed in a real browser. |
| Lazy loading / virtualization | FAIL | FAIL | Three.js viewport and long asset lists are not yet lazy-loaded/virtualized. |
| Background job queue | FAIL | FAIL | Existing pipeline polls a job synchronously; shared running/paused/completed queue and pause/resume/cancel controls are not implemented. |
| Notifications | FAIL | FAIL | Dismissible job/export/payment notifications are not implemented. |
| Docking / saved layout | FAIL | FAIL | User-resizable, dockable and per-user remembered panel layouts are not implemented. |
| Export entitlement / plan status | FAIL | FAIL | No unified account plan/export-entitlement status surface has been added. Monetization configuration remains separate from live SDK/billing execution. |

## Productivity changes in this branch

- GuidedTour.tsx and nexoraTourConfig.ts: guided onboarding and editable English-first copy.
- PCConnectionCard.tsx: Local Agent detection, pairing-token connection, hardware capability scan, video workload requirement score, and explicit device-access status.
- localAgentFetch.ts: shared authorization for the paired local engine.
- CommandPalette.tsx: Ctrl+K navigation.
- ShortcutsHelp.tsx: shortcut reference and tour replay.
- App.tsx: correct Local Agent API default, autosave, browser recovery cache, recent-project resume, scene undo/redo, PC status and first-project tour path.
- MoviePipelinePanel.tsx: pipeline and project progress anchors/checklist.
- AssetCollectionCenter.tsx: tour anchor; existing asset operations remain intact.
- identity.py: account-scoped tour progress persistence.
- local_agent.py: secure account-profile proxy using the cloud credential held in memory; local engine requests retain the Local Agent token so the mounted engine can validate the correct principal.
- tests/test_nexora_identity.py: route and payload validation coverage.

## Guided tour behavior

1. First app launch shows the tour if no local completion/skip record exists.
2. After PC pairing, the tour reads/writes the account progress through the Local Agent proxy.
3. Skip and Finish are stored separately; the last step is retained.
4. Help → Take the tour replays it.
5. PC step advances only after successful pairing; video step advances only after a file selection. Other steps can advance when the highlighted panel/control is clicked.
6. On narrow screens the card becomes a bottom sheet. Escape skips, arrow keys navigate, Tab is trapped inside the dialog, and focus returns to the previous control.

## Not yet accepted

- No browser session was available to run a console-error sweep or interaction tests at desktop viewport sizes.
- No paired Windows PC session was available to test app-closed, internet-drop, expired-session, file recovery and heavy-job responsiveness.
- No 4K or low-end device visual/performance measurements have been recorded.
- The checklist and tour are implemented; they do not imply the incomplete features in the table are finished.
