# Nexora Foundry — technical research library

**Studio:** NEXORA Interactive Studios  
**Product:** Nexora Foundry  
**Repository:** `musombi123/Procedural-Game-Foundry`  
**Evidence snapshot:** 25 November 2026  
**Purpose:** Founder study, engineering handover, partner evaluation and technical due diligence.

This repository contains the game-production engine and local compute foundation behind Nexora Foundry. It is the technical core of the wider NEXORA product, not the Windows Tauri host and not the separate React workspace.

## Read in order

1. [System architecture](SYSTEM-ARCHITECTURE.md) — core components, data flow, local/cloud split and repository map.
2. [Production pipeline and technology](PRODUCTION-PIPELINE-AND-TECHNOLOGY.md) — FPD, procedural generation, Blender, Godot, assets, audio and creator approval stages.
3. [Readiness, security and research risks](READINESS-SECURITY-AND-RESEARCH-GAPS.md) — implemented surfaces, outstanding acceptance gates, data rights and claims that must not be made prematurely.

## NEXORA source boundaries

| Repository | What it owns |
|---|---|
| `Procedural-Game-Foundry` | FastAPI Foundry Core, project engine, generation, validation, Blender/Godot pipeline, asset registry and Local Agent |
| `RevelaCode-Frontend/apps/nexora` | Creator-facing NEXORA React/Vite workspace |
| `Nexora_Windows` | Tauri 2 Windows desktop host and Windows installer workflow |

The repositories are connected by build and API contracts. They must not be described as one monolithic codebase.

## Evidence labels

- **In main:** present in the inspected default-branch source.
- **Declared implemented:** the project README or roadmap says implementation exists; verify the exact commit and test before claiming it is accepted.
- **Acceptance pending:** implementation exists but creator, device or release testing is not complete.
- **Feature branch:** work described in a phase tracker may not be merged into `main`.
- **Planned:** a documented future capability.

The presence of a test file does not prove the test has passed. A green CI run proves only the checks it executes. A synthetic fixture does not prove real creator quality.

## Product identity and independence

The NEXORA Studio Charter identifies **NEXORA Interactive Studios** as the studio and **Nexora Foundry** as its flagship product. It says NEXORA is operationally separate from RevelaCode. Any future technology sharing, distribution or sponsorship with RevelaCode should be explicit and documented.

See also the [NEXORA partnership library](https://github.com/musombi123/Nexora_Windows/tree/main/docs/research).
