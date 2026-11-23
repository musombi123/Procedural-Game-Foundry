import { useState } from "react";
import { localAgentFetch } from "./localAgentFetch";
import AvatarPreview from "./AvatarPreview";

type Props={projectId:string;api:string;portraitReady:boolean;playerReady:boolean;onBuilt:()=>void};
export default function PlayerAvatarBuilder({projectId,api,portraitReady,playerReady,onBuilt}:Props){
 const [height,setHeight]=useState(1.78),[shoulders,setShoulders]=useState(.46),[hips,setHips]=useState(.34),[legs,setLegs]=useState(.52),[build,setBuild]=useState(1),[faceX,setFaceX]=useState(.5),[faceTop,setFaceTop]=useState(.035),[faceWidth,setFaceWidth]=useState(.22),[faceHeight,setFaceHeight]=useState(.16);
 const [busy,setBusy]=useState(false),[result,setResult]=useState("Adjust proportions, then generate the procedural player avatar.");
 const [asset,setAsset]=useState("");
 async function generate(){
  setBusy(true);
  try{
   const r=await localAgentFetch(api+"/api/projects/"+projectId+"/movie-pipeline/player/build",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({proportions:{height,shoulder_width:shoulders,hip_width:hips,leg_ratio:legs,build,face_center_x:faceX,face_top:faceTop,face_width:faceWidth,face_height:faceHeight}})});
   const data=await r.json();if(!r.ok)throw new Error(data.detail??"Player generation failed");
   setAsset(data.glb_scene);setResult("Avatar generated with "+(data.stage?.output?.bone_count??"a humanoid")+" rig. Review the GLB before approving the Player stage.");onBuilt();
  }catch(e){setResult(e instanceof Error?e.message:"Player generation failed");}
  finally{setBusy(false);}
 }
 const range=(label:string,value:number,min:number,max:number,step:number,onChange:(v:number)=>void)=><label style={{display:"grid",gap:4,fontSize:12,color:"#c5d4e4"}}>{label}: {value.toFixed(2)}<input type="range" min={min} max={max} step={step} value={value} onChange={e=>onChange(Number(e.target.value))}/></label>;
 return <article style={{marginTop:12,padding:16,border:"1px solid #49627d",borderRadius:12,background:"#0d1725",display:"grid",gap:12}}>
  <h3 style={{margin:0}}>Player character · procedural 3D avatar</h3>
  <p style={{margin:0,color:"#a9b8c9",fontSize:13}}>The uploaded full-body portrait supplies the face texture through a manually adjustable crop and the clothing palette. Blender constructs the body mesh and armature procedurally; proportions remain editable because one photo cannot reveal hidden anatomy.</p>
  {!portraitReady&&<p style={{color:"#e3c58b",margin:0}}>Upload the player's full-body portrait first.</p>}
  {!playerReady&&<p style={{color:"#e3c58b",margin:0}}>Complete the movie-analysis approval, or save a story-first brief, to unlock player generation.</p>}
  <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(170px,1fr))",gap:12}}>
   {range("Height (m)",height,1.35,2.2,.01,setHeight)}
   {range("Shoulder width",shoulders,.32,.7,.01,setShoulders)}
   {range("Hip width",hips,.24,.55,.01,setHips)}
   {range("Leg proportion",legs,.42,.62,.01,setLegs)}
   {range("Body build",build,.75,1.3,.01,setBuild)}
   {range("Face crop · horizontal center",faceX,.1,.9,.005,setFaceX)}
   {range("Face crop · top position",faceTop,0,.6,.005,setFaceTop)}
   {range("Face crop · width",faceWidth,.12,.4,.005,setFaceWidth)}
   {range("Face crop · height",faceHeight,.08,.3,.005,setFaceHeight)}
  </div>
  <button disabled={busy||!portraitReady||!playerReady} onClick={()=>void generate()}>{busy?"Building avatar in Blender…":"Generate procedural player avatar"}</button>
  {asset&&<AvatarPreview src={api+"/api/projects/"+projectId+"/movie-pipeline/assets/"+asset} />}
  {asset&&<p style={{margin:0,color:"#8fd1a8",fontSize:12}}>GLB scene: <a href={api+"/api/projects/"+projectId+"/movie-pipeline/assets/"+asset} target="_blank" rel="noreferrer">Download player avatar</a></p>}
  <p aria-live="polite" style={{margin:0,color:"#d5c28e",fontSize:12}}>{result}</p>
 </article>;
}
