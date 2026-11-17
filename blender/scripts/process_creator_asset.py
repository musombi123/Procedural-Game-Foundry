"""Inspect and normalize one creator-supplied, self-contained GLB using Blender.

Run:
  blender --background --python blender/scripts/process_creator_asset.py -- \
    --input creator.glb --output normalized.glb --report report.json

This script does not generate or claim to repair semantic geometry. It validates
scene safety, applies object transforms, triangulates meshes, packs image assets,
and exports a normalized GLB with a machine-readable report.
"""
import argparse
import json
import math
import os
import sys

import bpy


def arguments():
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    return parser.parse_args(values)


def main():
    args = arguments()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=os.path.abspath(args.input))
    meshes = [item for item in bpy.context.scene.objects if item.type == "MESH"]
    if not meshes:
        raise RuntimeError("No mesh geometry was found in the GLB.")
    if len(meshes) > 5000:
        raise RuntimeError("Asset exceeds the 5,000 mesh-object processing limit.")

    vertex_count = 0
    triangle_count = 0
    for item in meshes:
        if any(not math.isfinite(float(value)) for value in item.location):
            raise RuntimeError(f"Object {item.name} has a non-finite location.")
        if any(abs(float(value)) > 100000 for value in item.location):
            raise RuntimeError(f"Object {item.name} is outside the supported coordinate range.")
        if any(abs(float(value)) < 1e-8 for value in item.scale):
            raise RuntimeError(f"Object {item.name} has a zero scale.")
        bpy.ops.object.select_all(action="DESELECT")
        bpy.context.view_layer.objects.active = item
        item.select_set(True)
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
        modifier = item.modifiers.new(name="NEXORA_Triangulate", type="TRIANGULATE")
        bpy.context.view_layer.objects.active = item
        bpy.ops.object.modifier_apply(modifier=modifier.name)
        for polygon in item.data.polygons:
            polygon.use_smooth = False
        item.data.validate(clean_customdata=True)
        item.data.update()
        vertex_count += len(item.data.vertices)
        triangle_count += len(item.data.polygons)
        item.select_set(False)

    bpy.ops.file.pack_all()
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(
        filepath=os.path.abspath(args.output),
        export_format="GLB",
        use_selection=True,
        export_apply=True,
        export_yup=True,
    )
    report = {
        "status": "normalized",
        "processor": "Blender",
        "blender_version": bpy.app.version_string,
        "input": os.path.basename(args.input),
        "output": os.path.basename(args.output),
        "mesh_objects": len(meshes),
        "vertices": vertex_count,
        "triangles": triangle_count,
        "creator_review_required": True,
        "semantic_repair_performed": False,
    }
    with open(args.report, "w", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
