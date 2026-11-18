"""Normalize a creator-owned 3D mesh into a self-contained, game-ready GLB.

This performs format conversion, transforms, material packing and optional polygon
budget reduction. It does not claim to rig, retopologize or repair arbitrary meshes.
"""
import argparse
import json
import sys
from pathlib import Path
import bpy


def parse_args():
    argv=sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else []
    parser=argparse.ArgumentParser()
    parser.add_argument("--input",required=True)
    parser.add_argument("--output",required=True)
    parser.add_argument("--max-faces",type=int,default=50000)
    return parser.parse_args(argv)


def import_asset(source: Path):
    ext=source.suffix.lower()
    if ext in {".glb",".gltf"}:
        bpy.ops.import_scene.gltf(filepath=str(source))
    elif ext==".obj":
        if hasattr(bpy.ops.wm,"obj_import"): bpy.ops.wm.obj_import(filepath=str(source))
        else: bpy.ops.import_scene.obj(filepath=str(source))
    elif ext==".fbx":
        bpy.ops.import_scene.fbx(filepath=str(source))
    elif ext==".ply":
        if hasattr(bpy.ops.wm,"ply_import"): bpy.ops.wm.ply_import(filepath=str(source))
        else: raise RuntimeError("This Blender build does not include the PLY importer")
    else:
        raise RuntimeError("Supported source models: GLB, glTF, OBJ, FBX and PLY")

def main():
    args=parse_args()
    source=Path(args.input).resolve()
    output=Path(args.output).resolve()
    if not source.is_file(): raise FileNotFoundError(str(source))
    output.parent.mkdir(parents=True,exist_ok=True)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    import_asset(source)
    meshes=[obj for obj in bpy.context.scene.objects if obj.type=="MESH"]
    if not meshes: raise RuntimeError("The source file contains no mesh objects")
    for obj in meshes:
        bpy.context.view_layer.objects.active=obj
        obj.select_set(True)
        bpy.ops.object.transform_apply(location=False,rotation=True,scale=True)
        obj.select_set(False)
    face_count=sum(len(obj.data.polygons) for obj in meshes)
    if args.max_faces>0 and face_count>args.max_faces:
        ratio=max(.02,min(1.0,args.max_faces/face_count))
        for obj in meshes:
            if len(obj.data.polygons)>2000:
                modifier=obj.modifiers.new("NEXORA_GameBudget","DECIMATE")
                modifier.ratio=ratio
                bpy.context.view_layer.objects.active=obj
                bpy.ops.object.modifier_apply(modifier=modifier.name)
    bpy.ops.object.select_all(action="DESELECT")
    for obj in meshes: obj.select_set(True)
    bpy.context.view_layer.objects.active=meshes[0]
    bpy.ops.export_scene.gltf(
        filepath=str(output),export_format="GLB",use_selection=True,
        export_apply=True,export_materials="EXPORT",export_image_format="AUTO",
        export_texcoords=True,export_normals=True,export_tangents=True,
    )
    result={"input":source.name,"output":str(output),"mesh_objects":len(meshes),
            "faces_before":face_count,"faces_after":sum(len(obj.data.polygons) for obj in meshes),
            "animations":sum(len(obj.animation_data.action.fcurves) for obj in bpy.data.objects if obj.animation_data and obj.animation_data.action)}
    print(json.dumps(result))
    if not output.is_file() or output.stat().st_size<1024: raise RuntimeError("Blender did not create a valid GLB output")


if __name__=="__main__": main()
