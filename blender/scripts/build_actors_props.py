"""Deterministic actor and prop mesh generator. No inference, downloads or external assets."""
import argparse, json, math, sys
from pathlib import Path
import bpy
from mathutils import Vector

def cli():
    args=sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else []
    p=argparse.ArgumentParser(); p.add_argument("--spec",required=True); p.add_argument("--output",required=True)
    return p.parse_args(args)

def mat(name, color, metallic=0.0):
    m=bpy.data.materials.new(name); m.diffuse_color=(*color,1); m.metallic=metallic; m.roughness=.62
    return m

def add_uv(name, loc, scale, material, segments=16, rings=8):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=segments, ring_count=rings, radius=1, location=loc)
    o=bpy.context.object; o.name=name; o.scale=scale; o.data.materials.append(material); return o

def add_cylinder(name, loc, radius, depth, material, vertices=12):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth, location=loc)
    o=bpy.context.object; o.name=name; o.data.materials.append(material); return o

def build_actor(actor, palette):
    base=palette["actor"]; dark=palette["dark"]; skin=palette["skin"]
    x,y,z=actor["position"]; s=actor["scale"]
    parts=[]
    parts.append(add_uv(actor["id"]+"_torso",(x,y+1.15*s,z),(.38*s,.25*s,.58*s),base))
    parts.append(add_uv(actor["id"]+"_head",(x,y+1.92*s,z),(.25*s,.24*s,.29*s),skin))
    for side,label in [(-1,"left"),(1,"right")]:
        parts.append(add_uv(actor["id"]+"_"+label+"_arm",(x+side*.48*s,y+1.18*s,z),(.14*s,.15*s,.52*s),base))
        parts.append(add_uv(actor["id"]+"_"+label+"_leg",(x+side*.17*s,y+.43*s,z),(.17*s,.2*s,.48*s),dark))
        parts.append(add_uv(actor["id"]+"_"+label+"_hand",(x+side*.5*s,y+.65*s,z),(.13*s,.13*s,.14*s),skin))
    # Join the body parts, then apply deterministic height/position-based weights.
    bpy.ops.object.select_all(action="DESELECT")
    for p in parts: p.select_set(True)
    bpy.context.view_layer.objects.active=parts[0]; bpy.ops.object.join()
    body=bpy.context.object; body.name=actor["id"]+"_mesh"
    arm_data=bpy.data.armatures.new(actor["id"]+"_skeleton"); rig=bpy.data.objects.new(actor["id"]+"_rig",arm_data); bpy.context.collection.objects.link(rig)
    bpy.context.view_layer.objects.active=rig; rig.select_set(True); bpy.ops.object.mode_set(mode="EDIT")
    bones={}
    definitions={"root":((0,0,.12),(0,0,.5),None),"spine":((0,0,.5),(0,0,1.55),"root"),"head":((0,0,1.55),(0,0,2.2),"spine"),
                 "left_arm":((-.25,0,1.55),(-.65,0,.95),"spine"),"right_arm":((.25,0,1.55),(.65,0,.95),"spine"),
                 "left_leg":((-.15,0,.5),(-.18,0,.05),"root"),"right_leg":((.15,0,.5),(.18,0,.05),"root")}
    for name,(head,tail,parent) in definitions.items():
        b=arm_data.edit_bones.new(name); b.head=(x+head[0]*s,y+head[1]*s,z+head[2]*s); b.tail=(x+tail[0]*s,y+tail[1]*s,z+tail[2]*s)
        if parent: b.parent=bones[parent]
        bones[name]=b
    bpy.ops.object.mode_set(mode="OBJECT")
    groups={name:body.vertex_groups.new(name=name) for name in definitions}
    for v in body.data.vertices:
        wx,wy,wz=body.matrix_world @ v.co
        local_x=(wx-x)/s; local_z=(wz-z)/s
        if local_z>1.62: target="head"
        elif local_z<.72: target="left_leg" if local_x<0 else "right_leg"
        elif local_z>1.05 and local_x<-.25: target="left_arm"
        elif local_z>1.05 and local_x>.25: target="right_arm"
        elif local_z<.35: target="root"
        else: target="spine"
        groups[target].add([v.index],1.0,"REPLACE")
    mod=body.modifiers.new("Actor_Skin","ARMATURE"); mod.object=rig
    body.parent=rig; body["collision_shape"]="capsule"; body["collision_radius"]=.42*s; body["collision_height"]=2.1*s
    body["actor_kind"]=actor["kind"]; body["behavior_spec"]=actor["behavior"]
    rig["actor_id"]=actor["id"]; rig["animation_ready"]=True
    return body,rig

