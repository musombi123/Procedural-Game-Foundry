# Deterministic Gameplay Compiler

The Gameplay Compiler converts a creator-authored JSON contract into a versioned Godot runtime package. It never derives objectives, mission prose, actor intent, dialogue or game rules from a film or story. Empty creator fields remain validation errors.

## Inputs and approval gate

Compilation requires APPROVED pipeline records for analysis, player, environment, actors/props and audio, plus the matching story, actor/prop and audio manifests. The gameplay stage itself must be READY. Regenerating an upstream stage invalidates downstream approvals through PipelineStore.

## Creator-authored contract

- Player movement, jump, gravity, health and inventory capacity.
- Missions and typed objectives: collect, interact, defeat, reach, survive.
- Actor behaviour selection from an allowlisted finite-state set.
- Prop interactions selected from collect, open, activate, talk and damage.
- Explicit event-to-audio-cue bindings. Free-form audio trigger descriptions are not executable event names.

The API verifies actor, prop, objective and audio cue references against approved manifests. IDs are stable, bounded identifiers; generated scripts are fixed templates, never creator-supplied source code.

## Generated output

Gameplay JSON, audio event bindings, a compiler manifest and fixed Godot scripts for player movement, objective/mission progression, health, inventory, checkpoints, save/load, actor state behaviour and audio event routing. Output enters REVIEW. Creator approval is required before assembly becomes READY.

## Runtime integration boundary

This milestone emits Godot data and reusable runtime scripts. The final assembly step must bind generated player/actor/prop nodes, input actions, collision shapes, audio players and scene references. The compiler does not claim that every generated GLB rig or behaviour descriptor is already wired to a live scene. Combat damage, dialogue execution, navigation mesh pathfinding and adaptive music remain future runtime integrations.
