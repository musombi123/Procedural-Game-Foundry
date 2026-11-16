from dataclasses import dataclass,asdict
from enum import StrEnum
from datetime import datetime,timezone
from threading import RLock
from uuid import uuid4
class JobState(StrEnum):
    QUEUED="QUEUED"; RUNNING="RUNNING"; VALIDATING="VALIDATING"; COMPLETED="COMPLETED"; FAILED="FAILED"
@dataclass
class Job:
    id: str
    project_id: str
    state: JobState=JobState.QUEUED
    progress: int=0
    message: str="Queued"
    error: str|None=None
    created_at: str=""
    @classmethod
    def create(cls,pid): return cls(uuid4().hex,pid,created_at=datetime.now(timezone.utc).isoformat())
    def as_dict(self):
        data=asdict(self); data["state"]=self.state.value; return data
class JobRegistry:
    def __init__(self): self._jobs={}; self._lock=RLock()
    def add(self,job):
        with self._lock: self._jobs[job.id]=job
        return job
    def get(self,jid):
        with self._lock: return self._jobs.get(jid)
    def update(self,jid,**values):
        with self._lock:
            job=self._jobs[jid]
            for key,value in values.items(): setattr(job,key,value)
            return job
