from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from threading import Lock
from time import sleep as default_sleep
from typing import Any, Callable, Literal, Protocol
from uuid import uuid4

from atlas.agent.runner import AgentRunner
from atlas.types import RunContext, Trajectory, utcnow

JobStatus = Literal["pending", "running", "succeeded", "failed"]


@dataclass
class Job:
    id: str
    task: str
    status: JobStatus = "pending"
    attempts: int = 0
    run_id: str | None = None
    result: Trajectory | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task": self.task,
            "status": self.status,
            "attempts": self.attempts,
            "run_id": self.run_id,
            "error": self.error,
            "stop_reason": self.result.stop_reason if self.result else None,
            "final_answer": self.result.final_answer if self.result else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "metadata": dict(self.metadata),
        }


class JobStore(Protocol):
    def save(self, job: Job) -> None:
        ...

    def get(self, job_id: str) -> Job | None:
        ...

    def claim(self) -> Job | None:
        ...

    def list(self) -> list[Job]:
        ...


class InMemoryJobStore:
    """进程内任务存储；``claim`` 用锁保证同一任务不会被重复领取。

    生产环境应使用带可见性超时与原子领取的队列（如 SQS、Redis、
    Temporal），否则进程崩溃后任务会停在 running 状态。
    """

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []
        self._lock = Lock()

    def save(self, job: Job) -> None:
        with self._lock:
            job.updated_at = utcnow()
            if job.id not in self._jobs:
                self._order.append(job.id)
            self._jobs[job.id] = deepcopy(job)

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return deepcopy(job) if job is not None else None

    def claim(self) -> Job | None:
        with self._lock:
            for job_id in self._order:
                job = self._jobs[job_id]
                if job.status == "pending":
                    job.status = "running"
                    job.updated_at = utcnow()
                    return deepcopy(job)
            return None

    def list(self) -> list[Job]:
        with self._lock:
            return [deepcopy(self._jobs[job_id]) for job_id in self._order]

    def stats(self) -> dict[str, int]:
        with self._lock:
            counts = {"pending": 0, "running": 0, "succeeded": 0, "failed": 0}
            for job in self._jobs.values():
                counts[job.status] = counts.get(job.status, 0) + 1
            return counts


class JobRunner:
    """把一次 Agent 运行包装成可重试、可持久化的任务。

    失败判定同时覆盖异常与 ``stop_reason="error"``；后者是 Agent
    内部捕获模型异常后的返回路径，不会以异常形式冒泡。
    """

    def __init__(
        self,
        runner: AgentRunner,
        store: JobStore | None = None,
        *,
        max_attempts: int = 2,
        retry_delay: float = 0.0,
        retry_stop_reasons: tuple[str, ...] = ("error",),
        sleep: Callable[[float], None] = default_sleep,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self.runner = runner
        self.store = store or InMemoryJobStore()
        self.max_attempts = max_attempts
        self.retry_delay = retry_delay
        self.retry_stop_reasons = set(retry_stop_reasons)
        self.sleep = sleep

    def submit(
        self,
        task: str,
        *,
        job_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Job:
        job = Job(
            id=job_id or f"job-{uuid4().hex[:8]}",
            task=task,
            metadata=dict(metadata or {}),
        )
        if self.store.get(job.id) is not None:
            raise ValueError(f"job already exists: {job.id}")
        self.store.save(job)
        return job

    def run_once(self) -> Job | None:
        job = self.store.claim()
        if job is None:
            return None

        job.attempts += 1
        job.run_id = job.run_id or f"{job.id}-attempt-{job.attempts}"
        ctx = RunContext(
            run_id=job.run_id,
            metadata={"job_id": job.id, "attempt": job.attempts},
        )
        try:
            trajectory = self.runner.run(job.task, ctx)
            job.result = trajectory
            if trajectory.stop_reason in self.retry_stop_reasons:
                raise RuntimeError(f"agent stopped with {trajectory.stop_reason}")
            job.status = "succeeded"
            job.error = None
        except Exception as exc:
            job.error = f"{type(exc).__name__}: {exc}"
            if job.attempts < self.max_attempts:
                job.status = "pending"
                self.store.save(job)
                if self.retry_delay:
                    self.sleep(self.retry_delay)
                return job
            job.status = "failed"

        self.store.save(job)
        return job

    def drain(self, *, max_jobs: int = 100) -> list[Job]:
        """顺序处理到没有待办任务为止；返回每个任务的最终快照。"""
        processed: dict[str, Job] = {}
        for _ in range(max_jobs):
            job = self.run_once()
            if job is None:
                break
            processed[job.id] = job
        return list(processed.values())

    def stats(self) -> dict[str, int]:
        if hasattr(self.store, "stats"):
            return self.store.stats()
        counts = {"pending": 0, "running": 0, "succeeded": 0, "failed": 0}
        for job in self.store.list():
            counts[job.status] = counts.get(job.status, 0) + 1
        return counts
