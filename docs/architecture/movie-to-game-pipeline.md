# Movie-to-Game Pipeline

## Product contract

PGF accepts exactly two creative inputs: (1) one full-body player portrait and (2) one user-authorized movie or clip. The video is an analysis reference only. Generated characters, environments, props, dialogue, music and effects must be original and must not reproduce protected footage, soundtrack, logos or exact character designs.

The pipeline is human-gated. Every stage produces versioned artifacts and enters REVIEW. The creator must approve it before the next stage becomes READY. Regenerating a stage invalidates its downstream approvals and outputs. Jobs must be resumable; no stage may silently skip a missing dependency.

## Stages

1. Analysis — FFmpeg media metadata/audio/frame extraction, PySceneDetect scene boundaries and representative keyframes, faster-whisper transcript, local vision-language descriptions, local LLM design brief, mission outline, enemy/prop inventory and storyboard.
2. Player — consented portrait conditioning, stylized turnaround, image-to-mesh, Blender cleanup/UV/texture, auto-rig and retargeted licensed motion clips.
3. Environment — art direction lock, procedural modular level geometry, original materials/sky, image-to-3D props and scene layout.
4. Actors & props — original NPC/enemy/weapon/item assets, rigging, collision and metadata.
5. Audio — original music and sound effects, optional locally synthesized voice lines.
6. Gameplay — populate the reusable game core with movement, camera, combat, HUD, objectives, checkpoints, saves and win/lose flow from the approved mission data.
7. Assembly & QA — register GLB assets, generate game config, build web runtime, run deterministic smoke/playwright checks, validate references and package exports.

## Runtime and services

- Creator: React, Vite, TypeScript, Tailwind; stage cards, 3D previews, approve/regenerate/edit actions, resumable project library and WebSocket progress.
- Runtime: Three.js / React Three Fiber, Rapier, recast-navigation-js, Howler, glTF/GLB, Draco, KTX2 and LOD. Capacitor is the Android packaging route.
- API: FastAPI. Production workers: Celery + Redis. Metadata: PostgreSQL. Binary assets: MinIO (S3 API). Docker Compose is the reproducible local stack; GPU workers are optional and detected at runtime.
- Existing PGF Godot assembler remains supported while the browser runtime becomes the primary generated-game target. Do not remove working Godot export until parity is proven.

## Model policy

No paid hosted inference APIs. Providers are local adapters selected by config/models.example.yaml; model weights are downloaded by the operator and never bundled in Git. Each adapter declares model identifier, quantization, required VRAM, license URL, commercial-use status and local command. A model is unavailable until its license and weight provenance are verified. Prefer permissive, explicit licenses; do not label a community/research license as OSI open source. The platform must surface hardware requirements before a stage starts and support CPU/small quantized fallbacks where feasible.

## Data and safety

- Require affirmative declarations of rights to both uploads and consent for the depicted person's likeness before processing.
- Treat video links as untrusted input; reject private-network, localhost, file and unsupported schemes. Enforce download limits, timeouts and redirect revalidation to mitigate SSRF.
- Validate file signatures, MIME type, duration, dimensions and size. Store originals outside the public web root with project-scoped access.
- Provide deletion of originals, derived artifacts and job metadata; document retention and backups.
- Strip metadata where appropriate. Do not create a photorealistic impersonation or claim a generated model is the real person.
- Maintain an asset provenance manifest: source stage, generator, model/version, license, transformations and content hash.

## Delivery gates

A stage is complete only when its artifacts are present, previewable and validated. Final output is not marked playable until asset references resolve, runtime boots, required controls work, mission completion/failure flows pass and automated browser tests report no uncaught errors. APK export additionally requires Android SDK/Gradle tooling and a configured signing key; signing secrets must never be committed.

## Implementation sequence

1. Stage state machine, rights declarations, resumable project manifest and API contract.
2. Secure photo/video ingestion and local media-analysis worker.
3. Creator stage cards, preview/approve/regenerate flow and WebSocket events.
4. Local model adapter registry and license/hardware preflight.
5. Player asset pipeline, Blender automation and provenance manifests.
6. Procedural environment/actor/audio generation.
7. Reusable browser game core, asset registration and automated QA.
8. Docker Compose production services, MinIO/PostgreSQL/Celery/Redis and APK export.

The initial implementation deliberately does not pretend that model inference, retopology, rigging or full-game playtesting has happened when the relevant local workers are not installed.
