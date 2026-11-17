from core.game_assembler.workspace_adapter import build_documents


def test_workspace_document_maps_to_native_godot_world():
    project = {
        "name": "NEXORA Test",
        "description": "creator brief",
        "document": {
            "seed": 42,
            "settings": {"dimension": "3d"},
            "scene": {
                "objects": [{
                    "id": "node_01",
                    "name": "Signal Beacon",
                    "type": "MeshInstance3D",
                    "position": [12, 2, -8],
                    "rotation": [0, 90, 0],
                    "scale": [1, 1, 1],
                }]
            },
        },
    }
    definition, world = build_documents("11111111-1111-4111-8111-111111111111", project)
    assert definition.project.name == "NEXORA Test"
    assert world.seed == 42
    assert len(world.objects) == 1
    assert world.objects[0].kind == "beacon"
    assert world.objects[0].x == 12
    assert world.objects[0].z == -8
    assert world.objects[0].rotation == 90
