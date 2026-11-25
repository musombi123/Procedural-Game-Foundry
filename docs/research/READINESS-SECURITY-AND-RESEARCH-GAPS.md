# Nexora Foundry — readiness, security and research gaps

**Evidence snapshot:** 25 November 2026  
**Purpose:** Keep product claims aligned with evidence.

## 1. Capability and acceptance matrix

| Area | Source-level evidence | Current assurance boundary |
|---|---|---|
| FastAPI Foundry Core | Project, job, generation, validation and Godot-check routes | Endpoint presence is not full end-to-end production acceptance |
| FPD and schemas | Pydantic models and JSON Schemas | Validate schema and migrations across saved project versions |
| Procedural terrain/world | Deterministic heightfield and Blender environment generation | Visual and gameplay quality needs creator testing |
| Player avatar | Procedural mesh, armature, skin weights and animation pipeline | Real portrait consent, likeness review and proportion approval remain necessary |
| Actors and props | Procedural geometry and interaction/behavior manifests | Some runtime behavior and node binding remain incomplete |
| Audio | Deterministic original WAV synthesis and cue manifests | Runtime event bus/spatial/adaptive audio is not established |
| Gameplay compiler | Creator-authored bounded contract and fixed Godot script output | Full binding/playability still needs end-to-end tests |
| Godot assembly | Native project assembly and headless validation | Human playthrough and device testing remain required |
| Local Agent | Loopback service, pairing, system profile, local workspace, workload gate | Signed installer/update and cross-device acceptance remain |
| Android | Local export/ADB bridge and CI export checks in the repository | Physical device testing and signed release remain gates |
| Publishing | Release manifest and connector code/instructions | Creator accounts, OAuth, MSIX, signing and platform acceptance vary by connector |

A row can be implemented in source while remaining unaccepted for a public commercial release.

## 2. Creator acceptance gates

The project roadmap identifies these open acceptance requirements:

- a real creator-provided full-body portrait with explicit rights and consent;
- creator review of generated proportions, face crop, rig and animation;
- an entire pipeline run from creator-authored brief to final assembly;
- human playthrough covering movement, camera, collisions, interactions, objectives, combat where relevant, save/load, win/lose and audio;
- desktop launch and playtest on supported hardware;
- installation and playtesting of Android APK on a physical device, including touch controls, performance, layout, audio and app lifecycle.

A CI test with a synthetic image fixture does not prove likeness quality. A headless Godot test does not prove that a human can enjoy or finish the game. A debug APK export does not prove a signed release can be distributed.

## 3. Release engineering gates

The roadmap also calls for:

- repeatable versioning and build manifests;
- artifact hashes and source/toolchain provenance;
- software bill of materials and licence notices;
- signed Android release configuration;
- clean install, update, uninstall and save-data testing;
- crash reporting, performance budgets and rollback process;
- final acceptance on target operating systems and devices.

The NEXORA Windows host CI currently creates an NSIS installer artifact and manifest. The checked-in configuration does not establish public code signing or Microsoft Store certification.

## 4. Security boundaries

The technical security documents establish the following principles:

- Local Agent accepts loopback connections only.
- Browser-origin and host checks reduce cross-origin and DNS-rebinding style risks.
- Pairing is explicit and yields a short-lived local device token.
- Workload guards check hardware and required tool availability.
- Project writes are restricted beneath a configured data root.
- Imported project scripts are untrusted and must never auto-run.
- Asset/plugin imports require review and licence/provenance metadata.
- Creator publishing credentials and signing keys remain on the creator's machine.

These are intended design controls. Their effectiveness still requires abuse-case tests, code review, dependency review, installer/update hardening and independent security assessment.

## 5. Privacy, consent and intellectual property

The movie-to-game workflow may involve personal images, likeness references, source video, audio, creator-authored story details and third-party assets. NEXORA must obtain appropriate rights and consent before processing or publishing content.

For each asset, preserve:

- uploader/creator and project ownership context;
- source URL or source description;
- copyright/licence terms and attribution requirements;
- creator rights/consent declarations where relevant;
- generator/tool and version;
- parameters and timestamp;
- checksum and storage path;
- deletion and downstream derived-asset behavior.

The project documentation notes that the optional Google Drive ZIP backup does not currently apply a separate client-side encryption layer to the archive. Do not describe it as end-to-end encrypted. Explain the Google account access controls and advise creators to protect sensitive project material.

## 6. Commercial and operational questions

Before an investor or partner receives commercial claims, NEXORA needs documented answers for:

1. Which creator segment is the initial target: students, indie creators, training institutions, studios or another group?
2. What existing tool workflow does the product replace or accelerate?
3. How much time does a creator save compared with a manual baseline?
4. What hardware is required by each workload?
5. What are support, update, asset distribution and storage costs per active creator?
6. Which features are free, subscription-based or paid add-ons?
7. What is the cost of optional cloud backup, publishing and storage?
8. What is the plan for security updates and local agent compatibility?
9. What third-party licences constrain distribution?
10. What release and product liability obligations apply to user-generated games?

There is no verified revenue, paying user, retention, market share or valuation dataset in this repository review. Those should not be invented.

## 7. Research and partnership experiments

A useful first set of studies:

### Creator usability
Recruit a small, clearly described cohort. Observe whether they can pair the Local Agent, create a project, generate a scene, open it in Godot and complete a playtest. Record failures and time-to-task, not just satisfaction.

### Reproducible build study
Run the same FPD and toolchain manifest on multiple clean devices. Compare generated file hashes where determinism is expected, and document variation where tool versions or environment affect output.

### Asset quality study
Use rights-cleared, diverse test assets. Have technical artists assess mesh quality, topology, rig weights, texture artifacts, import behavior and editability.

### Device matrix
Test declared low, mid and high hardware profiles with fixed projects. Record CPU, RAM, GPU/VRAM, disk, elapsed time, crashes and output size. Never generalize beyond the tested sample.

### Playability study
Define one small complete game loop and test from creation to human play. Record whether the game is playable, understandable and fun enough to continue—not merely whether files were generated.

### Business validation
Interview target creators and buyers. Test willingness to pay and procurement constraints before building forecasts.

## 8. Defensible external positioning

A careful statement:

> NEXORA is developing a local-first game-production workflow that combines structured project definitions, procedural tools, Blender asset generation, Godot assembly and a paired desktop agent. The engineering foundation is in place across the core pipeline, while creator acceptance, physical-device validation, signed release engineering and market validation remain active milestones.

This communicates ambition without describing the product as finished.

## 9. Founder checklist before each partnership conversation

- Show the exact working commit.
- Distinguish main-branch functionality from feature-branch work.
- State which workflow has passed automated tests and which has completed human acceptance.
- Explain what data stays local and what contacts the cloud.
- Show a small playable output if one has passed real playtest.
- Bring a precise partner work package and acceptance criterion.
- Agree on ownership, licence, compensation and publication in writing.
