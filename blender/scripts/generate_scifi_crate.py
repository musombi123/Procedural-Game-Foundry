"""Run with: blender --background --python generate_scifi_crate.py -- --output /path/crate.glb
Creates an original low-poly sci-fi cargo crate and exports glTF/GLB. Requires Blender bpy.
"""
import bpy,sys,argparse,os

def main():
    argv=sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else []
    parser=argparse.ArgumentParser(); parser.add_argument("--output",required=True); args=parser.parse_args(argv)
    bpy.ops.object.select_all(action="SELECT"); bpy.ops.object.delete(use_global=False)
    mat=bpy.data.materials.new("PGF_Crate_Alloy"); mat.diffuse_color=(0.12,0.22,0.31,1); mat.metallic=0.72; mat.roughness=0.34
    bpy.ops.mesh.primitive_cube_add(size=2,location=(0,0,1)); crate=bpy.context.object; crate.name="PGF_SciFi_Cargo_Crate"; crate.dimensions=(2.0,1.6,2.0); bpy.ops.object.transform_apply(location=False,rotation=False,scale=True); crate.data.materials.append(mat)
    bevel=crate.modifiers.new("Manufactured_Edges","BEVEL"); bevel.width=0.09; bevel.segments=2
    crate.modifiers.new("Weighted_Corner_Normals","WEIGHTED_NORMAL")
    for x in (-0.72,0.72):
        bpy.ops.mesh.primitive_cube_add(size=1,location=(x,-0.82,1)); rib=bpy.context.object; rib.name="Crate_Rib"; rib.dimensions=(0.12,0.08,1.7); bpy.ops.object.transform_apply(location=False,rotation=False,scale=True); rib.data.materials.append(mat)
    os.makedirs(os.path.dirname(os.path.abspath(args.output)),exist_ok=True)
    bpy.ops.object.select_all(action="SELECT"); bpy.ops.export_scene.gltf(filepath=args.output,export_format="GLB",use_selection=True)
if __name__=="__main__": main()
