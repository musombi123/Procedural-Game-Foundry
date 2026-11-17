# Nexora Foundry engineering roadmap

Nexora Foundry is the flagship product of NEXORA Interactive Studios. The roadmap tracks executable capabilities separately from creator acceptance and release readiness.

## Implemented and automated

1. **Foundation:** FastAPI local-first core, versioned project definition, job lifecycle, validation, React/TypeScript studio and Tauri desktop shell.
2. **Procedural world:** deterministic terrain/world specification and Blender GLB environment generation.
3. **Player asset:** Blender procedural humanoid mesh, armature, skin weights, animation strips and portrait-derived texture/palette path.
4. **Actors and props:** procedural Blender geometry, actor rigs, prop manifests and interaction descriptors.
5. **Audio:** deterministic original WAV synthesis with cue manifests.
6. **Gameplay:** strict creator-authored gameplay contracts, deterministic Godot runtime scripts, objectives, interactions, actor behaviours, health, inventory, win/lose and save/load.
7. **Assembly:** approval-gated Godot project assembly, imported GLB/WAV assets, runtime wiring, project archive and gameplay smoke checks.
8. **Integration validation:** CI invokes the actual Blender generators and imports their generated assets into Godot 4.6.1. The portrait used in CI is a synthetic, non-identifying fixture.
9. **Mobile runtime:** shared action map and on-screen touch controls are included in the assembled scene; automated checks assert their presence and binding.
10. **Export preparation:** generated projects include Linux/X11 and Android export presets. Native export CI is being added as a separate release gate.

## Creator acceptance gates — not yet complete

- Upload a real full-body portrait with the player's explicit consent.
- Review and approve avatar face crop, proportions, rig and animation in the creator studio.
- Run the entire pipeline from creator-authored brief through final assembly using that real portrait.
- Complete a human playtest: movement, camera, collisions, interaction, combat, objectives, save/load, win/lose and audio.
- Launch and test the desktop export on a supported desktop OS.
- Install and play the Android APK on a physical device; verify touch controls, performance, screen layout, audio and lifecycle behavior.

## Release engineering gates — not yet complete

- Confirm Linux and Android exports succeed from the same assembled creator project in CI.
- Retain build artifacts with commit, toolchain and asset-manifest provenance.
- Add reproducible versioning, checksums, SBOM/license notices and release notes.
- Add signed Android release configuration without committing keystores or passwords.
- Validate clean install, upgrade, uninstall and save-data behavior.
- Establish crash reporting, performance budgets and a documented rollback process.

A green CI run demonstrates only the checks it actually executes. Synthetic fixtures do not prove likeness quality; headless runtime checks do not prove human playability; debug APK export does not prove production signing or physical-device compatibility.