def build_prop(prop,palette):
    x,y,z=prop["position"]; s=prop["scale"]; kind=prop["kind"]; material=palette["metal"] if kind in ("weapon","tool","vehicle") else palette["prop"]
    external_asset = str(prop.get("asset_path") or "").strip()
    if external_asset:
        asset_path = Path(external_asset).resolve()
        if not asset_path.is_file() or asset_path.suffix.lower() != ".glb":
            raise RuntimeError("Creator prop asset must be an existing local GLB file.")
        bpy.ops.object.select_all(action="DESELECT")
        bpy.ops.import_scene.gltf(filepath=str(asset_path))
        imported = list(bpy.context.selected_objects)
        if not imported:
            raise RuntimeError("Blender could not import creator prop GLB: " + asset_path.name)
        root = bpy.data.objects.new(prop["id"], None)
        bpy.context.collection.objects.link(root)
        root.location = (x, y, z)
        root.scale = (s, s, s)
        for item in imported:
            item.parent = root
        root["prop_kind"] = kind
        root["interaction_spec"] = prop["interaction"]
        root["collision_shape"] = "box"
        root["collision_size"] = [s, s, s]
        return root
    if kind=="weapon":
        obj=add_cylinder(prop["id"]+"_shaft",(x,y+s*.5,z),.07*s,s,material)
        head=add_uv(prop["id"]+"_head",(x,y+s,z),(.22*s,.13*s,.18*s),palette["metal"])
    elif kind=="vehicle":
        bpy.ops.mesh.primitive_cube_add(size=1,location=(x,y+s*.35,z)); obj=bpy.context.object; obj.name=prop["id"]+"_body"; obj.dimensions=(1.5*s,.65*s,.9*s); bpy.ops.object.transform_apply(location=False,rotation=False,scale=True); obj.data.materials.append(material)
        for side in (-1,1):
            for front in (-1,1):
                add_uv(prop["id"]+"_wheel_"+str(side)+"_"+str(front),(x+side*.55*s,y+.13*s,z+front*.34*s),(.18*s,.18*s,.18*s),palette["dark"])
    elif kind=="tool":
        obj=add_cylinder(prop["id"]+"_handle",(x,y+s*.45,z),.08*s,s*.8,material)
        add_uv(prop["id"]+"_grip",(x,y+s*.85,z),(.23*s,.1*s,.12*s),palette["dark"])
    else:
        bpy.ops.mesh.primitive_cube_add(size=1,location=(x,y+s*.5,z)); obj=bpy.context.object; obj.name=prop["id"]; obj.dimensions=(s,s,s); bpy.ops.object.transform_apply(location=False,rotation=False,scale=True); obj.data.materials.append(material)
    obj["prop_kind"]=kind; obj["interaction_spec"]=prop["interaction"]; obj["collision_shape"]="box"; obj["collision_size"]=[s,s,s]
    return obj

def main():
    a=cli(); spec=json.loads(Path(a.spec).read_text(encoding="utf-8"))
    bpy.ops.object.select_all(action="SELECT"); bpy.ops.object.delete(use_global=False)
    palette={"actor":mat("Actor_Cloth",(.12,.34,.62)),"dark":mat("Actor_Dark",(.06,.09,.13)),"skin":mat("Actor_Skin",(.55,.34,.24)),
             "prop":mat("Prop_Material",(.42,.3,.16)),"metal":mat("Metal",(.32,.38,.43),.72)}
    actor_records=[]; prop_records=[]
    for actor in spec["actors"]:
        body,rig=build_actor(actor,palette); actor_records.append({"id":actor["id"],"kind":actor["kind"],"mesh":body.name,"rig":rig.name,"collision":body["collision_shape"],"behavior":actor["behavior"]})
    for prop in spec["props"]:
        obj=build_prop(prop,palette); prop_records.append({"id":prop["id"],"kind":prop["kind"],"mesh":obj.name,"collision":obj["collision_shape"],"interaction":prop["interaction"]})
    bpy.ops.object.light_add(type="AREA",location=(0,8,8)); bpy.context.object.data.energy=1800
    bpy.ops.object.camera_add(location=(0,5,12)); cam=bpy.context.object; cam.rotation_euler=(math.radians(20),0,0); bpy.context.scene.camera=cam
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(filepath=a.output,export_format="GLB",use_selection=True)
    manifest={"schema_version":"1.0","generator":"PGF Actors & Props Foundry v1","actors":actor_records,"props":prop_records,"creator_review_required":True}
    Path(a.output).with_suffix(".manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    print(json.dumps({"actors":len(actor_records),"props":len(prop_records),"manifest":str(Path(a.output).with_suffix(".manifest.json"))}))

if __name__=="__main__": main()
