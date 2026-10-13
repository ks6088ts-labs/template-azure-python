from dataclasses import dataclass

from template_azure_python.application.ports import TaskRepository
from template_azure_python.domain import Task, TaskId, TaskStatus


class TaskNotFoundError(LookupError):
    def __init__(self, task_id: TaskId) -> None:
        self.task_id = task_id
        super().__init__(f"Task {task_id} was not found")


class TaskAlreadyExistsError(RuntimeError):
    def __init__(self, task_id: TaskId) -> None:
        self.task_id = task_id
        super().__init__(f"Task {task_id} already exists")


class TaskRepositoryError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Task storage is unavailable")


class TaskPreconditionError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("The task has changed; fetch its current ETag and retry")


class TaskReadOnlyError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("This Task repository is read-only")


@dataclass(frozen=True, slots=True)
class CreateTaskCommand:
    title: str
    description: str = ""


@dataclass(frozen=True, slots=True)
class UpdateTaskCommand:
    task_id: TaskId
    title: str
    description: str
    status: TaskStatus
    expected_etag: str | None = None


class CreateTask:
    def __init__(self, repository: TaskRepository) -> None:
        self._repository = repository

    async def __call__(self, command: CreateTaskCommand) -> Task:
        task = Task.create(title=command.title, description=command.description)
        await self._repository.add(task)
        stored = await self._repository.get(task.id)
        if stored is None:
            raise TaskRepositoryError()
        return stored


class GetTask:
    def __init__(self, repository: TaskRepository) -> None:
        self._repository = repository

    async def __call__(self, task_id: TaskId) -> Task:
        task = await self._repository.get(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        return task


class ListTasks:
    def __init__(self, repository: TaskRepository) -> None:
        self._repository = repository

    async def __call__(self) -> tuple[Task, ...]:
        return await self._repository.list()

    async def page(self, *, offset: int = 0, limit: int = 100) -> tuple[tuple[Task, ...], int]:
        if offset < 0 or not 1 <= limit <= 100:
            raise ValueError("Pagination requires offset >= 0 and limit between 1 and 100")
        return await self._repository.page(offset=offset, limit=limit)


class UpdateTask:
    def __init__(self, repository: TaskRepository) -> None:
        self._repository = repository

    async def __call__(self, command: UpdateTaskCommand) -> Task:
        existing = await self._repository.get(command.task_id)
        if existing is None:
            raise TaskNotFoundError(command.task_id)
        updated = existing.update(
            title=command.title,
            description=command.description,
            status=command.status,
        )
        if not await self._repository.update(updated, expected_etag=command.expected_etag):
            raise TaskNotFoundError(command.task_id)
        stored = await self._repository.get(command.task_id)
        if stored is None:
            raise TaskNotFoundError(command.task_id)
        return stored


class DeleteTask:
    def __init__(self, repository: TaskRepository) -> None:
        self._repository = repository

    async def __call__(self, task_id: TaskId, *, expected_etag: str | None = None) -> None:
        if not await self._repository.delete(task_id, expected_etag=expected_etag):
            raise TaskNotFoundError(task_id)
