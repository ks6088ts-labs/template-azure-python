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


class CreateTask:
    def __init__(self, repository: TaskRepository) -> None:
        self._repository = repository

    async def __call__(self, command: CreateTaskCommand) -> Task:
        task = Task.create(title=command.title, description=command.description)
        await self._repository.add(task)
        return task


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
        if not await self._repository.update(updated):
            raise TaskNotFoundError(command.task_id)
        return updated


class DeleteTask:
    def __init__(self, repository: TaskRepository) -> None:
        self._repository = repository

    async def __call__(self, task_id: TaskId) -> None:
        if not await self._repository.delete(task_id):
            raise TaskNotFoundError(task_id)
