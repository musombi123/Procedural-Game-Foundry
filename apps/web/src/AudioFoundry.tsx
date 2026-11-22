import { useState } from "react";
import { localAgentFetch } from "./localAgentFetch";
type Props={projectId:string;api:string;ready:boolean;onBuilt:()=>void};
type Cue={id:string;label:string;kind:"tone"|"impact"|"sweep"|"pulse"|"noise"|"alarm";frequency:number;duration:number;seed:number;trigger:string};
export default function AudioFoundry({projectId,api,ready,onBuilt}:Props){
 const [cues,setCues]=useState<Cue[]>([{id:"player-hit",label:"Player hit",kind:"impact",frequency:180,duration:.65,seed:11,trigger:"player receives damage"},{id:"mission-complete",label:"Mission complete",kind:"sweep",frequency:520,duration:1.4,seed:22,trigger:"mission objective completed"}]);
 const [music,setMusic]=useState(true),[mood,setMood]=useState<"adventure"|"calm"|"tense"|"triumphant">("adventure"),[duration,setDuration]=useState(24);
 const [busy,setBusy]=useState(false),[assets,setAssets]=useState<any[]>([]),[message,setMessage]=useState("Approve Actors & Props to unlock Audio Foundry.");
 async function build(){
  setBusy(true);
  try{const response=await localAgentFetch(api+"/api/projects/"+projectId+"/movie-pipeline/audio/build",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({cues,music:music?{mood,duration,seed:7,loop:true}:null})});
   const data=await response.json();if(!response.ok)throw new Error(data.detail??"Audio generation failed");
   const stage=data.stage;const outputs=stage.output;setAssets([...outputs.effects.map((x:any)=>({name:x.label,asset:x.asset,duration:x.duration_seconds})),...(outputs.music?[{name:"Background music · "+outputs.music.mood,asset:outputs.music.asset,duration:outputs.music.duration_seconds}]:[])]);
   setMessage("Generated "+data.effects_count+" sound effects"+(data.music_generated?" and background music.":"." )+" Listen and approve the Audio stage.");onBuilt();
  }catch(e){setMessage(e instanceof Error?e.message:"Audio generation failed");}finally{setBusy(false);}
 }
 const field={background:"#142235",color:"#e8eef7",border:"1px solid #49627d",borderRadius:6,padding:7,minWidth:0};
 return <article style={{marginTop:12,padding:16,border:"1px solid #49627d",borderRadius:12,background:"#0d1725",display:"grid",gap:10}}>
  <h3 style={{margin:0}}>Audio Foundry · original sound synthesis</h3>
  <p style={{margin:0,color:"#a9b8c9",fontSize:13}}>Create sound effects and looping music using deterministic oscillators, envelopes and seeded noise. No audio models, samples, downloads or paid APIs. Cue triggers are metadata for the gameplay compiler; they are not yet wired to runtime events.</p>
  <b>Sound effects</b>
  {cues.map((cue,i)=><div key={cue.id} style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:7}}>
   <input aria-label="Sound cue name" style={field} value={cue.label} onChange={e=>setCues(v=>v.map((x,j)=>j===i?{...x,label:e.target.value}:x))}/>
   <select style={field} value={cue.kind} onChange={e=>setCues(v=>v.map((x,j)=>j===i?{...x,kind:e.target.value as Cue["kind"]}:x))}><option value="tone">Tone</option><option value="impact">Impact</option><option value="sweep">Sweep</option><option value="pulse">Pulse</option><option value="noise">Noise</option><option value="alarm">Alarm</option></select>
   <input aria-label="Gameplay sound trigger" style={{...field,gridColumn:"1 / -1"}} value={cue.trigger} onChange={e=>setCues(v=>v.map((x,j)=>j===i?{...x,trigger:e.target.value}:x))}/>
  </div>)}
  <button type="button" disabled={cues.length>=24} onClick={()=>setCues(v=>[...v,{id:"cue-"+(v.length+1),label:"New sound",kind:"tone",frequency:440,duration:.8,seed:v.length+1,trigger:"manual"}])}>Add sound cue</button>
  <label style={{display:"flex",gap:8,alignItems:"center"}}><input type="checkbox" checked={music} onChange={e=>setMusic(e.target.checked)}/> Generate background music</label>
  {music&&<div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:7}}><select style={field} value={mood} onChange={e=>setMood(e.target.value as typeof mood)}><option value="adventure">Adventure</option><option value="calm">Calm</option><option value="tense">Tense</option><option value="triumphant">Triumphant</option></select><input style={field} type="number" min="4" max="180" value={duration} onChange={e=>setDuration(Number(e.target.value))} aria-label="Music duration in seconds"/></div>}
  <button disabled={!ready||busy||(!cues.length&&!music)} onClick={()=>void build()}>{busy?"Synthesizing audio…":"Generate audio assets"}</button>
  {!ready&&<small style={{color:"#e3c28b"}}>Approve Actors & Props first.</small>}
  {assets.map(item=><div key={item.asset} style={{display:"grid",gap:4,padding:9,border:"1px solid #344b64",borderRadius:8}}><b>{item.name}</b><audio controls preload="none" src={api+"/api/projects/"+projectId+"/movie-pipeline/assets/"+item.asset} style={{width:"100%"}}/><small>{item.duration.toFixed(2)} seconds · WAV PCM</small><a href={api+"/api/projects/"+projectId+"/movie-pipeline/assets/"+item.asset}>Download WAV</a></div>)}
  <p aria-live="polite" style={{margin:0,color:"#d5c28e",fontSize:12}}>{message}</p>
 </article>;
}
