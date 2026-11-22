import { useCallback, useEffect, useState } from "react";
import StoryBuilderPanel from "./StoryBuilderPanel";
import PlayerAvatarBuilder from "./PlayerAvatarBuilder";
import EnvironmentBuilder from "./EnvironmentBuilder";
import ActorsPropsBuilder from "./ActorsPropsBuilder";
import AudioFoundry from "./AudioFoundry";
import GameplayFoundry from "./GameplayFoundry";
import AssemblyFoundry from "./AssemblyFoundry";

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
  const refresh = useCallback(async () => {
    try {
      const response = await fetch(api + "/api/projects/" + projectId + "/movie-pipeline");
      if (response.status === 404) { setPipeline(null); setMessage("No movie-to-game pipeline created for this project yet."); return; }
      if (!response.ok) throw new Error("Could not load pipeline");
      setPipeline(await response.json() as Pipeline);
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
      setPipeline(data as Pipeline); setMessage("Production stages created. Add secure media ingestion and local workers to begin processing.");
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
      <div><small style={{ color: "#91a9c4", letterSpacing: 1.2 }}>NEW PRODUCTION WORKFLOW</small><h2 style={{ margin: "6px 0" }}>Movie → playable game</h2><p style={{ margin: 0, color: "#a9b8c9" }}>One player portrait + your story, an optional movie clip, or both. Seven review-gated stages.</p></div>
      <span style={{ fontSize: 12, color: "#9fb5ca" }}>LOCAL-FIRST · NO PAID APIs</span>
    </div>
    {!pipeline ? <div style={{ marginTop: 18 }}>
      <p style={{ color: "#c1cedc" }}>Before enabling processing, confirm portrait rights, likeness consent and original-asset requirements. Movie rights are required only if you select movie-first or guided mode.</p>
      {["If I use a movie clip, I own it or have permission to use it (optional for story-first creation).", "I own or have permission to use the portrait photo.", "I have consent to use the depicted person's likeness.", "I agree the game will use original inspired assets, not copied footage, music, logos or exact character designs."].map((label, index) => <label key={index} style={{ display: "flex", gap: 10, margin: "11px 0", color: "#c8d4e1", fontSize: 14 }}><input type="checkbox" checked={rights[index]} onChange={(event) => setRights(current => current.map((value, i) => i === index ? event.target.checked : value))}/>{label}</label>)}
      <button disabled={busy || rights.slice(1).some(value => !value)} onClick={create} style={{ marginTop: 8, border: 0, borderRadius: 8, padding: "11px 16px", background: "#2878bb", color: "white", fontWeight: 700, cursor: "pointer", opacity: busy || rights.slice(1).some(value => !value) ? .5 : 1 }}>Create staged pipeline</button>
    </div> : <div style={{ marginTop: 18, display: "grid", gap: 10 }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 12, marginBottom: 6 }}>
        <label style={{ padding: 13, border: "1px dashed #49627d", borderRadius: 10, color: "#c5d4e4", fontSize: 13 }}>PLAYER PORTRAIT · FULL BODY
          <input type="file" accept="image/jpeg,image/png,image/webp" disabled={busy || !!pipeline.source_photo} onChange={event => void uploadInput("photo", event.target.files?.[0])} style={{ display: "block", marginTop: 9, maxWidth: "100%" }}/>
          <small style={{ display: "block", marginTop: 6, color: pipeline.source_photo ? "#7ec79c" : "#9fb0c4" }}>{pipeline.source_photo ? pipeline.source_photo.filename : "JPEG, PNG or WebP · max 20 MB"}</small>
        </label>
        <label data-tour="video-upload" style={{ padding: 13, border: "1px dashed #49627d", borderRadius: 10, color: "#c5d4e4", fontSize: 13 }}>MOVIE VIDEO · FULL FILM OR CLIP
          <input type="file" accept="video/mp4,video/quicktime,video/x-matroska,video/webm,video/x-msvideo" disabled={busy || !!pipeline.source_video} onChange={event => void uploadInput("video", event.target.files?.[0])} style={{ display: "block", marginTop: 9, maxWidth: "100%" }}/>
          <small style={{ display: "block", marginTop: 6, color: pipeline.source_video ? "#7ec79c" : "#9fb0c4" }}>{pipeline.source_video ? pipeline.source_video.filename : "MP4, MOV, MKV, WebM or AVI · max 8 GB"}</small>
        </label>
      </div>
      <StoryBuilderPanel projectId={projectId} api={api} onStorySaved={() => void refresh()} />
      <PlayerAvatarBuilder projectId={projectId} api={api} portraitReady={!!pipeline.source_photo} playerReady={pipeline.stages.some(stage => stage.stage === "player" && stage.state === "READY")} onBuilt={() => void refresh()} />
      <EnvironmentBuilder projectId={projectId} api={api} ready={pipeline.stages.some(stage => stage.stage === "environment" && stage.state === "READY")} onBuilt={() => void refresh()} />
      <ActorsPropsBuilder projectId={projectId} api={api} ready={pipeline.stages.some(stage => stage.stage === "actors_props" && stage.state === "READY")} onBuilt={() => void refresh()} />
      <AudioFoundry projectId={projectId} api={api} ready={pipeline.stages.some(stage => stage.stage === "audio" && stage.state === "READY")} onBuilt={() => void refresh()} />
      <GameplayFoundry projectId={projectId} api={api} ready={pipeline.stages.some(stage => stage.stage === "gameplay" && stage.state === "READY")} busy={busy} onBuilt={() => void refresh()} />
      <AssemblyFoundry projectId={projectId} api={api} ready={pipeline.stages.some(stage => stage.stage === "assembly" && stage.state === "READY")} busy={busy} onBuilt={() => void refresh()} />
      {pipeline.stages.map((stage) => <article key={stage.stage} style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", flexWrap: "wrap", padding: 13, border: "1px solid #2b3a4e", borderRadius: 10, background: "#142235" }}>
        <div style={{ minWidth: 180, flex: 1 }}><b>{stageNames[stage.stage] ?? stage.stage}</b><div style={{ fontSize: 12, color: "#9fb0c4", marginTop: 5 }}>{stage.summary} · revision {stage.revision + 1}</div>{stage.error && <div style={{ color: "#ef9696", fontSize: 12 }}>{stage.error}</div>}</div>
        <span style={{ color: statusColor[stage.state], fontSize: 11, fontWeight: 800, letterSpacing: .8 }}>{stage.state}</span>
        {stage.stage === "analysis" && stage.state === "READY" && pipeline.source_photo && pipeline.source_video && <button disabled={busy} onClick={() => void runAnalysis()}>Run local analysis</button>}\n        {stage.state === "REVIEW" && <button disabled={busy} onClick={() => stageAction(stage.stage, "approve")}>Approve</button>}
        {["REVIEW", "FAILED", "APPROVED"].includes(stage.state) && <button disabled={busy} onClick={() => stageAction(stage.stage, "regenerate")}>Regenerate</button>}
      </article>)}
      <p style={{ margin: "6px 0 0", color: "#e3c58b", fontSize: 13 }}>Media worker: FFmpeg / FFprobe analysis runs locally when installed. The full-body portrait is required; a movie clip is optional in story-first mode. All assets are generated by deterministic local tools, without AI models.</p>
    </div>}
    <p aria-live="polite" style={{ margin: "14px 0 0", color: "#9fb0c4", fontSize: 12 }}>{message}</p>
  </section>;
}
