import { useState } from "react";
import { localAgentFetch } from "./localAgentFetch";
import AvatarPreview from "./AvatarPreview";

type Props={projectId:string;api:string;ready:boolean;onBuilt:()=>void};
export default function EnvironmentBuilder({projectId,api,ready,onBuilt}:Props){
 const [busy,setBusy]=useState(false),[asset,setAsset]=useState(""),[message,setMessage]=useState("Approve the player character to unlock full 3D environment generation.");
 async function build(){
  setBusy(true);
  try{
   const r=await localAgentFetch(api+"/api/projects/"+projectId+"/movie-pipeline/environment/build",{method:"POST"});
   const data=await r.json();if(!r.ok)throw new Error(data.detail??"Environment generation failed");
   setAsset(data.glb_scene);setMessage("3D world generated: "+data.landmarks+" landmarks and "+data.props+" props. Inspect and approve the Environment stage.");onBuilt();
  }catch(e){setMessage(e instanceof Error?e.message:"Environment generation failed");}
  finally{setBusy(false);}
 }
 return <article style={{marginTop:12,padding:16,border:"1px solid #49627d",borderRadius:12,background:"#0d1725",display:"grid",gap:10}}>
  <h3 style={{margin:0}}>Environment · full 3D world</h3>
  <p style={{margin:0,color:"#a9b8c9",fontSize:13}}>Blender builds terrain meshes, 3D structures, props, lighting and walkable route geometry from your approved story brief. No generated images or AI models.</p>
  {!ready&&<p style={{margin:0,color:"#e3c28b",fontSize:12}}>The player stage must be approved first.</p>}
  <button disabled={!ready||busy} onClick={()=>void build()}>{busy?"Building full 3D world…":"Generate 3D environment"}</button>
  {asset&&<><AvatarPreview src={api+"/api/projects/"+projectId+"/movie-pipeline/assets/"+asset}/><a href={api+"/api/projects/"+projectId+"/movie-pipeline/assets/"+asset} target="_blank" rel="noreferrer">Download environment GLB</a></>}
  <p aria-live="polite" style={{margin:0,color:"#d5c28e",fontSize:12}}>{message}</p>
 </article>;
}
