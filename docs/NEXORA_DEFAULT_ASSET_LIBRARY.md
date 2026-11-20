# NEXORA Default Asset Library

NEXORA installs a local starter asset pack as part of every generated Godot game build. This removes the empty-project problem for creators who describe a game in plain language and expect the first build to contain usable resources.

## Automatic selection

The local Foundry build worker reads the project name, description and genre and selects one of four original procedural packs:

| Pack | Prompt signals | Visual direction |
|---|---|---|
| Adventure | jungle, exploration, platformer, adventure | Natural environments and warm accents |
| Fantasy | wizard, magic, dragon, castle, enchanted | Enchanted woodland and magical palette |
| Sci-Fi | space, robot, alien, cyber, futuristic | Technology, dark blue and neon palette |
| Modern | city, street, urban, racing, school | Contemporary neutral palette |

If no stronger signal is found, Adventure is selected. If a project already has a pack installed, later builds preserve that pack and all existing files. Switching packs requires an explicit overwrite through the local asset-pack endpoint.

## Included resources

Each pack creates original, offline resources under `game/assets/nexora-defaults/`:

- Character starter poses: idle, run and jump SVG textures
- Environment: sky background, ground tile and platform
- Props and actors: crate, enemy and collectible gem
- UI: health heart, panel, primary/secondary buttons, play and pause icons
- Audio: jump, collect and hit effects, ambience and a short synthesized music loop
- `asset-pack.json`: asset roles, provenance, license and generated file list

A Godot helper is installed at `game/scripts/nexora_default_assets.gd` with typed loaders for character, environment and UI textures, plus an audio cue helper.

The SVGs remain editable source assets. The starter character poses are separate textures, not a skeletal rig or a finished frame-by-frame animation. Creators can replace, animate or extend them in Godot.

## Local API

- `GET /api/v1/desktop/assets/default-packs` lists the available packs.
- `POST /api/v1/desktop/projects/{project_id}/assets/default-pack` installs a selected pack on the paired computer.

Example request:

```json
{
  "pack_id": "adventure",
  "overwrite_existing": false
}
```

The route is owner-scoped and writes only inside the project's Godot folder. Overwrite is false by default; existing asset files are preserved. A different installed pack cannot be silently replaced.

## Rights and execution

The starter textures are generated from original vector geometry and the WAV files are synthesized locally. They do not fetch third-party asset packs, use external image URLs, require a model download, or consume Render compute. The generated pack is marked CC0-1.0. Godot imports the SVG and WAV resources locally.

This is a useful default starter kit, not a claim that every prompt can be fully art-directed from generic assets. Specialized characters, detailed 3D models, custom animation, voice acting and genre-specific art still require creator assets or additional local generation and review.
