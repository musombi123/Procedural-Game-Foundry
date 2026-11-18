from core.project_engine.manager import ProjectManager
from core.project_engine.models import ProjectCreate, WorldDocument, SceneObject


def test_create_load(tmp_path):
    manager = ProjectManager(tmp_path)
    created = manager.create(ProjectCreate(name="Lost Planet", seed=123))
    loaded = manager.load(created.id)
    assert loaded.project.name == "Lost Planet"
    assert (tmp_path / created.id / "pgf.json").is_file()


def test_create_records_initial_revision(tmp_path):
    manager = ProjectManager(tmp_path)
    created = manager.create(ProjectCreate(name="Versioned World", seed=123))
    versions = manager.list_versions(created.id)
    assert len(versions) == 1
    assert versions[0]["revision"] == 1
    assert versions[0]["reason"] == "project-created"


def test_autosave_creates_immutable_revisions_and_deduplicates(tmp_path):
    manager = ProjectManager(tmp_path)
    created = manager.create(ProjectCreate(name="Autosave World", seed=456))
    first = WorldDocument(seed=456)
    unchanged = manager.save_world(created.id, first, reason="autosave")
    assert unchanged["revision"] == 1
    assert unchanged["unchanged"] is True

    changed = WorldDocument(seed=456, objects=[
        SceneObject(id="crate-1", name="Supply crate", kind="crate", x=2, z=4)
    ])
    saved = manager.save_world(created.id, changed, reason="autosave")
    assert saved["revision"] == 2
    assert saved["unchanged"] is False
    assert len(manager.list_versions(created.id)) == 2
    loaded_world = WorldDocument.model_validate_json(
        (manager.path_for(created.id) / "world.json").read_text(encoding="utf-8")
    )
    assert len(loaded_world.objects) == 1


def test_restore_creates_a_new_revision_instead_of_mutating_history(tmp_path):
    manager = ProjectManager(tmp_path)
    created = manager.create(ProjectCreate(name="Restore World", seed=789))
    original = WorldDocument(seed=789)
    manager.save_world(created.id, original)
    changed = WorldDocument(seed=789, water_level=3.0)
    manager.save_world(created.id, changed)

    restored = manager.restore_version(created.id, 1)
    assert restored["restored_from"] == 1
    assert restored["revision"] == 3
    current = WorldDocument.model_validate_json(
        (manager.path_for(created.id) / "world.json").read_text(encoding="utf-8")
    )
    assert current.water_level == original.water_level
    assert [item["revision"] for item in manager.list_versions(created.id)] == [3, 2, 1]
