# Nexora Foundry — production pipeline and technology

**Evidence snapshot:** 25 November 2026  
**Primary sources:** project README, `docs/architecture/`, `docs/engineering/roadmap.md`, `core/movie_pipeline/`, `core/gameplay_compiler/`, `core/audio_foundry/`, Blender scripts and Godot assembly modules.

## 1. Foundry Project Definition (FPD)

FPD is the versioned, structured project definition used as the source of truth. It represents creator-authored game intent and configuration in a form that can be validated, transformed into generation steps and assembled into a native Godot project.

The design is important because a structured project definition gives the system predictable inputs and explicit validation errors. It is not a generative model and does not prove that the game concept is creatively complete or fun.

## 2. Seven production stages

The documented creator-led pipeline separates a project into staged, reviewable work:

1. **Analysis** — local FFmpeg/FFprobe inspects supported video metadata, scene-cut candidates and sampled keyframes. The creator supplies story interpretation; the current documented pipeline does not claim automatic speech transcription or semantic film understanding.
2. **Player** — Blender generates an adjustable procedural humanoid, armature, deterministic skin weights and idle/walk animation strips. A user-selected portrait crop and sampled clothing palette can guide identity presentation. It is not an accurate photorealistic reconstruction of hidden anatomy from one image.
3. **Environment** — deterministic terrain/world specification, modular geometry, props, lighting and camera are generated and exported as GLB by Blender.
4. **Actors and props** — creator-authored descriptors are turned into procedural geometry, basic rigs, collision metadata and interaction manifests. A stored behavior descriptor does not automatically mean the behavior is fully active in the game runtime.
5. **Audio** — deterministic/original sound assets are produced locally and saved with cue metadata.
6. **Gameplay** — a creator-authored contract specifies movement, missions, objectives, actor state choices, prop interactions, checkpoints, health, inventory and save/load rules.
7. **Assembly and QA** — assets and manifests are registered, a native Godot project is assembled, references are validated and available playtest/export checks are executed.

Each stage is human-gated. Outputs enter a review state; the creator approves a stage before downstream work becomes ready. Regenerating an earlier stage invalidates approvals and outputs that depend on it.

## 3. Deterministic generation versus AI

The repository describes the production path as model-free/tools-first for the documented pipeline. Deterministic routines are used for procedural geometry, world generation, audio synthesis and fixed gameplay scripts.

This distinction matters in partner and investor conversations:

- a deterministic generator executes rules defined in code;
- a procedural asset builder produces geometry/audio from parameters;
- a metadata inspector extracts technical information from media;
- a generative AI model predicts outputs from learned weights.

The current production path should not be marketed as fully AI-generative film understanding or automated narrative creation. Future optional model-assisted work would need its own architecture, privacy, cost, rights and acceptance review.

## 4. Blender, GLB and Godot

Blender scripts generate meshes, environments, characters, props and asset exports. The AssetRegistry stores metadata and provides owner-checked project-level references. GLB/glTF files are imported into the Godot project assembly path.

Godot is authoritative for gameplay and export. The Foundry project assembler creates native project files, runtime scripts and resource references. Static validation and Godot headless checks are available in the repository.

The assembly boundary must be described accurately: a generated mesh or gameplay manifest does not automatically prove every model rig, collision shape, actor behavior, audio cue or interaction is correctly bound into a complete playable game. The roadmap explicitly identifies runtime integration and creator acceptance as ongoing work.

## 5. Gameplay compiler

The compiler translates a creator-authored structured JSON gameplay contract into a versioned Godot runtime package. It uses bounded, fixed templates rather than evaluating arbitrary creator-supplied source code.

The documented compiler validates objective and actor/prop/audio references against approved manifests. It emits data, a compiler manifest and fixed Godot scripts. The stage then requires creator review before assembly.

The compiler documentation identifies further integrations that are not to be claimed as finished until implemented and tested: full binding of all generated nodes and references, some combat/damage pathways, dialogue execution, navigation mesh pathfinding and adaptive music.

## 6. Procedural audio

The procedural audio subsystem uses deterministic local routines to produce mono PCM WAV files. Documented effects include tone, impact, sweep, pulse, noise and alarm; music moods include adventure, calm, tense and triumphant.

It records a manifest with duration, sample rate, cue trigger, path and file size. The creator listens and approves the audio stage.

The documented boundary is that cue triggers are metadata, not a fully integrated runtime event bus. Spatial audio, adaptive mixing and game-state-driven audio transitions need separate implementation/acceptance.

## 7. Asset discovery and provenance

The project documents:
- an original 2D starter library;
- a Poly Haven 3D model search/download workflow;
- registration of downloaded assets to the existing project AssetRegistry;
- source, licence, resolution, filenames and integrity metadata;
- bounded asset download and project path checks.

The documented Poly Haven assets are CC0-1.0 and the integration provides the required source credit. Creator-imported assets remain the creator's responsibility: they must be owned or properly licensed. "Free download" does not mean unrestricted commercial redistribution.

No downloaded model or plugin should be automatically executed. Imported asset packages must be inspected, path-checked and licence-reviewed.

## 8. Export and publishing

The local toolchain supports the direction of Web, Android and Windows outputs, subject to available software and device configuration. The creator's computer runs build tools.

- Android export requires Godot export templates and a configured JDK/Android SDK/build-tools.
- Windows output currently needs its own package/signing acceptance.
- Apple output requires supported macOS/Xcode and a creator-controlled publishing account.
- Microsoft Store publication is documented as not ready until an MSIX package, signing certificate and Partner Center identity exist.
- Google Play and App Store publishing requires creator-controlled accounts and explicit approval; a draft upload is not a completed rollout or store approval.

The desktop installer workflow and the game export workflow are distinct releases and should have separate versioning and evidence.

## 9. Suggested founder study questions

1. Why is FPD the source of truth instead of storing project state only in React?
2. Which fields are required to reproduce a build?
3. What determines whether a job is safe to retry?
4. Where does an asset become registered, and what identifies its provenance?
5. What is the difference between a GLB preview and a playable Godot scene?
6. Which pipeline stages require explicit creator approval?
7. What happens when Blender or Godot is missing?
8. Which artifacts stay local and which metadata may reach the cloud?
9. How do you know a generated script is safe to run?
10. What is the minimum test proving a generated game can actually be played?
