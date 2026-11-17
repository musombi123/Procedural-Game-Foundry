"""Procedural humanoid avatar builder. No image-to-3D or generative models.

Blender:
  blender --background --python blender/scripts/build_player_avatar.py -- --portrait photo.jpg --output player.glb --spec avatar.json

The portrait is used as a visual reference and clothing-palette source only. Body proportions
are explicit creator-controlled parameters; one photo cannot recover hidden anatomy.
"""
import argparse, json, math, os, sys
import bpy
from mathutils import Vector

def cli():
    args=sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else []
    p=argparse.ArgumentParser()
    p.add_argument("--portrait",required=True); p.add_argument("--output",required=True); p.add_argument("--spec",required=True)
    return p.parse_args(args)

def mat(name,color,roughness=.72):
    m=bpy.data.materials.new(name); m.diffuse_color=(*color,1); m.roughness=roughness; return m

def sample_clothing_color(path):
    """Use central lower portrait pixels as a rough clothing palette; no face recognition."""
    try:
        image=bpy.data.images.load(path,check_existing=False)
        w,h=image.size; px=image.pixels[:]
        samples=[]
        for fy in (.48,.55,.62,.69):
            for fx in (.38,.45,.52,.59,.66):
                x=min(w-1,max(0,int(w*fx))); y=min(h-1,max(0,int(h*fy)))
                i=(y*w+x)*4; r,g,b=px[i:i+3]
                if max(r,g,b)-min(r,g,b)>.06 and max(r,g,b)<.92 and min(r,g,b)>.04:
                    samples.append((r,g,b))
        if samples:
            samples.sort(key=lambda c:(c[0]+c[1]+c[2])/3)
            return tuple(sum(c[i] for c in samples[len(samples)//3:2*len(samples)//3+1])/max(1,len(samples)//3+1) for i in range(3))
    except Exception:
        pass
    return (.12,.22,.38)

def uv(name,loc,scale,material,segments=20,rings=12):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=segments,ring_count=rings,radius=1,location=loc)
    o=bpy.context.object; o.name=name; o.scale=scale; bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
    o.data.materials.append(material); return o

def portrait_face_material(path,crop):
    """Crop a creator-selected face region with Blender's image API; no recognition model."""
    source=bpy.data.images.load(path,check_existing=False)
    width,height=source.size
    cx=float(crop.get("center_x",.5)); top=float(crop.get("top",.035))
    cw=float(crop.get("width",.22)); ch=float(crop.get("height",.16))
    left=max(0.0,min(1.0-cw,cx-cw/2)); top=max(0.0,min(1.0-ch,top))
    size=256; source_pixels=source.pixels[:]; cropped=[]
    for y in range(size):
        for x in range(size):
            sx=min(width-1,max(0,int((left+(x/(size-1))*cw)*(width-1))))
            top_y=top+(1-y/(size-1))*ch
            sy=min(height-1,max(0,int((1-top_y)*(height-1))))
            offset=(sy*width+sx)*4
            cropped.extend(source_pixels[offset:offset+4])
    image=bpy.data.images.new("Player_Portrait_Face_Crop",width=size,height=size,alpha=True)
    image.pixels[:]=cropped; image.pack()
    material=bpy.data.materials.new("Uploaded_Portrait_Face"); material.use_nodes=True
    nodes=material.node_tree.nodes; links=material.node_tree.links
    shader=nodes.get("Principled BSDF"); texture=nodes.new("ShaderNodeTexImage"); texture.image=image
    links.new(texture.outputs["Color"],shader.inputs["Base Color"])
    shader.inputs["Roughness"].default_value=.82
    return material

def face_patch(height,scale,material):
    """Curved UV patch follows the front ellipsoid of the procedural head."""
    columns=24; rows=24; width=.19*scale; patch_height=.215*scale
    center_y=height*.89; radius_x=.115*scale; radius_y=.145*scale; radius_z=.105*scale
    vertices=[]; faces=[]; uvs=[]
    for row in range(rows+1):
        v=row/rows; y=center_y+(0.105*scale)-v*patch_height
        for col in range(columns+1):
            u=col/columns; x=(u-.5)*width
            inside=max(.02,1-(x/radius_x)**2-((y-center_y)/radius_y)**2)
            z=radius_z*math.sqrt(inside)+.003*scale
            vertices.append((x,y,z)); uvs.append((u,1-v))
    for row in range(rows):
        for col in range(columns):
            a=row*(columns+1)+col; b=a+1; d=(row+1)*(columns+1)+col; cc=d+1
            faces.append((a,d,cc,b))
    mesh=bpy.data.meshes.new("PortraitFacePatchMesh"); mesh.from_pydata(vertices,[],faces); mesh.update()
    uv_layer=mesh.uv_layers.new(name="PortraitUV")
    for poly in mesh.polygons:
        for loop_index in poly.loop_indices:
            vertex_index=mesh.loops[loop_index].vertex_index
            uv_layer.data[loop_index].uv=uvs[vertex_index]
    obj=bpy.data.objects.new("Uploaded_Portrait_Face_Patch",mesh); bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material); return obj

def cylinder(name,a,b,radius,material,vertices=16):
    start,end=Vector(a),Vector(b); direction=end-start
    bpy.ops.mesh.primitive_cone_add(vertices=vertices,radius1=radius,radius2=radius*.92,depth=direction.length,location=(start+end)/2)
    o=bpy.context.object; o.name=name; o.rotation_mode="QUATERNION"; o.rotation_quaternion=direction.to_track_quat("Z","Y"); o.data.materials.append(material); return o

def build(args):
    with open(args.spec,encoding="utf-8") as f: spec=json.load(f)
    p=spec.get("proportions",{})
    height=float(p.get("height",1.78)); shoulder=float(p.get("shoulder_width",.46)); hip=float(p.get("hip_width",.34))
    leg_ratio=float(p.get("leg_ratio",.52)); build_ratio=float(p.get("build",1.0))
    if not (1.35<=height<=2.2 and .32<=shoulder<=.7 and .24<=hip<=.55 and .42<=leg_ratio<=.62 and .75<=build_ratio<=1.3):
        raise ValueError("Avatar proportions are outside safe generation limits")
    bpy.ops.object.select_all(action="SELECT"); bpy.ops.object.delete(use_global=False)
    skin=mat("Avatar_Skin",(.48,.29,.2)); cloth=mat("Portrait_Inspired_Clothing",sample_clothing_color(args.portrait))
    dark=mat("Boots_Gloves",(.055,.065,.08)); eye=mat("Eyes",(.025,.018,.012),.3)
    detail=mat("Clothing_Details",(.72,.62,.36))
    s=height/1.78; torso_top=height*.69; hip_y=height*.48; leg_end=0
    parts=[]
    parts.append(uv("Pelvis",(0,hip_y,0),(hip*.62*build_ratio,.13*s,.14*s),cloth))
    parts.append(uv("Abdomen",(0,height*.59,0),(shoulder*.29*build_ratio,.17*s,.13*s),cloth))
    parts.append(uv("Chest",(0,height*.69,0),(shoulder*.5*build_ratio,.19*s,.16*s),cloth))
    parts.append(uv("Neck",(0,height*.81,0),(.075*s,.09*s,.075*s),skin))
    parts.append(uv("Head",(0,height*.89,0),(.115*s,.145*s,.105*s),skin))
    face_material=portrait_face_material(args.portrait,spec.get("face_crop",{}))
    parts.append(face_patch(height,s,face_material))
    parts.append(uv("Hair",(0,height*.965,-.005),(.12*s,.07*s,.11*s),dark))
    parts.append(uv("Ear_L",(-.115*s,height*.89,0),(.025*s,.045*s,.025*s),skin))
    parts.append(uv("Ear_R",(.115*s,height*.89,0),(.025*s,.045*s,.025*s),skin))
    parts.append(uv("Nose",(0,height*.885,.102*s),(.025*s,.045*s,.03*s),skin))
    for side,label in [(-1,"L"),(1,"R")]:
        parts.append(uv("Eye_"+label,(side*.045*s,height*.91,.093*s),(.018*s,.012*s,.009*s),eye,12,8))
        # shoulder, upper arm, elbow, forearm and hand
        shoulder_pos=(side*shoulder*.5*build_ratio,height*.73,0)
        elbow=(side*(shoulder*.5*build_ratio+.16*s),height*.58,0)
        wrist=(side*(shoulder*.5*build_ratio+.19*s),height*.43,.005)
        hand=(side*(shoulder*.5*build_ratio+.2*s),height*.39,.015)
        parts.append(uv("Shoulder_"+label,shoulder_pos,(.105*s,.11*s,.11*s),cloth))
        parts.append(cylinder("UpperArm_"+label,shoulder_pos,elbow,.075*s,cloth))
        parts.append(uv("Elbow_"+label,elbow,(.07*s,.07*s,.07*s),cloth))
        parts.append(cylinder("Forearm_"+label,elbow,wrist,.055*s,cloth))
        parts.append(uv("Hand_"+label,hand,(.05*s,.075*s,.035*s),skin))
        # legs with articulated knees and boots
        hip_pos=(side*hip*.32*build_ratio,hip_y,0)
        knee_y=height*(1-leg_ratio*.48)
        ankle_y=height*(1-leg_ratio)
        knee=(side*hip*.34*build_ratio,knee_y,0)
        ankle=(side*hip*.36*build_ratio,ankle_y,0)
        foot=(side*hip*.36*build_ratio,ankle_y-.035*s,.07*s)
        parts.append(uv("Thigh_"+label,(hip_pos[0],(hip_y+knee_y)/2,0),(.105*s*build_ratio,(hip_y-knee_y)/2+.04*s,.105*s),cloth))
        parts.append(uv("Knee_"+label,knee,(.072*s,.075*s,.075*s),cloth))
        parts.append(cylinder("Shin_"+label,knee,ankle,.062*s,dark))
        parts.append(uv("Boot_"+label,foot,(.07*s,.055*s,.13*s),dark))
    # Join body islands into one skinnable mesh while preserving material assignments.
    bpy.ops.object.select_all(action="DESELECT")
    for o in parts: o.select_set(True)
    bpy.context.view_layer.objects.active=parts[0]; bpy.ops.object.join()
    body=bpy.context.object; body.name="PlayerAvatar_Mesh"
    # Rig with named deform bones and a basic humanoid hierarchy.
    arm_data=bpy.data.armatures.new("PlayerAvatar_Rig"); rig=bpy.data.objects.new("PlayerAvatar_Rig",arm_data); bpy.context.collection.objects.link(rig)
    bpy.context.view_layer.objects.active=rig; rig.select_set(True); bpy.ops.object.mode_set(mode="EDIT")
    bones={}
    def bone(name,head,tail,parent=None):
        b=arm_data.edit_bones.new(name); b.head=head; b.tail=tail
        if parent: b.parent=bones[parent]
        bones[name]=b
    bone("root",(0,0,0),(0,height*.1,0))
    bone("pelvis",(0,hip_y,0),(0,height*.57,0),"root")
    bone("spine",(0,height*.57,0),(0,height*.7,0),"pelvis")
    bone("neck",(0,height*.7,0),(0,height*.82,0),"spine")
    bone("head",(0,height*.82,0),(0,height*.96,0),"neck")
    for side,label in [(-1,"L"),(1,"R")]:
        sx=side
        sh=(sx*shoulder*.5*build_ratio,height*.73,0); el=(sx*(shoulder*.5*build_ratio+.16*s),height*.58,0); wr=(sx*(shoulder*.5*build_ratio+.19*s),height*.43,0)
        bone("upper_arm."+label,sh,el,"spine"); bone("forearm."+label,el,wr,"upper_arm."+label); bone("hand."+label,wr,(wr[0],wr[1]-.07*s,.02),"forearm."+label)
        hp=(sx*hip*.32*build_ratio,hip_y,0); kn=(sx*hip*.34*build_ratio,height*(1-leg_ratio*.48),0); an=(sx*hip*.36*build_ratio,height*(1-leg_ratio),0)
        bone("thigh."+label,hp,kn,"pelvis"); bone("shin."+label,kn,an,"thigh."+label); bone("foot."+label,an,(an[0],an[1]-.04*s,.1*s),"shin."+label)
    bpy.ops.object.mode_set(mode="OBJECT")
    # Deterministic proximity weights avoid Blender's heat-weight solver failing on a
    # joined mesh made from multiple procedural body volumes.
    deform_bones=[b for b in arm_data.bones if b.use_deform]
    groups={b.name:body.vertex_groups.new(name=b.name) for b in deform_bones}
    segments=[]
    for b in deform_bones:
        head=rig.matrix_world @ b.head_local; tail=rig.matrix_world @ b.tail_local
        segments.append((b.name,head,tail))
    def distance_to_segment(point,a,b):
        ab=b-a
        if ab.length_squared==0: return (point-a).length
        t=max(0.0,min(1.0,(point-a).dot(ab)/ab.length_squared))
        return (point-(a+t*ab)).length
    for vertex in body.data.vertices:
        point=body.matrix_world @ vertex.co
        nearest=sorted(((distance_to_segment(point,a,b),name) for name,a,b in segments))[:2]
        weights=[1.0/max(distance,0.025)**2 for distance,_ in nearest]
        total=sum(weights)
        for (_,name),weight in zip(nearest,weights):
            groups[name].add([vertex.index],weight/total,"REPLACE")
    modifier=body.modifiers.new("PlayerAvatar_Skinning","ARMATURE"); modifier.object=rig
    body.parent=rig
    # Creator-editable material and rig metadata travel in the GLB custom properties.
    rig["identity_source"]="uploaded_portrait"; rig["portrait_reference"]=os.path.basename(args.portrait)
    rig["generator"]="PGF procedural humanoid v1"; rig["creator_review_required"]=True
    rig["proportions_json"]=json.dumps(p)
    # Build authored idle and walk cycles; store both as NLA strips for GLB export.
    rig.animation_data_create()
    idle=bpy.data.actions.new("PGF_Idle"); rig.animation_data.action=idle
    for frame,breath in ((1,0.0),(12,.025),(24,0.0)):
        spine=rig.pose.bones["spine"]; spine.rotation_mode="XYZ"; spine.rotation_euler=(breath,0,0)
        spine.keyframe_insert(data_path="rotation_euler",frame=frame,group="spine")
        head=rig.pose.bones["head"]; head.rotation_mode="XYZ"; head.rotation_euler=(0,0,math.sin(frame/24*math.pi)*.025)
        head.keyframe_insert(data_path="rotation_euler",frame=frame,group="head")
    rig.animation_data.action=None
    track=rig.animation_data.nla_tracks.new(); track.name="PGF_Idle"; strip=track.strips.new("PGF_Idle",1,idle)
    walk=bpy.data.actions.new("PGF_Walk")
    for frame,phase in ((1,0),(7,math.pi/2),(13,math.pi),(19,3*math.pi/2),(25,2*math.pi)):
        for name,offset in (("upper_arm.L",0),("upper_arm.R",math.pi),("thigh.L",math.pi),("thigh.R",0)):
            pose=rig.pose.bones[name]; pose.rotation_mode="XYZ"
            pose.rotation_euler=(math.sin(phase+offset)*.42,0,0)
            pose.keyframe_insert(data_path="rotation_euler",frame=frame,group=name)
    walk_track=rig.animation_data.nla_tracks.new(); walk_track.name="PGF_Walk"
    walk_strip=walk_track.strips.new("PGF_Walk",1,walk)
    bpy.context.scene.frame_start=1; bpy.context.scene.frame_end=25
    # Export skinned avatar, armature and both animation strips.
    bpy.ops.object.select_all(action="DESELECT"); body.select_set(True); rig.select_set(True); bpy.context.view_layer.objects.active=rig
    bpy.ops.export_scene.gltf(filepath=args.output,export_format="GLB",use_selection=True,export_animations=True,export_nla_strips=True)
    return {"height":height,"bone_count":len(arm_data.bones),"mesh":"PlayerAvatar_Mesh","rig":"PlayerAvatar_Rig"}

if __name__=="__main__":
    args=cli(); result=build(args); print(json.dumps(result))
