import { useCallback, useEffect, useState } from "react";

type StageState = "LOCKED" | "READY" | "RUNNING" | "REVIEW" | "APPROVED" | "FAILED";
type Stage = { stage: string; state: StageState; revision: number; progress: number; summary: string; output: Record<string, unknown>; error?: string | null };
type Pipeline = { project_id: string; active_stage: string; stages: Stage[]; source_photo?: { filename: string; size_bytes: number } | null; source_video?: { filename: string; size_bytes: number } | null };
type Props = { projectId: string; api: string };
const stageNames: Record<string, string> = {
  analysis: "01 · Film analysis & storyboard", player: "02 · Player character", environment: "03 · Environments",
  actors_props: "04 · Enemies, NPCs & props", audio: "05 · Music & sound", gameplay: "06 · Gameplay systems", assembly: "07 · Assembly & QA"
};
const statusColor: Record<StageState, string> = { LOCKED: "#778397", READY: "#67b9ef", RUNNING: "#d9b56d", REVIEW: "#b69af2", APPROVED: "#7ec79c", FAILED: "#e17c7c" };

export default function MoviePipelinePanel({ projectId, api }: Props) {
  const [pipeline, setPipeline] = useState<Pipeline | null>(null);
  const [rights, setRights] = useState([false, false, false, false]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("Loading production pipeline…");
  const [story, setStory] = useState<Record<string, any> | null>(null);
  const refresh = useCallback(async () => {
    try {
      const response = await fetch(api + "/api/projects/" + projectId + "/movie-pipeline");
      if (response.status === 404) { setPipeline(null); setMessage("No movie-to-game pipeline created for this project yet."); return; }
      if (!response.ok) throw new Error("Could not load pipeline");
      const loaded = await response.json() as Pipeline;
      setPipeline(loaded);
      const analysis = loaded.stages.find(stage => stage.stage === "analysis");
      if (analysis?.output?.story_manifest) {
        const storyResponse = await fetch(api + "/api/projects/" + projectId + "/movie-pipeline/stages/analysis/intelligence");
        if (storyResponse.ok) { const saved = await storyResponse.json(); setStory(saved.story ?? null); }
      } else setStory(null);
      setMessage("Pipeline manifest loaded · stage approvals are persisted");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Pipeline unavailable"); }
  }, [api, projectId]);
  useEffect(() => { void refresh(); }, [refresh]);
  async function create() {
    setBusy(true);
    try {
      const response = await fetch(api + "/api/projects/" + projectId + "/movie-pipeline", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rights: { has_video_rights: rights[0], has_photo_rights: rights[1], likeness_consent: rights[2], accepts_original_assets_only: rights[3] } })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? "Could not create pipeline");
      setPipeline(data as Pipeline); setMessage("Production stages created. Upload the portrait and movie to begin.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Pipeline creation failed"); }
    finally { setBusy(false); }
  }
  async function uploadInput(kind: "photo" | "video", file?: File) {
    if (!file) return;
    setBusy(true);
    try {
      const form = new FormData(); form.append("file", file);
      const response = await fetch(api + "/api/projects/" + projectId + "/movie-pipeline/source/" + kind, { method: "POST", body: form });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? "Upload failed");
      await refresh(); setMessage(kind === "photo" ? "Player portrait uploaded and verified" : "Movie uploaded and verified");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Upload failed"); }
    finally { setBusy(false); }
  }
  async function runAnalysis() {
    setBusy(true);
    try {
      const response = await fetch(api + "/api/projects/" + projectId + "/movie-pipeline/stages/analysis/run", { method: "POST" });
      const queued = await response.json();
      if (!response.ok) throw new Error(queued.detail ?? "Could not start media analysis");
      setMessage("Local media analysis running · extracting metadata and keyframes…");
      for (let attempt = 0; attempt < 240; attempt++) {
        await new Promise(resolve => window.setTimeout(resolve, 1500));
        const jobResponse = await fetch(api + "/api/jobs/" + queued.id);
        if (!jobResponse.ok) throw new Error("Could not read media analysis job status");
        const job = await jobResponse.json();
        if (job.state === "COMPLETED") {
          await refresh();
          setMessage(job.message ?? "Media analysis ready for creator review");
          return;
        }
        if (job.state === "FAILED") throw new Error(job.error ?? "Media analysis failed");
      }
      setMessage("Analysis is still running in the background. Refresh this panel to inspect the stage state.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Media analysis failed"); await refresh(); }
    finally { setBusy(false); }
  }
  async function runIntelligence() {
    setBusy(true);
    try {
      const response = await fetch(api + "/api/projects/" + projectId + "/movie-pipeline/stages/analysis/intelligence/run", { method: "POST" });
      const queued = await response.json();
      if (!response.ok) throw new Error(queued.detail ?? "Could not start local intelligence");
      setMessage("Local vision model is examining keyframes; story planner will build the original game proposal…");
      for (let attempt = 0; attempt < 240; attempt++) {
        await new Promise(resolve => window.setTimeout(resolve, 1500));
        const jobResponse = await fetch(api + "/api/jobs/" + queued.id);
        if (!jobResponse.ok) throw new Error("Could not read intelligence job status");
        const job = await jobResponse.json();
        if (job.state === "COMPLETED") {
          const resultResponse = await fetch(api + "/api/projects/" + projectId + "/movie-pipeline/stages/analysis/intelligence");
          const result = await resultResponse.json();
          if (!resultResponse.ok) throw new Error(result.detail ?? "Could not load generated story");
          setStory(result.story);
          await refresh();
          setMessage(job.message ?? "Original story proposal is ready for review");
          return;
        }
        if (job.state === "FAILED") throw new Error(job.error ?? "Local intelligence failed");
      }
      setMessage("Intelligence is still running. Refresh the pipeline later to inspect its state.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Local intelligence failed"); }
    finally { setBusy(false); }
  }
  async function saveStory() {
    if (!story) return;
    setBusy(true);
    try {
      const response = await fetch(api + "/api/projects/" + projectId + "/movie-pipeline/stages/analysis/intelligence", {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ story })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? "Could not save story edits");
      setStory(data.story); setMessage("Creator edits saved to the project storyboard");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not save story edits"); }
    finally { setBusy(false); }
  }
  async function stageAction(stage: string, action: "approve" | "regenerate") {
    setBusy(true);
    try {
      const response = await fetch(api + "/api/projects/" + projectId + "/movie-pipeline/stages/" + stage + "/" + action, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ note: "Approved in creator studio" })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? "Stage update failed");
      setPipeline(data as Pipeline); setMessage("Stage state saved");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Stage update failed"); }
    finally { setBusy(false); }
  }
  return <section style={{ marginTop: 24, padding: 22, border: "1px solid #2c3b50", borderRadius: 16, background: "#101a29", color: "#e8eef7" }}>
    <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
      <div><small style={{ color: "#91a9c4", letterSpacing: 1.2 }}>NEW PRODUCTION WORKFLOW</small><h2 style={{ margin: "6px 0" }}>Movie → playable game</h2><p style={{ margin: 0, color: "#a9b8c9" }}>One player portrait + one authorized movie. Seven review-gated stages.</p></div>
      <span style={{ fontSize: 12, color: "#9fb5ca" }}>LOCAL-FIRST · NO PAID APIs</span>
    </div>
    {!pipeline ? <div style={{ marginTop: 18 }}>
      <p style={{ color: "#c1cedc" }}>Before enabling processing, confirm all four rights and originality requirements:</p>
      {["I own or have permission to use the movie video.", "I own or have permission to use the portrait photo.", "I have consent to use the depicted person's likeness.", "I agree the game will use original inspired assets, not copied footage, music, logos or exact character designs."].map((label, index) => <label key={index} style={{ display: "flex", gap: 10, margin: "11px 0", color: "#c8d4e1", fontSize: 14 }}><input type="checkbox" checked={rights[index]} onChange={(event) => setRights(current => current.map((value, i) => i === index ? event.target.checked : value))}/>{label}</label>)}
      <button disabled={busy || rights.some(value => !value)} onClick={create} style={{ marginTop: 8, border: 0, borderRadius: 8, padding: "11px 16px", background: "#2878bb", color: "white", fontWeight: 700, cursor: "pointer", opacity: busy || rights.some(value => !value) ? .5 : 1 }}>Create staged pipeline</button>
    </div> : <div style={{ marginTop: 18, display: "grid", gap: 10 }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 12, marginBottom: 6 }}>
        <label style={{ padding: 13, border: "1px dashed #49627d", borderRadius: 10, color: "#c5d4e4", fontSize: 13 }}>PLAYER PORTRAIT · FULL BODY
          <input type="file" accept="image/jpeg,image/png,image/webp" disabled={busy || !!pipeline.source_photo} onChange={event => void uploadInput("photo", event.target.files?.[0])} style={{ display: "block", marginTop: 9, maxWidth: "100%" }}/>
          <small style={{ display: "block", marginTop: 6, color: pipeline.source_photo ? "#7ec79c" : "#9fb0c4" }}>{pipeline.source_photo ? pipeline.source_photo.filename : "JPEG, PNG or WebP · max 20 MB"}</small>
        </label>
        <label style={{ padding: 13, border: "1px dashed #49627d", borderRadius: 10, color: "#c5d4e4", fontSize: 13 }}>MOVIE VIDEO · FULL FILM OR CLIP
          <input type="file" accept="video/mp4,video/quicktime,video/x-matroska,video/webm,video/x-msvideo" disabled={busy || !!pipeline.source_video} onChange={event => void uploadInput("video", event.target.files?.[0])} style={{ display: "block", marginTop: 9, maxWidth: "100%" }}/>
          <small style={{ display: "block", marginTop: 6, color: pipeline.source_video ? "#7ec79c" : "#9fb0c4" }}>{pipeline.source_video ? pipeline.source_video.filename : "MP4, MOV, MKV, WebM or AVI · max 8 GB"}</small>
        </label>
      </div>
      {pipeline.stages.map((stage) => <article key={stage.stage} style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", flexWrap: "wrap", padding: 13, border: "1px solid #2b3a4e", borderRadius: 10, background: "#142235" }}>
        <div style={{ minWidth: 180, flex: 1 }}><b>{stageNames[stage.stage] ?? stage.stage}</b><div style={{ fontSize: 12, color: "#9fb0c4", marginTop: 5 }}>{stage.summary} · revision {stage.revision + 1}</div>{stage.error && <div style={{ color: "#ef9696", fontSize: 12 }}>{stage.error}</div>}</div>
        <span style={{ color: statusColor[stage.state], fontSize: 11, fontWeight: 800, letterSpacing: .8 }}>{stage.state}</span>
        {stage.stage === "analysis" && stage.state === "READY" && pipeline.source_photo && pipeline.source_video && <button disabled={busy} onClick={() => void runAnalysis()}>Run local analysis</button>}
        {stage.stage === "analysis" && stage.state === "REVIEW" && <button disabled={busy} onClick={() => void runIntelligence()}>Generate story & missions with local AI</button>}
        {stage.state === "REVIEW" && <button disabled={busy} onClick={() => stageAction(stage.stage, "approve")}>Approve</button>}
        {["REVIEW", "FAILED", "APPROVED"].includes(stage.state) && <button disabled={busy} onClick={() => stageAction(stage.stage, "regenerate")}>Regenerate</button>}
      </article>)}
      {story && <article style={{ padding: 16, border: "1px solid #49627d", borderRadius: 12, background: "#0d1725", display: "grid", gap: 9 }}>
        <h3 style={{ margin: "0 0 2px" }}>Editable game brief</h3>
        <label>Game title<input value={story.title ?? ""} onChange={event => setStory((current: any) => current ? { ...current, title: event.target.value } : current)} style={{ display: "block", width: "100%", marginTop: 4 }}/></label>
        <label>Logline<textarea value={story.logline ?? ""} onChange={event => setStory((current: any) => current ? { ...current, logline: event.target.value } : current)} rows={2} style={{ display: "block", width: "100%", marginTop: 4 }}/></label>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", fontSize: 12, color: "#9fb0c4" }}><span>{story.genre}</span><span>· {story.missions?.length ?? 0} missions</span><span>· {story.level_progression?.length ?? 0} levels</span></div>
        {story.player_character && <p style={{ margin: 0, color: "#b8c8d9" }}><b>Player:</b> {story.player_character.name} — {story.player_character.role}. {story.player_character.visual_design}</p>}
        <h4 style={{ marginBottom: 0 }}>Mission outline</h4>
        {(story.missions ?? []).map((mission: any, index: number) => <div key={mission.id ?? index} style={{ display: "grid", gap: 4 }}>
          <input aria-label={"Mission " + (index + 1) + " title"} value={mission.title ?? ""} onChange={event => setStory((current: any) => current ? { ...current, missions: current.missions.map((item: any, i: number) => i === index ? { ...item, title: event.target.value } : item) } : current)}/>
          <textarea aria-label={"Mission " + (index + 1) + " objective"} rows={2} value={mission.objective ?? ""} onChange={event => setStory((current: any) => current ? { ...current, missions: current.missions.map((item: any, i: number) => i === index ? { ...item, objective: event.target.value } : item) } : current)}/>
        </div>)}
        <h4 style={{ marginBottom: 0 }}>Level progression</h4>
        {(story.level_progression ?? []).map((level: any, index: number) => <div key={level.level ?? index} style={{ display: "grid", gap: 4 }}>
          <input aria-label={"Level " + (index + 1) + " name"} value={level.name ?? ""} onChange={event => setStory((current: any) => current ? { ...current, level_progression: current.level_progression.map((item: any, i: number) => i === index ? { ...item, name: event.target.value } : item) } : current)}/>
          <textarea aria-label={"Level " + (index + 1) + " challenge"} rows={2} value={level.primary_challenge ?? ""} onChange={event => setStory((current: any) => current ? { ...current, level_progression: current.level_progression.map((item: any, i: number) => i === index ? { ...item, primary_challenge: event.target.value } : item) } : current)}/>
        </div>)}
        <button disabled={busy} onClick={() => void saveStory()}>Save creator edits</button>
        <small style={{ color: "#e3c58b" }}>AI-generated proposal · creator edits are saved before stage approval and asset production</small>
      </article>}
      <p style={{ margin: "6px 0 0", color: "#e3c58b", fontSize: 13 }}>Media worker: FFmpeg / FFprobe analysis runs locally when installed. Both source inputs are required. Vision and story synthesis use local Ollama models; generated assets remain a separate production stage.</p>
    </div>}
    <p aria-live="polite" style={{ margin: "14px 0 0", color: "#9fb0c4", fontSize: 12 }}>{message}</p>
  </section>;
}
