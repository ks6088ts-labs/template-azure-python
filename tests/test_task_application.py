import asyncio
from uuid import UUID

import pytest

from template_azure_python.application import (
    CreateTask,
    CreateTaskCommand,
    DeleteTask,
    GetTask,
    ListTasks,
    TaskAlreadyExistsError,
    TaskNotFoundError,
    UpdateTask,
    UpdateTaskCommand,
)
from template_azure_python.domain import Task, TaskId, TaskStatus
from template_azure_python.infrastructure import InMemoryTaskRepository

TASK_ID = TaskId(UUID("00000000-0000-0000-0000-000000000001"))
MISSING_ID = TaskId(UUID("00000000-0000-0000-0000-000000000002"))


def test_task_use_cases_cover_crud():
    async def scenario() -> None:
        repository = InMemoryTaskRepository()
        created = await CreateTask(repository)(CreateTaskCommand(title="First", description="Details"))

        assert await GetTask(repository)(created.id) == created
        assert await ListTasks(repository)() == (created,)

        updated = await UpdateTask(repository)(
            UpdateTaskCommand(
                task_id=created.id,
                title="Updated",
                description="Complete",
                status=TaskStatus.DONE,
            )
        )
        assert updated.status is TaskStatus.DONE
        assert await GetTask(repository)(created.id) == updated

        await DeleteTask(repository)(created.id)
        assert await ListTasks(repository)() == ()

    asyncio.run(scenario())


@pytest.mark.parametrize("operation", ["get", "update", "delete"])
def test_task_use_cases_report_missing_task(operation: str):
    async def scenario() -> None:
        repository = InMemoryTaskRepository()
        with pytest.raises(TaskNotFoundError, match=str(MISSING_ID)):
            if operation == "get":
                await GetTask(repository)(MISSING_ID)
            elif operation == "update":
                await UpdateTask(repository)(
                    UpdateTaskCommand(
                        task_id=MISSING_ID,
                        title="Missing",
                        description="",
                        status=TaskStatus.TODO,
                    )
                )
            else:
                await DeleteTask(repository)(MISSING_ID)

    asyncio.run(scenario())


def test_in_memory_repository_contract_and_duplicate_detection():
    async def scenario() -> None:
        repository = InMemoryTaskRepository()
        task = Task(id=TASK_ID, title="First", description="", status=TaskStatus.TODO)
        await repository.add(task)

        with pytest.raises(TaskAlreadyExistsError, match=str(TASK_ID)):
            await repository.add(task)

        replacement = task.update(title="Second", description="", status=TaskStatus.IN_PROGRESS)
        assert await repository.update(replacement)
        assert await repository.get(TASK_ID) == replacement
        assert await repository.delete(TASK_ID)
        assert not await repository.delete(TASK_ID)
        assert not await repository.update(replacement)

    asyncio.run(scenario())
