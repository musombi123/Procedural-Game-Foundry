from core.asset_registry.registry import AssetRegistry
def test_register_asset_with_provenance(tmp_path):
    (tmp_path/"rock.glb").write_bytes(b"test-mesh")
    registry=AssetRegistry(tmp_path)
    record=registry.register("rock-01","rock.glb","mesh","CC0")
    assert record["checksum"] and registry.list()[0]["asset_id"]=="rock-01"
