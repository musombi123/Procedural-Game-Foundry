import { useState } from "react";
import { localAgentFetch } from "./localAgentFetch";
import AvatarPreview from "./AvatarPreview";

type Props={projectId:string;api:string;ready:boolean;onBuilt:()=>void};
type Actor={id:string;name:string;kind:"npc"|"enemy"|"animal"|"robot";behavior:string;scale:number;position:[number,number,number]};
type Prop={id:string;name:string;kind:"weapon"|"tool"|"vehicle"|"item"|"obstacle"|"container";interaction:string;scale:number;position:[number,number,number]};
export default function ActorsPropsBuilder({projectId,api,ready,onBuilt}:Props){
 const [actors,setActors]=useState<Actor[]>([{id:"guard-01",name:"Gate Guard",kind:"npc",behavior:"patrol between the gate and watchtower",scale:1,position:[2,0,2]}]);
 const [props,setProps]=useState<Prop[]>([{id:"supply-crate-01",name:"Supply Crate",kind:"container",interaction:"open and collect supplies",scale:1,position:[-2,0,1]}]);
 const [busy,setBusy]=useState(false),[asset,setAsset]=useState(""),[message,setMessage]=useState("Approve the environment to unlock actor and prop generation.");
 async function build(){
  setBusy(true);
  try{
   const response=await localAgentFetch(api+"/api/projects/"+projectId+"/movie-pipeline/actors-props/build",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({actors,props})});
   const data=await response.json();if(!response.ok)throw new Error(data.detail??"Actor and prop generation failed");
   setAsset(data.glb_scene);setMessage("Generated "+data.actor_count+" actors and "+data.prop_count+" props. Inspect and approve this stage.");onBuilt();
  }catch(e){setMessage(e instanceof Error?e.message:"Actor and prop generation failed");}
  finally{setBusy(false);}
 }
 const field={background:"#142235",color:"#e8eef7",border:"1px solid #49627d",borderRadius:6,padding:7,minWidth:0};
 return <article style={{marginTop:12,padding:16,border:"1px solid #49627d",borderRadius:12,background:"#0d1725",display:"grid",gap:10}}>
  <h3 style={{margin:0}}>Actors & props · procedural 3D cast</h3>
  <p style={{margin:0,color:"#a9b8c9",fontSize:13}}>Define your own cast and objects. Geometry, basic skeletal controls, collision metadata and interaction descriptors are generated locally with Blender. Behavior text is stored as creator-authored metadata; a runtime behavior engine is a later stage.</p>
  <b>Actors / NPCs / enemies / animals / robots</b>
  {actors.map((a,i)=><div key={a.id} style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:7}}>
   <input aria-label="Actor name" style={field} value={a.name} onChange={e=>setActors(v=>v.map((x,j)=>j===i?{...x,name:e.target.value}:x))}/>
   <select style={field} value={a.kind} onChange={e=>setActors(v=>v.map((x,j)=>j===i?{...x,kind:e.target.value as Actor["kind"]}:x))}><option value="npc">NPC</option><option value="enemy">Enemy</option><option value="animal">Animal</option><option value="robot">Robot</option></select>
   <input aria-label="Actor behavior" style={{...field,gridColumn:"1 / -1"}} value={a.behavior} onChange={e=>setActors(v=>v.map((x,j)=>j===i?{...x,behavior:e.target.value}:x))}/>
  </div>)}
  <button type="button" onClick={()=>setActors(v=>[...v,{id:"actor-"+(v.length+1),name:"New Actor",kind:"npc",behavior:"idle",scale:1,position:[0,0,0]}])} disabled={actors.length>=12}>Add actor</button>
  <b>Props / equipment / vehicles / objects</b>
  {props.map((p,i)=><div key={p.id} style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:7}}>
   <input aria-label="Prop name" style={field} value={p.name} onChange={e=>setProps(v=>v.map((x,j)=>j===i?{...x,name:e.target.value}:x))}/>
   <select style={field} value={p.kind} onChange={e=>setProps(v=>v.map((x,j)=>j===i?{...x,kind:e.target.value as Prop["kind"]}:x))}><option value="item">Item</option><option value="weapon">Weapon</option><option value="tool">Tool</option><option value="vehicle">Vehicle</option><option value="obstacle">Obstacle</option><option value="container">Container</option></select>
   <input aria-label="Prop interaction" style={{...field,gridColumn:"1 / -1"}} value={p.interaction} onChange={e=>setProps(v=>v.map((x,j)=>j===i?{...x,interaction:e.target.value}:x))}/>
  </div>)}
  <button type="button" onClick={()=>setProps(v=>[...v,{id:"prop-"+(v.length+1),name:"New Object",kind:"item",interaction:"inspect",scale:1,position:[0,0,0]}])} disabled={props.length>=40}>Add prop</button>
  <button disabled={!ready||busy||(!actors.length&&!props.length)} onClick={()=>void build()}>{busy?"Building cast and props…":"Generate actors & props"}</button>
  {!ready&&<small style={{color:"#e3c28b"}}>Approve the Environment stage first.</small>}
  {asset&&<><AvatarPreview src={api+"/api/projects/"+projectId+"/movie-pipeline/assets/"+asset}/><a href={api+"/api/projects/"+projectId+"/movie-pipeline/assets/"+asset} target="_blank" rel="noreferrer">Download actors & props GLB</a></>}
  <p aria-live="polite" style={{margin:0,color:"#d5c28e",fontSize:12}}>{message}</p>
 </article>;
}
