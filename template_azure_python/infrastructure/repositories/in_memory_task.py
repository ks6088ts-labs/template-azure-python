from asyncio import Lock

from template_azure_python.application import TaskAlreadyExistsError
from template_azure_python.domain import Task, TaskId


class InMemoryTaskRepository:
    def __init__(self) -> None:
        self._tasks: dict[TaskId, Task] = {}
        self._lock = Lock()

    async def add(self, task: Task) -> None:
        async with self._lock:
            if task.id in self._tasks:
                raise TaskAlreadyExistsError(task.id)
            self._tasks[task.id] = task

    async def get(self, task_id: TaskId) -> Task | None:
        async with self._lock:
            return self._tasks.get(task_id)

    async def list(self) -> tuple[Task, ...]:
        async with self._lock:
            return tuple(self._tasks.values())

    async def update(self, task: Task) -> bool:
        async with self._lock:
            if task.id not in self._tasks:
                return False
            self._tasks[task.id] = task
            return True

    async def delete(self, task_id: TaskId) -> bool:
        async with self._lock:
            return self._tasks.pop(task_id, None) is not None
