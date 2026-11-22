import { useEffect, useMemo, useState } from "react";
import { localAgentFetch } from "./localAgentFetch";
import WorldEditor from "./WorldEditor";
import MoviePipelinePanel from "./MoviePipelinePanel";
import AssetCollectionCenter from "./AssetCollectionCenter";
import InternalIDE from "./InternalIDE";
import MonetizationCenter from "./MonetizationCenter";
import StudioSponsorSlot from "./StudioSponsorSlot";
import GuidedTour from "./GuidedTour";
import PCConnectionCard from "./PCConnectionCard";
import CommandPalette from "./CommandPalette";
import ShortcutsHelp from "./ShortcutsHelp";
import type { ObjectKind, SceneObject, TerrainEdit, WorldDocument } from "./types";

type Project = { id: string; project: { name: string; genre: string; dimension: string; seed: number } };
const API = (import.meta.env.VITE_PGF_API ?? "http://127.0.0.1:8765/engine").replace(/\/$/, "");
const initialWorld = (seed: number): WorldDocument => ({
  seed,
  world: { width: 96, depth: 96, resolution: 64, amplitude: 9, frequency: 0.055, biomes: ["rocky-desert", "alien-forest"], weather: true },
  objects: [], terrain_edits: [], sun_angle: -28, fog: true, water_level: -1.5
});
const labels: Record<ObjectKind, string> = { outpost: "Outpost", beacon: "Signal beacon", tree: "Alien tree", rock: "Rock formation", crate: "Cargo crate" };
const colors: Record<ObjectKind, string> = { outpost: "#819db9", beacon: "#5b8da8", tree: "#4c846f", rock: "#8d8b84", crate: "#b18a5f" };
type WorldPatch = Partial<Omit<WorldDocument, "world">> & { world?: Partial<WorldDocument["world"]> };

