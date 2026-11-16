# Third-party software and model license register

This file is the required provenance register. It is intentionally conservative: an entry marked REVIEW REQUIRED is not approved for production or commercial distribution until a maintainer records the exact version, weight source, license text and any use restrictions.

| Component | Intended role | Software/weight license status | Release gate |
|---|---|---|---|
| Python / FastAPI / Pydantic | API | Permissive upstream licenses; pin exact versions | Record versions in SBOM |
| FFmpeg | Media decoding | LGPL/GPL build-dependent | Use an LGPL-compatible build or disclose GPL obligations |
| PySceneDetect | Scene segmentation | BSD-3-Clause | Pin version |
| faster-whisper | Transcription | MIT software; model weights have separate terms | Record selected Whisper model terms |
| Ollama | Local model serving | MIT software; each model has its own license | Verify model card and weight provenance |
| Qwen2.5-VL / Qwen text models | Local vision and planning | Model-specific terms; verify exact release | REVIEW REQUIRED |
| Stable Diffusion XL | Image generation | OpenRAIL++ license, not OSI open source | REVIEW REQUIRED; honor use restrictions |
| TripoSR | Image-to-3D | MIT code; checkpoint provenance/license must be verified | REVIEW REQUIRED |
| Blender | Mesh processing and rigging | GPL-2.0-or-later | Keep Blender as external executable; comply with distribution terms |
| Godot | Existing native game export | MIT | Include copyright/license notice |
| Three.js | Browser 3D runtime | MIT | Include notice |
| React / Vite | Creator UI | MIT | Include notices |
| Rapier | Physics | Apache-2.0 or MIT depending on package | Pin exact package and license |
| Howler.js | Audio playback | MIT | Include notice |
| Capacitor | Android packaging | MIT | Include notices |
| Playwright | Browser QA | Apache-2.0 | Pin version |

A library's source-code license does not automatically cover model weights, datasets, generated outputs, fonts, textures, motion-capture data or downloaded assets. The release pipeline must scan and record each independently. Never describe this stack as entirely open source until all selected model weights and assets pass review.
