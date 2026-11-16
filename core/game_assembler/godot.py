import json
from pathlib import Path

from core.project_engine.models import ProjectDefinition, WorldDocument
from generators.terrain.heightfield import generate_heightfield
from generators.biomes.biome_map import generate_biome_map

PROJECT = """config_version=5
[application]
config/name="PGF Generated World"
run/main_scene="res://main.tscn"
[display]
window/size/viewport_width=1280
window/size/viewport_height=720
[rendering]
renderer/rendering_method="gl_compatibility"
renderer/rendering_method.mobile="gl_compatibility"
"""

SCENE = """[gd_scene load_steps=2 format=3]
[ext_resource type="Script" path="res://scripts/main.gd" id="1"]
[node name="PGFWorld" type="Node3D"]
script = ExtResource("1")
"""

MAIN = """extends Node3D

const Terrain = preload("res://scripts/terrain.gd")
const Player = preload("res://scripts/player.gd")

func _ready() -> void:
    var data: Dictionary = JSON.parse_string(FileAccess.get_file_as_string("res://pgf_world.json"))
    var terrain = Terrain.new()
    terrain.name = "GeneratedTerrain"
    terrain.configure(data)
    add_child(terrain)

    var sun = DirectionalLight3D.new()
    sun.rotation_degrees = Vector3(-48, float(data.get("sun_angle", -28)), 0)
    sun.light_energy = 1.25
    add_child(sun)

    var environment = WorldEnvironment.new()
    var settings = Environment.new()
    settings.background_mode = Environment.BG_SKY
    var sky = Sky.new()
    var sky_material = ProceduralSkyMaterial.new()
    sky_material.sky_top_color = Color("#142c49")
    sky_material.sky_horizon_color = Color("#9bb8c4")
    sky_material.ground_bottom_color = Color("#111923")
    sky_material.ground_horizon_color = Color("#667b86")
    sky.sky_material = sky_material
    settings.sky = sky
    settings.ambient_light_source = Environment.AMBIENT_SOURCE_SKY
    settings.ambient_light_energy = 0.55
    settings.fog_enabled = bool(data.get("fog", true))
    settings.fog_light_color = Color("#93aab7")
    settings.fog_density = 0.0018
    environment.environment = settings
    add_child(environment)

    var scene_data: Dictionary = JSON.parse_string(FileAccess.get_file_as_string("res://pgf_scene.json"))
    for item in scene_data.get("objects", []):
        _spawn_prop(item)

    var player = CharacterBody3D.new()
    player.name = "Player"
    player.set_script(Player)
    player.position = Vector3(0, float(data.get("spawn_height", 3.0)) + 2.0, 18)
    add_child(player)

    var camera = Camera3D.new()
    camera.name = "Camera3D"
    camera.position = Vector3(0, 1.65, 0)
    player.add_child(camera)
    camera.current = true

func _spawn_prop(item: Dictionary) -> void:
    var kind = str(item.get("kind", "crate"))
    var root = StaticBody3D.new()
    root.name = str(item.get("name", kind))
    root.position = Vector3(float(item.get("x", 0)), float(item.get("y", 0)), float(item.get("z", 0)))
    root.rotation.y = deg_to_rad(float(item.get("rotation", 0)))
    root.scale = Vector3.ONE * float(item.get("scale", 1))

    var tint = Color.from_string(str(item.get("color", "#8ba7c7")), Color("#8ba7c7"))
    var material = StandardMaterial3D.new()
    material.albedo_color = tint
    material.roughness = 0.82

    var visual = Node3D.new()
    visual.name = "Visual"
    root.add_child(visual)
    if kind == "outpost":
        _add_part(visual, BoxMesh.new(), Vector3(0, 2.0, 0), material, Vector3(8, 4, 8))
        _add_part(visual, BoxMesh.new(), Vector3(0, 4.25, 0), material, Vector3(8.6, 0.5, 8.6))
    elif kind == "beacon":
        _add_part(visual, CylinderMesh.new(), Vector3(0, 1.8, 0), material, Vector3(1.3, 3.6, 1.3))
        var glow = StandardMaterial3D.new()
        glow.albedo_color = Color("#6bd9ff")
        glow.emission_enabled = true
        glow.emission = Color("#42c8ff")
        _add_part(visual, SphereMesh.new(), Vector3(0, 3.9, 0), glow, Vector3(0.8, 0.8, 0.8))
    elif kind == "tree":
        _add_part(visual, CylinderMesh.new(), Vector3(0, 1.6, 0), material, Vector3(0.45, 3.2, 0.45))
        _add_part(visual, SphereMesh.new(), Vector3(0, 3.8, 0), material, Vector3(2.4, 2.8, 2.4))
    elif kind == "rock":
        _add_part(visual, SphereMesh.new(), Vector3(0, 0.9, 0), material, Vector3(2.2, 1.5, 1.8))
    else:
        _add_part(visual, BoxMesh.new(), Vector3(0, 0.9, 0), material, Vector3(1.8, 1.8, 1.8))

    var collider = CollisionShape3D.new()
    var bounds = BoxShape3D.new()
    if kind == "outpost":
        bounds.size = Vector3(8, 4.5, 8)
        collider.position.y = 2.2
    elif kind == "tree":
        bounds.size = Vector3(1.4, 4.5, 1.4)
        collider.position.y = 2.2
    elif kind == "beacon":
        bounds.size = Vector3(1.6, 4.2, 1.6)
        collider.position.y = 2.1
    elif kind == "rock":
        bounds.size = Vector3(2.2, 1.6, 1.8)
        collider.position.y = 0.8
    else:
        bounds.size = Vector3(1.8, 1.8, 1.8)
        collider.position.y = 0.9
    collider.shape = bounds
    root.add_child(collider)
    add_child(root)

func _add_part(parent: Node3D, mesh: Mesh, local_position: Vector3, material: Material, dimensions: Vector3) -> void:
    var instance = MeshInstance3D.new()
    instance.mesh = mesh
    instance.position = local_position
    instance.scale = dimensions
    instance.material_override = material
    parent.add_child(instance)
"""

