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



def test_creator_glb_asset_is_referenced_by_native_godot_scene():
    asset_id = "22222222-2222-4222-8222-222222222222"
    project = {
        "name": "NEXORA Asset Binding",
        "document": {
            "scene": {
                "objects": [{
                    "id": "mesh-node",
                    "name": "Uploaded Player Mesh",
                    "type": "MeshInstance3D",
                    "position": [0, 0, 0],
                    "rotation": [0, 0, 0],
                    "scale": [1, 1, 1],
                    "asset_id": asset_id,
                }]
            }
        },
    }
    definition, world = build_documents(
        "11111111-1111-4111-8111-111111111111",
        project,
        {asset_id: f"res://assets/{asset_id}.glb"},
    )
    assert world.objects[0].asset_path == f"res://assets/{asset_id}.glb"

def test_worker_android_package_id_matches_release_smoke_test(tmp_path):
    from services.worker.runner import _write_export_presets

    _write_export_presets(tmp_path)
    presets = (tmp_path / "export_presets.cfg").read_text(encoding="utf-8")
    assert 'package/unique_name="com.nexora.foundry"' in presets
    assert 'package/unique_name="org.nexora.foundry"' not in presets
