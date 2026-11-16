from core.project_engine.manager import ProjectManager
from core.project_engine.models import ProjectCreate
def test_create_load(tmp_path):
    manager=ProjectManager(tmp_path); created=manager.create(ProjectCreate(name="Lost Planet",seed=123)); loaded=manager.load(created.id)
    assert loaded.project.name=="Lost Planet" and (tmp_path/created.id/"pgf.json").is_file()