PLAYER = """extends CharacterBody3D

@export var walk_speed: float = 7.0
@export var sprint_speed: float = 12.0
@export var jump_velocity: float = 5.0
@export var look_sensitivity: float = 0.0022

var gravity: float = ProjectSettings.get_setting("physics/3d/default_gravity")
@onready var camera: Camera3D = $Camera3D

func _ready() -> void:
    Input.mouse_mode = Input.MOUSE_MODE_CAPTURED

func _unhandled_input(event: InputEvent) -> void:
    if event is InputEventMouseMotion and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
        rotate_y(-event.relative.x * look_sensitivity)
        camera.rotate_x(-event.relative.y * look_sensitivity)
        camera.rotation.x = clampf(camera.rotation.x, deg_to_rad(-82), deg_to_rad(82))
    elif event is InputEventKey and event.pressed and event.keycode == KEY_ESCAPE:
        Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
    elif event is InputEventMouseButton and event.pressed and Input.mouse_mode == Input.MOUSE_MODE_VISIBLE:
        Input.mouse_mode = Input.MOUSE_MODE_CAPTURED

func _physics_process(delta: float) -> void:
    if not is_on_floor():
        velocity.y -= gravity * delta
    elif Input.is_key_just_pressed(KEY_SPACE):
        velocity.y = jump_velocity

    var input_axis = Vector2.ZERO
    input_axis.y = float(Input.is_key_pressed(KEY_S)) - float(Input.is_key_pressed(KEY_W))
    input_axis.x = float(Input.is_key_pressed(KEY_D)) - float(Input.is_key_pressed(KEY_A))
    var local_direction = Vector3(input_axis.x, 0, input_axis.y).normalized()
    var direction = (transform.basis * local_direction).normalized()
    var speed = sprint_speed if Input.is_key_pressed(KEY_SHIFT) else walk_speed
    velocity.x = direction.x * speed
    velocity.z = direction.z * speed
    move_and_slide()
"""

