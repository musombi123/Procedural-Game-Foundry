import { useState } from "react";
type Props = { projectId: string; api: string; ready: boolean; busy: boolean; onBuilt: () => void };
const starter = {
  player: { move_speed: 5, jump_velocity: 4.5, gravity: 9.8, health: 100, inventory_capacity: 20 },
  missions: [{ id: "mission-1", title: "", description: "", objectives: [
    { id: "objective-1", title: "", description: "", kind: "interact", target_id: null, required_count: 1 }
  ] }],
  actor_behaviours: [], interactions: [], audio_bindings: [],
  win_condition: "all_objectives_complete", lose_condition: "health_depleted"
};
export default function GameplayFoundry({ projectId, api, ready, busy, onBuilt }: Props) {
  const [source, setSource] = useState(JSON.stringify(starter, null, 2));
  const [message, setMessage] = useState("Define missions, objective logic, actor behaviours, prop interactions and audio event bindings. Blank mission text must be completed by you.");
  const [working, setWorking] = useState(false);
  async function compile() {
    let spec: unknown;
    try { spec = JSON.parse(source); } catch { setMessage("Gameplay definition is not valid JSON. Correct the syntax and try again."); return; }
    setWorking(true);
    try {
      const response = await fetch(api + "/api/projects/" + projectId + "/movie-pipeline/gameplay/compile", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(spec)
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? "Gameplay compilation failed");
      setMessage("Gameplay compiled into deterministic Godot runtime files. Review and approve this stage to unlock assembly.");
      onBuilt();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Gameplay compilation failed"); }
    finally { setWorking(false); }
  }
  return <div style={{ marginTop:14,padding:16,border:"1px solid #354b64",borderRadius:12,background:"#0d1725" }}>
    <div style={{display:"flex",justifyContent:"space-between",gap:10,flexWrap:"wrap"}}>
      <div><b>Gameplay Compiler</b><p style={{margin:"5px 0 12px",color:"#9fb0c4",fontSize:13}}>Creator-authored JSON contract · deterministic Godot scripts · no AI inference</p></div>
      <span style={{color:ready?"#7ec79c":"#d9b56d",fontSize:11,fontWeight:800}}>{ready?"READY TO COMPILE":"WAITING FOR AUDIO APPROVAL"}</span>
    </div>
    <textarea aria-label="Gameplay specification JSON" spellCheck={false} value={source} onChange={event=>setSource(event.target.value)}
      style={{width:"100%",minHeight:360,resize:"vertical",boxSizing:"border-box",border:"1px solid #3a5069",borderRadius:8,background:"#08111d",color:"#d9e5f2",padding:12,fontFamily:"ui-monospace,monospace",fontSize:12,lineHeight:1.5}}/>
    <div style={{display:"flex",gap:10,alignItems:"center",flexWrap:"wrap",marginTop:10}}>
      <button disabled={!ready||busy||working} onClick={()=>void compile()} style={{border:0,borderRadius:8,padding:"10px 15px",background:"#2878bb",color:"white",fontWeight:700,cursor:"pointer",opacity:!ready||busy||working?.5:1}}>{working?"Compiling…":"Compile gameplay"}</button>
      <button disabled={working} onClick={()=>setSource(JSON.stringify(starter,null,2))} style={{border:"1px solid #42546a",borderRadius:8,padding:"10px 12px",background:"transparent",color:"#cbd8e7"}}>Reset template</button>
    </div>
    <p aria-live="polite" style={{margin:"10px 0 0",color:"#a9b8c9",fontSize:12}}>{message}</p>
  </div>;
}
