from asyncio import Lock
from dataclasses import replace
from itertools import islice
from uuid import uuid4

from template_azure_python.application import TaskAlreadyExistsError, TaskPreconditionError
from template_azure_python.domain import Task, TaskId


class InMemoryTaskRepository:
    def __init__(self) -> None:
        self._tasks: dict[TaskId, Task] = {}
        self._lock = Lock()

    async def add(self, task: Task) -> None:
        async with self._lock:
            if task.id in self._tasks:
                raise TaskAlreadyExistsError(task.id)
            self._tasks[task.id] = replace(task, etag=f'"{uuid4()}"')

    async def get(self, task_id: TaskId) -> Task | None:
        async with self._lock:
            return self._tasks.get(task_id)

    async def list(self) -> tuple[Task, ...]:
        async with self._lock:
            return tuple(self._tasks.values())

    async def page(self, *, offset: int, limit: int) -> tuple[tuple[Task, ...], int]:
        async with self._lock:
            return tuple(islice(self._tasks.values(), offset, offset + limit)), len(self._tasks)

    async def ping(self) -> None:
        return None

    async def update(self, task: Task, *, expected_etag: str | None = None) -> bool:
        async with self._lock:
            if task.id not in self._tasks:
                return False
            if expected_etag is not None and expected_etag != self._tasks[task.id].etag:
                raise TaskPreconditionError()
            self._tasks[task.id] = replace(task, etag=f'"{uuid4()}"')
            return True

    async def delete(self, task_id: TaskId, *, expected_etag: str | None = None) -> bool:
        async with self._lock:
            existing = self._tasks.get(task_id)
            if existing is not None and expected_etag is not None and expected_etag != existing.etag:
                raise TaskPreconditionError()
            return self._tasks.pop(task_id, None) is not None