export default function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [name, setName] = useState("Lost Planet");
  const [selected, setSelected] = useState("");
  const [view, setView] = useState<"workspace" | "world" | "scene" | "ide" | "monetization">("workspace");
  const [world, setWorld] = useState<WorldDocument>(initialWorld(784215));
  const [selectedObject, setSelectedObject] = useState("");
  const [placementType, setPlacementType] = useState<ObjectKind | null>(null);
  const [sculptMode, setSculptMode] = useState<TerrainEdit["operation"] | null>(null);
  const [brushRadius, setBrushRadius] = useState(8);
  const [brushStrength, setBrushStrength] = useState(2.5);
  const [mode, setMode] = useState<"edit" | "play">("edit");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("Connecting to local Foundry Core…");
  const [loadedProjectId, setLoadedProjectId] = useState("");
  const [saveStatus, setSaveStatus] = useState("All changes saved");
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const selectedProject = useMemo(() => projects.find((project) => project.id === selected), [projects, selected]);
  const activeObject = useMemo(() => world.objects.find((item) => item.id === selectedObject), [world.objects, selectedObject]);

  async function refresh() {
    try {
      const response = await localAgentFetch(API + "/api/projects");
      if (!response.ok) throw new Error("API returned " + response.status);
      const data = await response.json() as Project[];
      setProjects(data);
      setStatus("Foundry Core connected · " + data.length + " project(s)");
    } catch {
      setStatus("Preview ready · start Foundry Core to save and build projects");
    }
  }
  async function loadWorld(projectId: string) {
    try {
      const response = await localAgentFetch(API + "/api/projects/" + projectId + "/world");
      if (!response.ok) throw new Error("World load unavailable");
      const document = await response.json() as WorldDocument;
      setWorld({ ...document, terrain_edits: document.terrain_edits ?? [] });
      setLoadedProjectId(projectId);
      setSaveStatus("All changes saved");
      setSelectedObject("");
      setStatus("World loaded · seed " + document.seed);
    } catch {
      const project = projects.find((item) => item.id === projectId);
      setWorld(initialWorld(project?.project.seed ?? 784215));
      setLoadedProjectId(projectId);
      setSaveStatus("Offline · local recovery copy only");
      setStatus("Local preview active · API unavailable");
    }
  }
  useEffect(() => { void refresh(); }, []);

  function changeProject(projectId: string) {
    setSelected(projectId);
    setView("world");
    void loadWorld(projectId);
  }
  async function createProject(returnToWorkspace = false) {
    if (!name.trim()) return;
    setBusy(true);
    try {
      const response = await localAgentFetch(API + "/api/projects", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, genre: "science-fiction", dimension: "3d", seed: Math.floor(Math.random() * 1000000) })
      });
      if (!response.ok) throw new Error((await response.json()).detail ?? "Project creation failed");
      const project = await response.json() as Project;
      await refresh();
      setProjects((current) => current.some((item) => item.id === project.id) ? current : [project, ...current]);
      setSelected(project.id);
      setWorld(initialWorld(project.project.seed));
      setLoadedProjectId(project.id);
      setSaveStatus("All changes saved");
      setView(returnToWorkspace ? "workspace" : "world");
      setStatus("Project created · add your source video to begin");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Project creation failed");
    } finally { setBusy(false); }
  }
  useEffect(() => {
    if (!selected || loadedProjectId !== selected) return;
    const snapshot = JSON.stringify(world);
    try { localStorage.setItem("nexora:world-recovery:" + selected, snapshot); } catch { /* local cache is best effort */ }
    setSaveStatus("Saving changes…");
    const timer = window.setTimeout(async () => {
      try {
        const response = await localAgentFetch(API + "/api/projects/" + encodeURIComponent(selected) + "/world", {
          method: "PUT", headers: { "Content-Type": "application/json" }, body: snapshot
        });
        if (!response.ok) throw new Error("Local project save failed");
        setSaveStatus("All changes saved");
      } catch {
        setSaveStatus("Recovery copy saved in this browser · reconnect to sync to the PC project folder");
      }
    }, 900);
    return () => window.clearTimeout(timer);
  }, [selected, loadedProjectId, world]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault(); setPaletteOpen(value => !value);
      } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault(); void saveWorld();
      } else if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
        event.preventDefault(); setView("world"); setMode("play");
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  });

  function updateWorld(patch: WorldPatch) {
    setWorld((current) => ({ ...current, ...patch, world: { ...current.world, ...(patch.world ?? {}) } }));
  }
  function placeObject(kind: ObjectKind, x: number, z: number) {
    const item: SceneObject = {
      id: "obj-" + Math.random().toString(36).slice(2, 10),
      name: labels[kind] + " " + (world.objects.filter((object) => object.kind === kind).length + 1),
      kind, x: Math.round(x * 10) / 10, y: 0, z: Math.round(z * 10) / 10,
      rotation: 0, scale: 1, color: colors[kind]
    };
    setWorld((current) => ({ ...current, objects: [...current.objects, item] }));
    setSelectedObject(item.id);
    setPlacementType(null);
    setStatus(item.name + " placed · scene updated");
  }
  function updateObject(patch: Partial<SceneObject>) {
    if (!selectedObject) return;
    setWorld((current) => ({ ...current, objects: current.objects.map((item) => item.id === selectedObject ? { ...item, ...patch } : item) }));
  }
  function sculptTerrain(x: number, z: number) {
    const edit: TerrainEdit = { id: "sculpt-" + Math.random().toString(36).slice(2, 10), operation: sculptMode ?? "raise", x: Math.round(x*10)/10, z: Math.round(z*10)/10, radius: brushRadius, strength: brushStrength };
    setWorld((current) => ({ ...current, terrain_edits: [...(current.terrain_edits ?? []), edit] }));
    setStatus(edit.operation + " stroke applied · terrain updated");
  }
  async function saveWorld() {
    if (!selected) { setStatus("Create or select a project before saving this world"); return; }
    setBusy(true);
    try {
      const response = await localAgentFetch(API + "/api/projects/" + selected + "/world", {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(world)
      });
      if (!response.ok) throw new Error((await response.json()).detail ?? "Save failed");
      setStatus("Scene saved · " + world.objects.length + " placed object(s)");
    } catch {
      setStatus("Preview updated locally · Foundry API is required to persist this scene");
    } finally { setBusy(false); }
  }
  async function generateGame() {
    if (!selected) { setStatus("Create or select a project first"); return; }
    setBusy(true);
    try {
      const saveResponse = await localAgentFetch(API + "/api/projects/" + selected + "/world", {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(world)
      });
      if (!saveResponse.ok) throw new Error("Could not save the scene before generation");
      const response = await localAgentFetch(API + "/api/projects/" + selected + "/generate", { method: "POST" });
      if (!response.ok) throw new Error("Generation request failed");
      const job = await response.json() as { id: string };
      let done = false;
      while (!done) {
        await new Promise((resolve) => window.setTimeout(resolve, 850));
        const current = await (await localAgentFetch(API + "/api/jobs/" + job.id)).json();
        setStatus(current.progress + "% · " + current.message);
        if (["COMPLETED", "FAILED"].includes(current.state)) {
          done = true;
          setStatus(current.state + " · " + (current.error ?? current.message));
        }
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Generation failed");
    } finally { setBusy(false); }
  }
  function rotateSelected(amount: number) {
    if (activeObject) updateObject({ rotation: (activeObject.rotation + amount + 360) % 360 });
  }

  const worldView = view === "world" || view === "scene";
  return <main className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="#" onClick={(event) => { event.preventDefault(); setView("workspace"); }}>
        <span className="brand-mark">PGF</span><span><b>PROCEDURAL</b><small>GAME FOUNDRY</small></span>
      </a>
      <div className="side-label">WORKSPACE</div>
      <button className={view === "workspace" ? "side-link active" : "side-link"} onClick={() => setView("workspace")}><span>▦</span> Overview</button>
      <button data-tour="world-nav" className={view === "world" ? "side-link active" : "side-link"} onClick={() => { setMode("edit"); setView("world"); }}><span>◈</span> World Foundry</button>
      <button className={view === "scene" ? "side-link active" : "side-link"} onClick={() => { setMode("edit"); setView("scene"); }}><span>⬡</span> Scene Editor</button>
      <button className={view === "ide" ? "side-link active" : "side-link"} disabled={!selected} onClick={() => setView("ide")}><span>⌘</span> Internal IDE</button>
      <button data-tour="monetization" className={view === "monetization" ? "side-link active" : "side-link"} disabled={!selected} onClick={() => setView("monetization")}><span>◇</span> Monetization</button>
      <button data-tour="help-nav" className="side-link" onClick={() => setShortcutsOpen(true)}><span>?</span> Help &amp; Shortcuts</button>
      <div className="sidebar-bottom"><span className="status-led" /> MODEL-FREE ENGINE <small>LOCAL-FIRST GENERATION</small></div>
    </aside>

    <section className="main-pane">
      <header className="topbar">
        <div><small>PROCEDURAL GAME FOUNDRY / {view === "monetization" ? "CREATOR REVENUE" : view === "ide" ? "INTERNAL IDE" : worldView ? (view === "world" ? "WORLD FOUNDRY" : "SCENE EDITOR") : "PROJECT WORKSPACE"}</small>
          <h1>{view === "ide" ? "Edit the game itself." : view === "monetization" ? "Turn play into value." : worldView ? (view === "world" ? "Shape a living world." : "Build the scene.") : "Build worlds. Make games."}</h1>
          <p>{view === "ide" ? "A local source workspace connected to your paired NEXORA computer." : view === "monetization" ? "Configure optional revenue modules for your game, with privacy and platform requirements built in." : worldView ? "A shared live viewport for terrain generation, environment authoring and scene composition." : "Deterministic creation tools for real, playable 2D and 3D games."}</p>
        </div>
        <div className="top-actions"><span className="connection">{status} · {saveStatus}</span><button className="button secondary" onClick={() => setShortcutsOpen(true)}>Shortcuts</button>{worldView && <button className="button secondary" disabled={busy} onClick={saveWorld}>Save scene</button>}</div>
      </header>

      {view === "workspace" ? <>
        <section className="welcome-card" data-tour="workspace-home">
          <div><span className="eyebrow">FOUNDRY CORE · 0.2</span><h2>Your next universe<br/>starts here.</h2>
            <p>Build terrain from a seed, arrange the environment, then enter it through a first-person controller. No generative model or paid asset pipeline required.</p>
            <div className="create-row"><input value={name} onChange={(event) => setName(event.target.value)} aria-label="Project name" placeholder="Project name"/><button className="button primary" disabled={busy || !name.trim()} onClick={createProject}>＋ New project</button></div>
          </div><div className="planet-art"><span /></div>
        </section>
        <PCConnectionCard onConnected={() => { void refresh(); }} />
        {!selected && <div className="tour-upload-placeholder" data-tour="upload-video"><b>Ready to add your video?</b><p>Create a project first. The video upload panel appears inside the project workspace.</p><button className="button primary" disabled={busy} onClick={() => void createProject(true)}>＋ Create a project to add video</button></div>}
        <div className="section-heading"><div><small>YOUR WORK</small><h2>Projects</h2></div><button className="button secondary" onClick={refresh}>↻ Refresh</button></div>
        <div className="project-grid">
          {projects.map((project) => <button key={project.id} className={selected === project.id ? "project-card chosen" : "project-card"} onClick={() => changeProject(project.id)}>
            <span className="project-icon">◉</span><b>{project.project.name}</b><small>{project.project.genre} · {project.project.dimension}D · seed {project.project.seed}</small><span className="card-open">Open project →</span>
          </button>)}
          {!projects.length && <div className="empty-state"><b>No projects yet</b><p>Create a world above. The viewport can also generate a local preview without the API.</p></div>}
        </div>
        <section className="launch-card"><div><small>SELECTED PROJECT</small><h3>{selectedProject?.project.name ?? "Choose a project"}</h3><p>Generate terrain, scene objects and a playable Godot project.</p></div><div className="launch-actions"><button className="button secondary" disabled={!selected} onClick={() => changeProject(selected)}>Open World Foundry</button><button className="button primary" disabled={busy || !selected} onClick={generateGame}>{busy ? "Working…" : "Build playable game →"}</button></div></section>
        <StudioSponsorSlot />
        {selected && <><MoviePipelinePanel projectId={selected} api={API} /><AssetCollectionCenter projectId={selected} api={API} /></>}
      </> : view === "ide" ? (selectedProject ? <InternalIDE projectId={selectedProject.id} projectName={selectedProject.project.name} /> : <div className="empty-state"><b>Select a project first</b><p>Open a project from the workspace before launching the Internal IDE.</p></div>) : view === "monetization" ? (selectedProject ? <MonetizationCenter projectId={selectedProject.id} projectName={selectedProject.project.name} /> : <div className="empty-state"><b>Select a project first</b><p>Open a project before configuring its monetization.</p></div>) : <>
        <div className="editor-toolbar" data-tour="levels">
          <div className="view-switch"><button className={view === "world" ? "selected" : ""} onClick={() => { setMode("edit"); setView("world"); }}>World Foundry</button><button className={view === "scene" ? "selected" : ""} onClick={() => { setMode("edit"); setView("scene"); }}>Scene Editor</button></div>
          <div className="toolbar-right"><span className="seed-tag">SEED {world.seed}</span>
            {mode === "play" ? <button className="button danger" onClick={() => setMode("edit")}>■ Exit world</button> : <><button className="button secondary" onClick={generateGame} disabled={busy || !selected}>{busy ? "Building…" : "Build game"}</button><button className="button primary" onClick={() => { setPlacementType(null); setSculptMode(null); setMode("play"); }}>▶ Enter world</button></>}
          </div>
        </div>
        <div className="editor-layout">
          <section className="viewport-column" data-tour="preview">
            <WorldEditor seed={world.seed} width={world.world.width} depth={world.world.depth} amplitude={world.world.amplitude}
              frequency={world.world.frequency} waterLevel={world.water_level} fog={world.fog} sunAngle={world.sun_angle}
              resolution={world.world.resolution} terrainEdits={world.terrain_edits ?? []} sculptMode={sculptMode}
              objects={world.objects} selectedId={selectedObject} mode={mode} placementType={placementType}
              onPlace={placeObject} onSelect={setSelectedObject} onSculpt={sculptTerrain}/>
            <div className="viewport-footer"><span>{world.world.width} × {world.world.depth} m world</span><span>{world.objects.length} scene objects</span><span>{world.world.resolution} grid resolution</span></div>
          </section>
          <aside className="inspector">
            {view === "world" ? <>
              <div className="panel-title"><small>WORLD FOUNDRY</small><h3>Terrain &amp; environment</h3><p>Adjust the generation recipe or sculpt the live heightfield.</p></div>
              <div className="object-list-title"><b>Terrain sculpting</b><span>{(world.terrain_edits ?? []).length} strokes</span></div>
              <div className="asset-grid">{(["raise","lower","smooth"] as const).map(tool => <button key={tool} className={sculptMode === tool ? "asset-option active" : "asset-option"} onClick={() => { setSculptMode(sculptMode === tool ? null : tool); setPlacementType(null); setMode("edit"); }}><span>{tool === "raise" ? "↗" : tool === "lower" ? "↘" : "≈"}</span>{tool}</button>)}</div>
              <label className="field-label">Brush radius <b>{brushRadius.toFixed(1)} m</b><input type="range" min="2" max="24" step="1" value={brushRadius} onChange={e=>setBrushRadius(Number(e.target.value))}/></label>
              <label className="field-label">Brush strength <b>{brushStrength.toFixed(1)}</b><input type="range" min=".2" max="8" step=".1" value={brushStrength} onChange={e=>setBrushStrength(Number(e.target.value))}/></label>
              <button className="button secondary full-width" disabled={!(world.terrain_edits ?? []).length} onClick={()=>updateWorld({terrain_edits:[]})}>Reset sculpting strokes</button>
              <label className="field-label">World seed <input type="number" value={world.seed} min={0} max={4294967295} onChange={(event) => updateWorld({ seed: Number(event.target.value) || 0 })}/></label>
              <div className="field-pair"><label className="field-label">Width <b>{world.world.width} m</b><input type="range" min="48" max="192" step="8" value={world.world.width} onChange={(event) => updateWorld({ world: { width: Number(event.target.value) } })}/></label><label className="field-label">Depth <b>{world.world.depth} m</b><input type="range" min="48" max="192" step="8" value={world.world.depth} onChange={(event) => updateWorld({ world: { depth: Number(event.target.value) } })}/></label></div>
              <label className="field-label">Terrain elevation <b>{world.world.amplitude.toFixed(1)}</b><input type="range" min="0" max="24" step=".5" value={world.world.amplitude} onChange={(event) => updateWorld({ world: { amplitude: Number(event.target.value) } })}/></label>
              <label className="field-label">Terrain roughness <b>{world.world.frequency.toFixed(3)}</b><input type="range" min=".018" max=".12" step=".001" value={world.world.frequency} onChange={(event) => updateWorld({ world: { frequency: Number(event.target.value) } })}/></label>
              <label className="field-label">Water level <b>{world.water_level.toFixed(1)} m</b><input type="range" min="-8" max="8" step=".5" value={world.water_level} onChange={(event) => updateWorld({ water_level: Number(event.target.value) })}/></label>
              <label className="field-label">Sun direction <b>{world.sun_angle}°</b><input type="range" min="-180" max="180" step="5" value={world.sun_angle} onChange={(event) => updateWorld({ sun_angle: Number(event.target.value) })}/></label>
              <label className="toggle-row"><span><b>Atmospheric fog</b><small>Depth and distance haze</small></span><input type="checkbox" checked={world.fog} onChange={(event) => updateWorld({ fog: event.target.checked })}/></label>
              <div className="inspector-note">Deterministic terrain is generated from the seed and noise parameters. Reusing the same settings recreates the same landscape.</div>
            </> : <>
              <div className="panel-title"><small>SCENE EDITOR</small><h3>Asset placement</h3><p>Select an asset, then click the terrain to place it into the scene.</p></div>
              <div className="asset-grid">{(Object.keys(labels) as ObjectKind[]).map((kind) => <button key={kind} className={placementType === kind ? "asset-option active" : "asset-option"} onClick={() => { setPlacementType(placementType === kind ? null : kind); setSculptMode(null); setMode("edit"); }}><span>{kind === "outpost" ? "⌂" : kind === "beacon" ? "⌁" : kind === "tree" ? "♣" : kind === "rock" ? "⬟" : "▣"}</span>{labels[kind]}</button>)}</div>
              <div className="object-list-title"><b>Scene objects</b><span>{world.objects.length}</span></div>
              <div className="object-list">{world.objects.map((item) => <button key={item.id} className={selectedObject === item.id ? "object-row active" : "object-row"} onClick={() => { setSelectedObject(item.id); setPlacementType(null); }}><span className="object-swatch" style={{ background: item.color }}/><span><b>{item.name}</b><small>{item.kind} · {item.x.toFixed(1)}, {item.z.toFixed(1)}</small></span><i>›</i></button>)}
                {!world.objects.length && <p className="list-empty">Your scene is empty. Pick an asset and click the terrain to place it.</p>}</div>
              {activeObject && <div className="object-inspector">
                <div className="object-list-title"><b>{activeObject.name}</b><button onClick={() => { setWorld((current) => ({ ...current, objects: current.objects.filter((item) => item.id !== activeObject.id) })); setSelectedObject(""); }}>Delete</button></div>
                <label className="field-label">Position X <b>{activeObject.x.toFixed(1)}</b><input type="range" min={-world.world.width / 2 + 2} max={world.world.width / 2 - 2} step=".5" value={activeObject.x} onChange={(event) => updateObject({ x: Number(event.target.value) })}/></label>
                <label className="field-label">Position Z <b>{activeObject.z.toFixed(1)}</b><input type="range" min={-world.world.depth / 2 + 2} max={world.world.depth / 2 - 2} step=".5" value={activeObject.z} onChange={(event) => updateObject({ z: Number(event.target.value) })}/></label>
                <label className="field-label">Scale <b>{activeObject.scale.toFixed(2)}×</b><input type="range" min=".25" max="3" step=".05" value={activeObject.scale} onChange={(event) => updateObject({ scale: Number(event.target.value) })}/></label>
                <div className="rotate-row"><span>Rotation</span><button onClick={() => rotateSelected(-15)}>−15°</button><b>{activeObject.rotation}°</b><button onClick={() => rotateSelected(15)}>＋15°</button></div>
                <button className="button secondary full-width" onClick={() => { const duplicate = { ...activeObject, id: "obj-" + Math.random().toString(36).slice(2, 10), name: activeObject.name + " copy", x: activeObject.x + 3, z: activeObject.z + 3 }; setWorld((current) => ({ ...current, objects: [...current.objects, duplicate] })); setSelectedObject(duplicate.id); }}>Duplicate object</button>
              </div>}
            </>}
          </aside>
        </div>
      </>}
      <footer className="app-footer">NEXORA · Local-first generation · Godot is the exported gameplay runtime</footer>
      <GuidedTour onStart={() => { if (!selected) void createProject(true); else setView("workspace"); }} />
      {paletteOpen && <CommandPalette selected={Boolean(selected)} onNavigate={next => { setView(next); if (next === "world" || next === "scene") setMode("edit"); }} onHelp={() => setShortcutsOpen(true)} onClose={() => setPaletteOpen(false)} />}
      {shortcutsOpen && <ShortcutsHelp onClose={() => setShortcutsOpen(false)} />}
    </section>
  </main>;
}
