# Creator-led, tools-only Movie-to-Game Pipeline

## Product contract

The creator can start with an original written story, a movie clip, or a movie clip plus explicit instructions. A full-body portrait is the player identity reference and is required in every mode. Movie-first and guided modes require an authorized clip; story-first does not require a video or movie rights declaration.

The pipeline uses local software tools and deterministic algorithms only. No LLM, neural vision model, image generator, image-to-3D model, speech model, hosted inference endpoint or paid API is part of the production path. FFmpeg/FFprobe inspect media; Python creates manifests and deterministic layouts; Blender constructs meshes, rigs and GLB scenes; Three.js previews assets; Godot remains the playable runtime/export route.

The video is a reference, not source material to copy. Generated characters, environments, props, dialogue and audio must be original. Every stage is human-gated: outputs enter REVIEW and the creator must approve before the next stage becomes READY. Regenerating a stage invalidates downstream approvals and outputs.

## Creation modes

1. Story-first — creator writes premise, setting, player role, instructions, mission count and ending. No movie is required.
2. Movie-first — creator supplies a clip and portrait; local media tools extract metadata, scene-cut candidates and keyframes. The creator supplies interpretation and story direction.
3. Guided — creator supplies a clip, portrait and detailed instructions for how the game should unfold.

The creator's authored text is persisted verbatim. The system does not invent missing plot details or claim to semantically understand movie content without a creator.

## Stages

1. Analysis — FFmpeg/FFprobe metadata, scene-cut candidates and representative keyframes. No automatic speech transcription, visual-language description or story synthesis.
2. Player — creator-adjustable procedural humanoid mesh; manually selected portrait face crop mapped to a curved 3D head patch; sampled portrait clothing palette; named armature, deterministic proximity skin weights and idle/walk animation strips. The creator reviews the proportions and face crop.
3. Environment — deterministic terrain heightfield, modular 3D structures, props, lighting, camera and walkable route geometry. Blender exports a GLB. Full navigation-mesh baking and runtime collision integration remain later work.
4. Actors & props — creator-authored NPC/enemy/animal/robot descriptors and item/tool/weapon/vehicle/container/obstacle descriptors become procedural Blender meshes, basic armatures, collision metadata and interaction/behavior manifests. Behavior text is stored as creator-authored metadata; runtime AI/behavior execution is not implied.
5. Audio — FFmpeg processing and procedural/original sound assets; no speech synthesis model.
6. Gameplay — movement, camera, interactions, objectives, checkpoints, saves and win/lose flow generated from creator-authored mission data.
7. Assembly & QA — register GLB assets, generate game config, assemble the playable Godot project, validate references and package exports.

## Runtime and services

- Creator: React, Vite and TypeScript; creator brief, upload, proportion/face-crop controls, stage cards, GLB preview, approve/regenerate actions and project library.
- Preview: Three.js GLTFLoader and OrbitControls.
- Asset tools: FFmpeg/FFprobe and Blender Python API.
- Game runtime: existing Godot assembler and validation pipeline. Three.js remains available for browser previews and future runtime work.
- API: FastAPI with project-scoped media and generated-asset storage.

## Rights, safety and provenance

- Require photo rights, likeness consent and original-assets-only confirmation before processing.
- Movie rights are required only when a clip is used.
- Treat video links as untrusted input; reject private-network, localhost, file and unsupported schemes. Enforce download limits, timeouts and redirect revalidation before URL ingestion is enabled.
- Validate upload signatures, MIME type, duration, dimensions and size. Store originals outside the public web root with project-scoped access.
- Provide deletion of originals, derived artifacts and job metadata before production release.
- Do not claim a procedural avatar is a photorealistic reconstruction. A single photograph cannot reveal hidden anatomy; creator-adjustable proportions and a manual face-crop control are explicit.
- Maintain an asset provenance manifest: source stage, generator/version, parameters and content hash.

## Delivery gates

A stage is complete only when its artifacts are present, previewable and validated. Final output is not marked playable until asset references resolve, runtime boots, controls work, mission completion/failure flows pass and automated smoke tests report no uncaught errors. Blender generation must be exercised against supported Blender versions before claiming the actual GLB pipeline is production-validated. APK export additionally requires Android SDK/Gradle tooling and a configured signing key; signing secrets must never be committed.

## Implementation sequence

1. Stage state machine, creator story contract, rights declarations and resumable project manifest.
2. Secure photo/video ingestion and local FFmpeg media inspection.
3. Creator brief, story persistence and approval-gated stage controls.
4. Procedural portrait-referenced player mesh, face crop, armature, weights and animation.
5. Deterministic Blender environment generation and GLB preview.
6. Procedural actor/prop/audio systems.
7. Mission compiler, Godot gameplay integration and automated QA.
8. Production storage, retention/deletion, URL-ingestion safeguards and Android export.

A directory or interface is not considered a finished subsystem. Do not claim Blender-generated assets have been executed or validated until a real Blender build has completed.
