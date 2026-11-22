import { useState } from "react";
import { localAgentFetch } from "./localAgentFetch";
type Props = { projectId: string; api: string; ready: boolean; busy: boolean; onBuilt: () => void };
export default function AssemblyFoundry({ projectId, api, ready, busy, onBuilt }: Props) {
  const [working, setWorking] = useState(false);
  const [message, setMessage] = useState("Approve the Gameplay stage to unlock final Godot assembly.");
  const [counts, setCounts] = useState<{ missions: number; objectives: number; actors: number; props: number; audio: number } | null>(null);
  async function assemble() {
    setWorking(true);
    setMessage("Importing approved GLB assets, wiring gameplay and validating the Godot runtime…");
    try {
      const response = await localAgentFetch(api + "/api/projects/" + projectId + "/movie-pipeline/assembly/build", { method: "POST" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? "Godot assembly failed");
      setCounts({ missions: data.mission_count, objectives: data.objective_count, actors: data.actor_count, props: data.prop_count, audio: data.audio_effect_count });
      setMessage("Godot editor import and headless runtime checks passed. Assembly is now waiting for your playtest and approval.");
      onBuilt();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Godot assembly failed"); }
    finally { setWorking(false); }
  }
  return <section style={{ marginTop: 14, padding: 16, border: "1px solid #354b64", borderRadius: 12, background: "#0d1725", color: "#e5edf7" }}>
    <div style={{ display: "flex", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
      <div><b>Assembly & Runtime Integration</b><p style={{ margin: "5px 0 12px", color: "#9fb0c4", fontSize: 13 }}>Godot 4 · imported 3D assets · live gameplay bindings · headless validation</p></div>
      <span style={{ color: ready ? "#7ec79c" : "#d9b56d", fontSize: 11, fontWeight: 800 }}>{ready ? "READY TO ASSEMBLE" : "WAITING FOR GAMEPLAY APPROVAL"}</span>
    </div>
    <button disabled={!ready || busy || working} onClick={() => void assemble()} style={{ border: 0, borderRadius: 8, padding: "10px 15px", background: "#2878bb", color: "white", fontWeight: 700, cursor: "pointer", opacity: !ready || busy || working ? .5 : 1 }}>{working ? "Assembling & testing…" : "Assemble playable Godot game"}</button>
    {counts && <div style={{ display: "flex", gap: 14, flexWrap: "wrap", marginTop: 12, fontSize: 12, color: "#c4d2e1" }}>
      <span>{counts.missions} missions</span><span>{counts.objectives} objectives</span><span>{counts.actors} actors</span><span>{counts.props} props</span><span>{counts.audio} sound cues</span>
    </div>}
    <p aria-live="polite" style={{ margin: "10px 0 0", color: "#a9b8c9", fontSize: 12 }}>{message}</p>
    {counts && <a href={api + "/api/projects/" + projectId + "/movie-pipeline/assembly/download"} style={{ display: "inline-block", marginTop: 8, color: "#8fc9f3", fontSize: 13 }}>Download assembled Godot project (.zip)</a>}
  </section>;
}
