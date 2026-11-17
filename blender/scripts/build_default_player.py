"""Create a neutral, non-photorealistic default player mesh for workspace projects.

This is a placeholder creator can replace with a licensed or self-authored GLB.
It does not synthesize or claim a real person's likeness.
"""
import argparse
import sys
from pathlib import Path
import bpy


def arguments():
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    return parser.parse_args(values)


def material(name, color, metallic=0.0):
    value = bpy.data.materials.new(name)
    value.diffuse_color = (*color, 1.0)
    value.metallic = metallic
    value.roughness = 0.72
    return value


def add_sphere(name, location, scale, surface):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=8, radius=1, location=location)
    item = bpy.context.object
    item.name = name
    item.scale = scale
    item.data.materials.append(surface)
    return item


def add_cylinder(name, location, radius, depth, surface):
    bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=radius, depth=depth, location=location)
    item = bpy.context.object
    item.name = name
    item.data.materials.append(surface)
    return item


def main():
    args = arguments()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    cloth = material("NEXORA_Default_Cloth", (0.12, 0.31, 0.52))
    trim = material("NEXORA_Default_Trim", (0.055, 0.09, 0.14), 0.18)
    face = material("NEXORA_Default_Face", (0.48, 0.31, 0.22))
    add_sphere("Player_Torso", (0, 0, 1.18), (0.39, 0.25, 0.58), cloth)
    add_sphere("Player_Head", (0, 0, 1.94), (0.25, 0.24, 0.29), face)
    add_cylinder("Player_Left_Arm", (-0.48, 0, 1.2), 0.13, 0.92, cloth)
    add_cylinder("Player_Right_Arm", (0.48, 0, 1.2), 0.13, 0.92, cloth)
    add_cylinder("Player_Left_Leg", (-0.17, 0, 0.43), 0.16, 0.82, trim)
    add_cylinder("Player_Right_Leg", (0.17, 0, 0.43), 0.16, 0.82, trim)
    add_sphere("Player_Left_Hand", (-0.49, 0, 0.69), (0.13, 0.13, 0.14), face)
    add_sphere("Player_Right_Hand", (0.49, 0, 0.69), (0.13, 0.13, 0.14), face)
    bpy.ops.object.select_all(action="SELECT")
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=str(Path(args.output).resolve()), export_format="GLB", use_selection=True)
    if not Path(args.output).is_file() or Path(args.output).stat().st_size < 1024:
        raise RuntimeError("Blender did not produce the default player GLB.")
    print("NEXORA_DEFAULT_PLAYER_READY")


if __name__ == "__main__":
    main()
