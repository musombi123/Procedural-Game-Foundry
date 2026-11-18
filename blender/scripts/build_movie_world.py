"""Build a real 3D world from PGF's deterministic world-spec JSON.

Run: blender --background --python build_movie_world.py -- --spec world-spec.json --output environment.glb
Only Blender's bundled Python API is used. No model inference or remote service.
"""
import argparse, json, math, random, sys
import bpy
from mathutils import Vector

def args():
    values=sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else []
    p=argparse.ArgumentParser(); p.add_argument("--spec",required=True); p.add_argument("--output",required=True)
    return p.parse_args(values)

def material(name, color, roughness=.8):
    mat=bpy.data.materials.new(name); mat.diffuse_color=(*color,1); mat.roughness=roughness
    return mat

def cube(name, location, scale, mat, bevel=.15):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location); obj=bpy.context.object; obj.name=name
    obj.dimensions=scale; bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if mat: obj.data.materials.append(mat)
    if bevel:
        mod=obj.modifiers.new("soft_edges","BEVEL"); mod.width=bevel; mod.segments=2
        obj.modifiers.new("weighted_normals","WEIGHTED_NORMAL")
    return obj

def build(spec):
    bpy.ops.object.select_all(action="SELECT"); bpy.ops.object.delete(use_global=False)
    palette=spec.get("palette",{})
    architecture=spec.get("architecture","sci_fi")
    terrain_mat=material("Terrain",tuple(palette.get("terrain",(0.16,.25,.13))))
    stone=material("Stone",tuple(palette.get("stone",(.32,.34,.36))))
    wood=material("Structure",tuple(palette.get("wood",(.28,.16,.08))))
    foliage=material("Foliage",tuple(palette.get("foliage",(.08,.25,.1))))
    road_mat=material("Road",tuple(palette.get("road",(.18,.18,.18))))
    accent=material("Accent",tuple(palette.get("accent",(.12,.5,.65))),roughness=.45)
    size_x,_,size_z=spec["dimensions"]; segments=spec["terrain"]["segments"]
    verts=[]; faces=[]
    seed=spec["seed"]; rng=random.Random(seed); amp=spec["terrain"]["amplitude"]; freq=spec["terrain"]["frequency"]
    for z in range(segments+1):
        for x in range(segments+1):
            px=(x/segments-.5)*size_x; pz=(z/segments-.5)*size_z
            height=amp*(math.sin(px*freq)*math.cos(pz*freq)*.55 + math.sin((px+pz)*freq*.6)*.25)
            verts.append((px,height,pz))
    for z in range(segments):
        for x in range(segments):
            a=z*(segments+1)+x; b=a+1; c=b+segments+1; d=a+segments+1
            faces.append((a,d,c,b))
    mesh=bpy.data.meshes.new("ProceduralTerrainMesh"); mesh.from_pydata(verts,[],faces); mesh.update()
    ground=bpy.data.objects.new("3D_Terrain",mesh); bpy.context.collection.objects.link(ground); ground.data.materials.append(terrain_mat)
    for landmark in spec.get("landmarks",[]):
        x,y,z=landmark["position"]; sx,sy,sz=landmark.get("footprint",[8,8,8])
        cube(landmark["id"]+"_foundation",(x,y+0.2,z),(sx,0.4,sz),stone)
        if architecture=="urban":
            cube(landmark["id"]+"_building",(x,y+sy/2,z),(sx*.82,sy,sz*.82),stone)
            for floor in range(max(2,int(sy//2))):
                for side in (-1,1):
                    cube(landmark["id"]+"_window_"+str(floor)+"_"+str(side),(x+side*sx*.42,y+1+floor*2,z+sz*.415),(sx*.16,1.0,.08),accent,0)
            cube(landmark["id"]+"_roof",(x,y+sy+0.35,z),(sx*.95,.5,sz*.95),wood)
        elif architecture=="fantasy":
            cube(landmark["id"]+"_keep",(x,y+sy*.48,z),(sx*.68,sy*.96,sz*.68),stone)
            for side in (-1,1):
                cube(landmark["id"]+"_tower_"+str(side),(x+side*sx*.43,y+sy*.65,z),(sx*.22,sy*1.3,sz*.22),wood)
                cube(landmark["id"]+"_spire_"+str(side),(x+side*sx*.43,y+sy*1.42,z),(sx*.28,.7,sz*.28),accent)
        elif architecture=="wilderness":
            cube(landmark["id"]+"_field_station",(x,y+sy*.45,z),(sx*.76,sy*.9,sz*.68),wood)
            cube(landmark["id"]+"_roof",(x,y+sy,z),(sx*.94,.6,sz*.86),stone)
        else:
            cube(landmark["id"]+"_core",(x,y+sy/2,z),(sx*.7,sy,sz*.7),stone)
            cube(landmark["id"]+"_roof",(x,y+sy+0.5,z),(sx*1.15,1,sz*1.15),wood)
        cube(landmark["id"]+"_door",(x,y+1.2,z+sz*.351),(sx*.2,2.4,.18),accent,0)
    # Raised, walkable 3D route strips connect spawn to every landmark.
    for route_index, route in enumerate(spec.get("navigation", {}).get("paths", [])):
        target = next((item for item in spec.get("landmarks", []) if item["id"] == route.get("to")), None)
        if target:
            tx, _, tz = target["position"]
            length = math.sqrt(tx*tx + tz*tz)
            midpoint = (tx/2, .18, tz/2)
            road = cube("Walkable_Path_%02d" % (route_index+1), midpoint,
                        (spec["navigation"].get("path_width", 4.0), .25, length), road_mat, .05)
            road.rotation_euler[1] = math.atan2(tx, tz)
    for prop in spec.get("props",[]):
        x,y,z=prop["position"]; s=prop["scale"]; kind=prop["geometry"]
        if kind=="tree":
            bpy.ops.mesh.primitive_cylinder_add(vertices=8, radius=.22*s, depth=2.2*s, location=(x,y+1.1*s,z))
            bpy.context.object.name=prop["id"]+"_trunk"; bpy.context.object.data.materials.append(wood)
            bpy.ops.mesh.primitive_cone_add(vertices=8, radius1=1.1*s, radius2=.08, depth=2.6*s, location=(x,y+3*s,z))
            bpy.context.object.name=prop["id"]+"_crown"; bpy.context.object.data.materials.append(foliage)
        elif kind=="rock":
            bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1,radius=s,location=(x,y+s*.5,z))
            bpy.context.object.name=prop["id"]; bpy.context.object.scale=(1.2,.8,1); bpy.context.object.data.materials.append(stone)
        else: cube(prop["id"],(x,y+s*.5,z),(s*1.4,s,s),wood)
    bpy.ops.object.light_add(type="SUN", location=(0,30,0)); bpy.context.object.name="World_Sun"
    bpy.context.object.data.energy=spec.get("lighting",{}).get("energy",2)
    bpy.ops.object.camera_add(location=(0,18,24)); cam=bpy.context.object; cam.name="World_Camera"
    cam.rotation_euler=(math.radians(35),0,0); bpy.context.scene.camera=cam
    # Export every generated mesh/light/camera as a self-contained GLB scene.
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(filepath=args().output, export_format="GLB", use_selection=True)

if __name__=="__main__":
    cli=args()
    with open(cli.spec,encoding="utf-8") as f: data=json.load(f)
    build(data)
