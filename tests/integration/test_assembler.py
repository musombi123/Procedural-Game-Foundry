from core.project_engine.models import ProjectCreate,ProjectDefinition
from core.game_assembler.godot import assemble_godot_project
from core.validation.validator import validate_project
def test_assembly(tmp_path):
    definition=ProjectDefinition(id="test-world",project=ProjectCreate(name="Test World",seed=10)); folder=tmp_path/"test-world"; folder.mkdir(); (folder/"pgf.json").write_text(definition.model_dump_json()); assemble_godot_project(definition,folder/"game")
    assert validate_project(folder)["valid"]