TERRAIN = """extends MeshInstance3D

func configure(data: Dictionary) -> void:
    var heights: Array = data.get("heights", [])
    var biomes: Array = data.get("biomes", [])
    if heights.is_empty():
        return
    var rows = heights.size()
    var cols = heights[0].size()
    var width = float(data.get("width", 96))
    var depth = float(data.get("depth", 96))
    var vertices = PackedVector3Array()
    var colors = PackedColorArray()
    var indices = PackedInt32Array()
    for z in range(rows):
        for x in range(cols):
            vertices.append(Vector3((float(x) / (cols - 1) - 0.5) * width, float(heights[z][x]), (float(z) / (rows - 1) - 0.5) * depth))
            var biome = str(biomes[z][x]) if biomes.size() == rows else "open-plains"
            colors.append(_biome_color(biome))
    for z in range(rows - 1):
        for x in range(cols - 1):
            var a = z * cols + x
            var b = a + 1
            var c = a + cols
            var d = c + 1
            indices.append_array(PackedInt32Array([a, c, b, b, c, d]))
    var arrays = []
    arrays.resize(Mesh.ARRAY_MAX)
    arrays[Mesh.ARRAY_VERTEX] = vertices
    arrays[Mesh.ARRAY_COLOR] = colors
    arrays[Mesh.ARRAY_INDEX] = indices
    var generated = ArrayMesh.new()
    generated.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
    mesh = generated

    var material = StandardMaterial3D.new()
    material.vertex_color_use_as_albedo = true
    material.roughness = 1.0
    material.cull_mode = BaseMaterial3D.CULL_DISABLED
    material_override = material

    var body = StaticBody3D.new()
    var collision = CollisionShape3D.new()
    var shape = ConcavePolygonShape3D.new()
    var collision_faces = PackedVector3Array()
    for index in indices:
        collision_faces.append(vertices[index])
    shape.set_faces(collision_faces)
    collision.shape = shape
    body.add_child(collision)
    add_child(body)

func _biome_color(name: String) -> Color:
    match name:
        "water": return Color("#315e78")
        "rocky-highlands": return Color("#777f86")
        "rocky-desert": return Color("#9b8061")
        "alien-forest": return Color("#416f62")
        _: return Color("#76866d")
"""

def _sample_height(heights, width, depth, x, z):
    rows = len(heights)
    cols = len(heights[0])
    gx = min(cols - 1, max(0.0, (x / width + 0.5) * (cols - 1)))
    gz = min(rows - 1, max(0.0, (z / depth + 0.5) * (rows - 1)))
    x0, z0 = int(gx), int(gz)
    x1, z1 = min(cols - 1, x0 + 1), min(rows - 1, z0 + 1)
    tx, tz = gx - x0, gz - z0
    top = float(heights[z0][x0]) * (1 - tx) + float(heights[z0][x1]) * tx
    bottom = float(heights[z1][x0]) * (1 - tx) + float(heights[z1][x1]) * tx
    return top * (1 - tz) + bottom * tz

def assemble_godot_project(definition: ProjectDefinition, destination: Path, world_state: dict | None = None) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "scripts").mkdir(exist_ok=True)
    document = WorldDocument.model_validate(world_state) if world_state else WorldDocument(seed=definition.project.seed, world=definition.world)
    settings = document.world
    heights = generate_heightfield(document.seed, settings.width, settings.depth, settings.resolution, settings.amplitude, settings.frequency)
    biomes = generate_biome_map(document.seed, heights)
    center_height = float(heights[len(heights) // 2][len(heights[0]) // 2])
    terrain_data = {
        "seed": document.seed, "width": settings.width, "depth": settings.depth,
        "heights": heights, "biomes": biomes, "spawn_height": center_height + 1.8,
        "sun_angle": document.sun_angle, "fog": document.fog, "water_level": document.water_level,
    }
    scene_objects = []
    for item in document.objects:
        record = item.model_dump(mode="json")
        record["y"] = round(float(record["y"]) + _sample_height(heights, settings.width, settings.depth, item.x, item.z), 4)
        scene_objects.append(record)
    (destination / "pgf_world.json").write_text(json.dumps(terrain_data), encoding="utf-8")
    (destination / "pgf_scene.json").write_text(json.dumps({"objects": scene_objects}, indent=2), encoding="utf-8")
    (destination / "project.godot").write_text(PROJECT, encoding="utf-8")
    (destination / "main.tscn").write_text(SCENE, encoding="utf-8")
    for filename, source in [("main.gd", MAIN), ("player.gd", PLAYER), ("terrain.gd", TERRAIN)]:
        (destination / "scripts" / filename).write_text(source, encoding="utf-8")
    (destination / "pgf_build.json").write_text(json.dumps({
        "project_id": definition.id, "generator_version": "0.2.0",
        "world_seed": document.seed, "scene_objects": len(scene_objects),
    }, indent=2), encoding="utf-8")
    return destination
