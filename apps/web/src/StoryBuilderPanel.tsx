import { useEffect, useState } from "react";

type Props = { projectId: string; api: string };
type Brief = { mode: "story"|"movie"|"guided"; title: string; premise: string; player_role: string; setting: string; tone: string; instructions: string; ending: string; mission_count: number; world_scale: "small"|"medium"|"large" };
const empty: Brief = { mode:"guided", title:"", premise:"", player_role:"Player", setting:"", tone:"", instructions:"", ending:"", mission_count:5, world_scale:"medium" };

export default function StoryBuilderPanel({projectId,api}:Props) {
  const [brief,setBrief]=useState<Brief>(empty);
  const [busy,setBusy]=useState(false);
  const [message,setMessage]=useState("Write the story or instructions that define how your game should unfold.");
  const [world,setWorld]=useState<any>(null);
  useEffect(()=>{ void (async()=>{ try { const r=await fetch(api+"/api/projects/"+projectId+"/movie-pipeline/story"); if(r.ok){const s=await r.json(); setBrief({mode:s.mode??empty.mode,title:s.title??empty.title,premise:s.premise??"",player_role:s.player_role??empty.player_role,setting:s.setting??"",tone:s.tone??"",instructions:s.instructions??"",ending:s.ending??"",mission_count:s.mission_count??5,world_scale:s.world_scale??"medium"});} } catch {} })(); },[api,projectId]);
  const set=(key:keyof Brief,value:string|number)=>setBrief(current=>({...current,[key]:value}));
  async function save():Promise<boolean>{
    setBusy(true);
    try { const r=await fetch(api+"/api/projects/"+projectId+"/movie-pipeline/story",{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify(brief)});
      const data=await r.json(); if(!r.ok) throw new Error(data.detail??"Could not save story"); setBrief({mode:data.story.mode??empty.mode,title:data.story.title??empty.title,premise:data.story.premise??"",player_role:data.story.player_role??empty.player_role,setting:data.story.setting??"",tone:data.story.tone??"",instructions:data.story.instructions??"",ending:data.story.ending??"",mission_count:data.story.mission_count??5,world_scale:data.story.world_scale??"medium"}); setMessage("Creator story saved. Portrait remains the player identity source."); return true;
    } catch(e){setMessage(e instanceof Error?e.message:"Story save failed"); return false;} finally{setBusy(false);}
  }
  async function buildWorld(){
    setBusy(true);
    try { const r=await fetch(api+"/api/projects/"+projectId+"/movie-pipeline/environment/build",{method:"POST"}); const data=await r.json(); if(!r.ok) throw new Error(data.detail??"World build failed"); setWorld(data); setMessage("3D world geometry specification generated. Run the Blender builder to export the full GLB scene."); }
    catch(e){setMessage(e instanceof Error?e.message:"World build failed");} finally{setBusy(false);}
  }
  return <article style={{marginTop:14,padding:16,border:"1px solid #49627d",borderRadius:12,background:"#0d1725",display:"grid",gap:10}}>
    <h3 style={{margin:0}}>Game story & world direction</h3>
    <p style={{margin:0,color:"#a9b8c9",fontSize:13}}>Choose story-first, movie-first, or guided creation. Your uploaded portrait is always the playable main character.</p>
    <label>Creation mode<select value={brief.mode} onChange={e=>set("mode",e.target.value)}><option value="guided">Guided · movie + my instructions</option><option value="story">Story-first · my original story</option><option value="movie">Movie-first · recreate the structure as an original game</option></select></label>
    <label>Game title<input value={brief.title} onChange={e=>set("title",e.target.value)} placeholder="Name your game"/></label>
    <label>Story / premise<textarea rows={4} value={brief.premise} onChange={e=>set("premise",e.target.value)} placeholder="Write what happens, who the player is, the conflict and the world…"/></label>
    <label>World setting<input value={brief.setting} onChange={e=>set("setting",e.target.value)} placeholder="e.g. coastal city, lost kingdom, alien frontier"/></label>
    <label>How should the game unfold?<textarea rows={4} value={brief.instructions} onChange={e=>set("instructions",e.target.value)} placeholder="Describe missions, actions, choices, enemies, rules, pacing and anything the system must follow…"/></label>
    <label>Player role<input value={brief.player_role} onChange={e=>set("player_role",e.target.value)} placeholder="Explorer, pilot, survivor…"/></label>
    <label>Tone / atmosphere<input value={brief.tone} onChange={e=>set("tone",e.target.value)} placeholder="Dark sci-fi, hopeful adventure…"/></label>
    <label>Desired ending<textarea rows={2} value={brief.ending} onChange={e=>set("ending",e.target.value)} placeholder="Optional ending or victory condition"/></label>
    <div style={{display:"flex",gap:10,flexWrap:"wrap"}}>
      <label>Mission count<input type="number" min="1" max="20" value={brief.mission_count} onChange={e=>set("mission_count",Number(e.target.value))}/></label>
      <label>World scale<select value={brief.world_scale} onChange={e=>set("world_scale",e.target.value)}><option value="small">Small</option><option value="medium">Medium</option><option value="large">Large</option></select></label>
    </div>
    <div style={{display:"flex",gap:8,flexWrap:"wrap"}}><button disabled={busy||!brief.title.trim()} onClick={()=>void save()}>Save story direction</button><button disabled={busy||!brief.title.trim()} onClick={()=>void (async()=>{if(await save()) await buildWorld();})()}>Save & build 3D world</button></div>
    {world&&<p style={{margin:0,color:"#8fd1a8"}}>3D GLB ready · {world.dimensions?.join(" × ")} units · {world.landmarks} landmarks · {world.props} props · {world.glb_scene}</p>}
    <p aria-live="polite" style={{margin:0,color:"#d5c28e",fontSize:12}}>{message}</p>
  </article>;
}
