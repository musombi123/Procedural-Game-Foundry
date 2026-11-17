# Third-party software license register

This file is the required provenance register. It is intentionally conservative: an entry marked REVIEW REQUIRED is not approved for production or commercial distribution until a maintainer records the exact version, weight source, license text and any use restrictions.

| Component | Intended role | Software/weight license status | Release gate |
|---|---|---|---|
| Python / FastAPI / Pydantic | API | Permissive upstream licenses; pin exact versions | Record versions in SBOM |
| FFmpeg | Media decoding | LGPL/GPL build-dependent | Use an LGPL-compatible build or disclose GPL obligations |
| PySceneDetect | Scene segmentation | BSD-3-Clause | Pin version |
| Blender | Mesh processing and rigging | GPL-2.0-or-later | Keep Blender as external executable; comply with distribution terms |
| Godot | Existing native game export | MIT | Include copyright/license notice |
| Three.js | Browser 3D runtime | MIT | Include notice |
| React / Vite | Creator UI | MIT | Include notices |
| Rapier | Physics | Apache-2.0 or MIT depending on package | Pin exact package and license |
| Howler.js | Audio playback | MIT | Include notice |
| Capacitor | Android packaging | MIT | Include notices |
| Playwright | Browser QA | Apache-2.0 | Pin version |

The current movie-to-game path uses local software tools and deterministic procedural geometry only. It does not load neural model weights or call inference services. The release pipeline must still record licenses for software, textures, audio, fonts and any third-party assets.
