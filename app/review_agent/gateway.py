"""Persistence is an injected A-side adapter. This module never opens a database."""
from typing import Protocol

from .models import Attempt, Failure, ReviewError, ReviewResult, RunMeta, TaskInput


class TaskGateway(Protocol):
    async def load(self, task_id: str) -> TaskInput: ...
    async def claim(self, task: TaskInput, meta: RunMeta) -> bool: ...
    async def audit(self, attempt: Attempt) -> None: ...
    async def complete(self, result: ReviewResult) -> None: ...
    async def fail(self, failure: Failure) -> None: ...


class MemoryGateway:
    """Runnable reference adapter, used for local acceptance, not database storage."""
    def __init__(self, tasks):
        self.tasks = {t.task_id: t.model_copy(deep=True) for t in tasks}
        self.states = dict.fromkeys(self.tasks, "ready")
        self.meta = {}
        self.results = {}
        self.failures = {}
        self.attempts = []

    async def load(self, task_id):
        if task_id not in self.tasks:
            raise ReviewError("task_not_found", "找不到此评审任务。")
        return self.tasks[task_id].model_copy(deep=True)

    async def claim(self, task, meta):
        if self.states.get(task.task_id) != "ready" or self.tasks[task.task_id] != task:
            return False
        self.states[task.task_id] = "running"
        self.meta[task.task_id] = meta
        return True

    async def audit(self, attempt):
        if self.states.get(attempt.task_id) != "running":
            raise ReviewError("task_not_running", "任务不在评审中。")
        self.attempts.append(attempt)

    async def complete(self, result):
        task_id = result.meta.task_id
        if self.states.get(task_id) != "running":
            raise ReviewError("task_not_running", "任务不在评审中。")
        self.results[task_id] = result
        self.meta[task_id] = result.meta
        self.states[task_id] = "completed"

    async def fail(self, failure):
        task_id = failure.meta.task_id
        if self.states.get(task_id) != "running":
            raise ReviewError("task_not_running", "任务不在评审中。")
        self.failures[task_id] = failure
        self.meta[task_id] = failure.meta
        self.states[task_id] = "failed"
