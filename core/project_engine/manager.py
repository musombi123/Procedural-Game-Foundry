from pathlib import Path
from uuid import uuid4
from .models import ProjectCreate, ProjectDefinition, safe_slug

class ProjectManager:
    def __init__(self, root: Path):
        self.root=root.resolve(); self.root.mkdir(parents=True,exist_ok=True)
    def path_for(self,pid: str) -> Path:
        if not pid or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in pid): raise ValueError("Invalid project id")
        path=(self.root/pid).resolve()
        if self.root not in path.parents: raise ValueError("Project path escapes workspace")
        return path
    def create(self,request: ProjectCreate) -> ProjectDefinition:
        pid=f"{safe_slug(request.name)}-{uuid4().hex[:8]}"
        definition=ProjectDefinition(id=pid,project=request)
        folder=self.path_for(pid); folder.mkdir(parents=True,exist_ok=False)
        (folder/"pgf.json").write_text(definition.model_dump_json(indent=2),encoding="utf-8")
        for name in ("assets","generated"): (folder/name).mkdir()
        return definition
    def load(self,pid: str) -> ProjectDefinition:
        file=self.path_for(pid)/"pgf.json"
        if not file.is_file(): raise FileNotFoundError(pid)
        return ProjectDefinition.model_validate_json(file.read_text(encoding="utf-8"))
    def list(self):
        result=[]
        for file in self.root.glob("*/pgf.json"):
            try: result.append(ProjectDefinition.model_validate_json(file.read_text(encoding="utf-8")))
            except Exception: continue
        return result
