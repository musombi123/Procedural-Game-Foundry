# Nexora Foundry creator acceptance playtest

This protocol is mandatory before calling a generated game creator-validated or release-ready.

## Test article

Use one creator-authored story brief, one full-body portrait supplied by the player with explicit permission to process it, and optional video only if the selected creation mode requires it. Record the project ID, source revision IDs, generated asset manifest and Git commit. Do not place the portrait or source video in public CI artifacts.

## Gate A — player identity and assets

- Confirm the player understands how the portrait is used and has consented to processing.
- Review the face crop, body proportions, clothing palette, skinning, idle and walk animations.
- Confirm the player avatar is recognizable enough for the creator's intended use; do not claim photorealistic reconstruction.
- Inspect environment geometry, collision surfaces, actors, props and audio.
- Record defects against the exact asset revision. Regeneration must invalidate downstream approvals.

Pass: creator explicitly approves the player, environment, actors/props and audio stages.  
Fail: missing geometry, broken rig, distorted face crop, unusable collision, missing assets or unapproved likeness.

## Gate B — desktop playthrough

Run the exported desktop build, not the Godot editor preview.

1. Launch from a clean extraction/install location.
2. Confirm the main menu/start state and initial camera framing.
3. Walk in all directions; test camera rotation, jump and collision boundaries.
4. Interact with every objective prop; verify inventory and objective counters.
5. Engage each hostile actor; verify detection, chase/patrol, damage, defeat and defeat objectives.
6. Test checkpoints, save, close, relaunch and load.
7. Complete the mission and verify the win state; separately verify health depletion and the lose state.
8. Confirm effects and music trigger at the expected events and that looping audio does not stack.
9. Play continuously for at least 20 minutes; note crashes, frame stalls, memory growth and progression blockers.

## Gate C — Android physical-device playthrough

Install the generated debug APK on a physical Android device. Record device model, Android version, screen resolution and available RAM.

- Cold launch, rotate if supported, background/resume and force-close/relaunch.
- Test every touch control, including simultaneous movement plus jump/attack.
- Check touch target sizes, screen safe areas, HUD overlap and landscape/portrait behavior.
- Repeat the desktop mission, combat, save/load, win/lose and audio checks.
- Record startup time, sustained frame rate, thermal behavior, battery impact and crashes.

Pass: all critical actions are possible using touch only; no progression-blocking defects; save data survives process restart.

## Gate D — release package integrity

- Verify the desktop executable and Android APK are non-empty and correspond to the same source commit and assembly manifest.
- Record SHA-256 checksums, toolchain versions and asset manifest.
- Confirm all third-party notices and asset provenance are present.
- Keep debug APKs clearly labelled. Production Android releases require a separately managed signing key; never commit signing credentials.
- Test installation, upgrade and uninstall behavior before public release.

## Result record

For each gate, record PASS, FAIL or BLOCKED, tester, date, device/OS, commit SHA, assembly manifest hash, defects and retest evidence. A CI pass is not a human playtest. A synthetic portrait fixture is not a likeness review. A debug APK export is not a signed production release.
