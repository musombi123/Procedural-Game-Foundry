# NEXORA Studio Pro — Phase 4 progress

**Working branch:** `nexora-studio-pro-phase-4`  
**Base:** `main` after PR #38 was merged  
**Phase 4 scope from the master build brief:** Internal IDE, game monetization add-ons, sponsored placements inside NEXORA, and the premium Studio interface.

## Delivered in this implementation slice

### Local-first Internal IDE
- Added an Internal IDE entry to the existing React workspace; it is available after a project is selected.
- Connects to the paired loopback Local Agent at `http://127.0.0.1:8765` (override with `VITE_NEXORA_LOCAL_AGENT`).
- Uses the existing owner-checked desktop project file API and paired Local Agent bearer authorization.
- Browses project files, opens supported UTF-8 text sources, edits and saves them, and creates new source files.
- Supports Ctrl/Cmd+S and unsaved-change warning before switching files.
- Saves include the original SHA-256. A concurrent external edit returns HTTP 409 instead of silently overwriting newer work.
- New source files are created locally, are restricted to the approved text extensions, capped at 2 MiB, and cannot overwrite existing files.
- Project paths are validated against traversal and symlink escapes. Source files and game assets remain on the creator's computer; this feature does not upload them to Render.

## Current limitations — not yet complete

- The current editor is a secure text-source editor, not yet a full language-server IDE: syntax highlighting, diagnostics, autocomplete, integrated terminal, debugger, breakpoints and run/test controls remain.
- The user must provide the paired Local Agent bearer token for this first UI slice. The polished account-pairing handoff and secure OS-backed token retrieval UI remain.
- Game monetization add-ons are not yet implemented. Provider SDK integration, consent handling, placement configuration, test mode, revenue reporting and export-time injection remain.
- NEXORA sponsored placements and advertiser reporting are not yet implemented. Future placements must be explicitly labelled, frequency-capped, and excluded from the editing canvas, timeline, preview and active build jobs.
- Premium Studio layout consolidation, Level Manager screen, Export Center and dock/timeline integration remain.

## Tests and acceptance

Automated tests cover local source-file creation, nested folder creation, overwrite prevention, unsupported or unsafe paths and the 2 MiB source limit. The full Python suite and web production build must pass on this branch before this slice is accepted. Manual acceptance must be done with a paired Local Agent, an owned local project and a second editor changing the same file to confirm HTTP 409 conflict handling.

No paid infrastructure, hosted source-file storage, cloud game processing or third-party ad network has been added.
