from datetime import datetime, timezone
from pathlib import Path
from .models import PipelineDocument, StageId, StageState, STAGE_ORDER

class PipelineError(ValueError):
    pass

class PipelineStore:
    def __init__(self, project_folder: Path):
        self.folder = project_folder / "movie_pipeline"
        self.folder.mkdir(parents=True, exist_ok=True)
        self.path = self.folder / "pipeline.json"

    def save(self, document: PipelineDocument) -> PipelineDocument:
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(document.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(self.path)
        return document

    def load(self) -> PipelineDocument:
        if not self.path.is_file():
            raise FileNotFoundError("Movie pipeline has not been created")
        return PipelineDocument.model_validate_json(self.path.read_text(encoding="utf-8"))

    def approve(self, stage_id: StageId, note: str = "") -> PipelineDocument:
        document = self.load()
        records = {record.stage: record for record in document.stages}
        current = records[stage_id]
        if current.state != StageState.REVIEW:
            raise PipelineError("Only a stage in REVIEW can be approved")
        current.state = StageState.APPROVED
        current.summary = note.strip() or "Approved by creator"
        current.updated_at = datetime.now(timezone.utc).isoformat()
        index = STAGE_ORDER.index(stage_id)
        if index + 1 < len(STAGE_ORDER):
            next_stage = records[STAGE_ORDER[index + 1]]
            if next_stage.state == StageState.LOCKED:
                next_stage.state = StageState.READY
                next_stage.summary = "Prerequisite approved; ready for processing"
                document.active_stage = next_stage.stage
        return self.save(document)

    def regenerate(self, stage_id: StageId) -> PipelineDocument:
        document = self.load()
        records = {record.stage: record for record in document.stages}
        current = records[stage_id]
        if current.state not in (StageState.REVIEW, StageState.FAILED, StageState.APPROVED):
            raise PipelineError("A stage can only be regenerated after it has output or failed")
        index = STAGE_ORDER.index(stage_id)
        for downstream in STAGE_ORDER[index:]:
            record = records[downstream]
            record.revision += 1
            record.progress = 0
            record.output = {}
            record.error = None
            record.state = StageState.READY if downstream == stage_id else StageState.LOCKED
            record.summary = "Ready for regeneration" if downstream == stage_id else "Waiting for regenerated prerequisite"
        document.active_stage = stage_id
        return self.save(document)

    def mark_review(self, stage_id: StageId, output: dict, summary: str) -> PipelineDocument:
        document = self.load()
        record = next((item for item in document.stages if item.stage == stage_id), None)
        if record is None or record.state != StageState.RUNNING:
            raise PipelineError("Stage must be RUNNING before output can enter review")
        record.state = StageState.REVIEW
        record.progress = 100
        record.output = output
        record.summary = summary
        record.error = None
        return self.save(document)
