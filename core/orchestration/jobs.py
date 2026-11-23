"""Durable, per-project production job journal for NEXORA.

Job metadata is stored inside each owner-scoped project folder. It deliberately
uses the existing local project filesystem rather than introducing another DB.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
import json
import re
from threading import RLock
from pathlib import Path
from typing import Any
from uuid import uuid4


class JobState(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    VALIDATING = "VALIDATING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"
    RECOVERED = "RECOVERED"


_ACTIVE_STATES = {JobState.QUEUED, JobState.RUNNING, JobState.VALIDATING}
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,100}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Job:
    id: str
    project_id: str
    state: JobState = JobState.QUEUED
    progress: int = 0
    message: str = "Queued"
    error: str | None = None
    created_at: str = ""
    updated_at: str = ""
    kind: str = ""
    target: str = ""

    @classmethod
    def create(cls, pid: str, kind: str = "", target: str = "") -> "Job":
        timestamp = _now()
        return cls(
            id=uuid4().hex,
            project_id=str(pid),
            created_at=timestamp,
            updated_at=timestamp,
            kind=str(kind or ""),
            target=str(target or ""),
        )

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        state = data.get("state")
        data["state"] = state.value if isinstance(state, JobState) else str(state)
        return data


class JobRegistry:
    """Thread-safe job registry backed by workspace_jobs/<id>.job.json."""

    def __init__(self, manager: Any | None = None):
        self._jobs: dict[str, Job] = {}
        self._lock = RLock()
        self._manager = manager
        self._loaded_projects: set[str] = set()

    def bind_manager(self, manager: Any) -> None:
        """Bind the current ProjectManager; its root may change after workspace migration."""
        with self._lock:
            self._manager = manager
            self._loaded_projects.clear()

    def _job_path(self, project_id: str, job_id: str) -> Path | None:
        if not self._manager or not _SAFE_ID.fullmatch(str(project_id)) or not _SAFE_ID.fullmatch(str(job_id)):
            return None
        try:
            folder = self._manager.path_for(str(project_id)).resolve()
            root = (folder / "workspace_jobs").resolve()
            if folder not in root.parents:
                return None
            return root / f"{job_id}.job.json"
        except (OSError, ValueError, RuntimeError):
            return None

    def _persist_locked(self, job: Job) -> None:
        path = self._job_path(job.project_id, job.id)
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema_version": 1, **job.as_dict()}
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(path)

    @staticmethod
    def _from_record(record: dict[str, Any], project_id: str) -> Job | None:
        job_id = str(record.get("id") or "")
        if not _SAFE_ID.fullmatch(job_id) or str(record.get("project_id") or project_id) != project_id:
            return None
        try:
            state = JobState(str(record.get("state") or "RECOVERED").upper())
        except ValueError:
            state = JobState.RECOVERED
        try:
            progress = max(0, min(100, int(record.get("progress") or 0)))
        except (TypeError, ValueError):
            progress = 0
        return Job(
            id=job_id,
            project_id=project_id,
            state=state,
            progress=progress,
            message=str(record.get("message") or "Recovered production job")[:1000],
            error=(str(record["error"])[:4000] if record.get("error") else None),
            created_at=str(record.get("created_at") or _now()),
            updated_at=str(record.get("updated_at") or record.get("created_at") or _now()),
            kind=str(record.get("kind") or "")[:80],
            target=str(record.get("target") or "")[:40],
        )

    def _load_project_locked(self, project_id: str) -> None:
        if project_id in self._loaded_projects:
            return
        self._loaded_projects.add(project_id)
        if not self._manager or not _SAFE_ID.fullmatch(str(project_id)):
            return
        try:
            folder = self._manager.path_for(project_id).resolve()
            root = (folder / "workspace_jobs").resolve()
            if folder not in root.parents or not root.is_dir():
                return
        except (OSError, ValueError, RuntimeError):
            return

        seen: set[str] = set()
        for path in sorted(root.glob("*.job.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(record, dict):
                continue
            job = self._from_record(record, project_id)
            if not job or path.name != f"{job.id}.job.json":
                continue
            # A local agent restart cannot resume an in-flight OS process.
            # Preserve its record and artifacts, but never report it as running.
            if job.state in _ACTIVE_STATES:
                job.state = JobState.INTERRUPTED
                job.progress = min(job.progress, 99)
                job.message = "The Local Agent restarted before this job completed. Existing logs and artifacts were retained."
                job.error = "Execution was interrupted by a Local Agent restart."
                job.updated_at = _now()
                self._persist_locked(job)
            self._jobs[job.id] = job
            seen.add(job.id)

        # Backward compatibility: earlier releases wrote owner and artifact
        # manifests but did not journal job state. Surface those outputs without
        # pretending that the original job status was recorded.
        for owner_path in sorted(root.glob("*.owner.json")):
            job_id = owner_path.name[:-len(".owner.json")]
            if job_id in seen or not _SAFE_ID.fullmatch(job_id):
                continue
            try:
                owner_record = json.loads(owner_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(owner_record, dict) or not owner_record.get("user_id"):
                continue
            artifacts_path = root / f"{job_id}.json"
            artifacts = []
            if artifacts_path.is_file():
                try:
                    raw = json.loads(artifacts_path.read_text(encoding="utf-8"))
                    if isinstance(raw, dict) and isinstance(raw.get("artifacts"), list):
                        artifacts = raw["artifacts"]
                except (OSError, ValueError):
                    artifacts = []
            job = Job(
                id=job_id,
                project_id=project_id,
                state=JobState.RECOVERED,
                progress=100 if artifacts else 0,
                message="Recovered legacy job metadata. Its original execution status was not saved by the previous NEXORA version.",
                created_at=datetime.fromtimestamp(owner_path.stat().st_mtime, timezone.utc).isoformat(),
                updated_at=_now(),
            )
            self._jobs[job.id] = job
            self._persist_locked(job)

    def add(self, job: Job) -> Job:
        with self._lock:
            if not job.updated_at:
                job.updated_at = _now()
            self._jobs[job.id] = job
            self._persist_locked(job)
            return job

    def get(self, jid: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(jid)
            if job:
                return job
            if self._manager:
                for definition in self._manager.list():
                    self._load_project_locked(str(definition.id))
                    job = self._jobs.get(jid)
                    if job:
                        return job
            return None

    def update(self, jid: str, **values: Any) -> Job:
        with self._lock:
            job = self._jobs[jid]
            for key, value in values.items():
                setattr(job, key, value)
            job.updated_at = _now()
            self._persist_locked(job)
            return job

    def list_for_project(self, project_id: str) -> list[Job]:
        with self._lock:
            project_id = str(project_id)
            self._load_project_locked(project_id)
            matching = [job for job in self._jobs.values() if job.project_id == project_id]
            return sorted(matching, key=lambda item: item.created_at, reverse=True)
