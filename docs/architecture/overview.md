# Architecture

FPD is the versioned source of truth. Python validates definitions; deterministic generators produce data/assets; the Godot assembler writes native project files; Godot is authoritative for gameplay; validators/build adapters report verified outcomes.

Trust boundaries: browser input is untrusted; API writes are confined to PGF_DATA_DIR; generators are offline by default; imported assets/plugins require review; generated scripts are user-editable code and must be inspected before running.

Pipeline: FPD -> dependency resolution -> procedural generation -> scene/runtime assembly -> static validation -> optional Godot headless validation -> export.

Web is React; Three.js can later provide editing visualization. Desktop uses Tauri and the same local API. Games run in Godot, not the browser viewport. A future local bridge must be paired/authenticated and must not expose arbitrary shell/filesystem operations.