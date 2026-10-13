import asyncio
from unittest.mock import AsyncMock, create_autospec

import pytest
from azure.core import MatchConditions
from azure.cosmos.aio import ContainerProxy
from azure.cosmos.exceptions import CosmosHttpResponseError

from template_azure_python.application import TaskPreconditionError
from template_azure_python.domain import InvalidTaskError, Task, TaskStatus
from template_azure_python.infrastructure import CosmosdbTaskRepository, InMemoryTaskRepository


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_in_memory_conditional_mutations_are_atomic():
    repository = InMemoryTaskRepository()
    task = Task.create("Original")
    await repository.add(task)
    original = await repository.get(task.id)
    assert original is not None and original.etag

    async def mutate(index):
        return await repository.update(
            task.update(title=f"Writer {index}", description="", status=TaskStatus.DONE),
            expected_etag=original.etag,
        )

    results = await asyncio.gather(*(mutate(index) for index in range(10)), return_exceptions=True)
    assert results.count(True) == 1
    assert sum(isinstance(result, TaskPreconditionError) for result in results) == 9
    current = await repository.get(task.id)
    assert current is not None and current.etag != original.etag
    with pytest.raises(TaskPreconditionError):
        await repository.delete(task.id, expected_etag=original.etag)
    assert await repository.delete(task.id, expected_etag=current.etag)


@pytest.mark.anyio
async def test_cosmos_etag_is_native_and_conditional_writes_use_sdk_preconditions():
    container = create_autospec(ContainerProxy, instance=True)
    task = Task.create("Task")
    container.read_item.return_value = {
        "id": str(task.id),
        "title": task.title,
        "description": "",
        "status": "todo",
        "_etag": '"native-version"',
    }
    repository = CosmosdbTaskRepository(container)
    current = await repository.get(task.id)
    assert current is not None and current.etag == '"native-version"'
    assert await repository.update(current, expected_etag=current.etag)
    assert container.replace_item.await_args.kwargs["etag"] == current.etag
    assert container.replace_item.await_args.kwargs["match_condition"] is MatchConditions.IfNotModified
    assert await repository.delete(task.id, expected_etag=current.etag)
    assert container.delete_item.await_args.kwargs["match_condition"] is MatchConditions.IfNotModified
    for method, operation in (("replace_item", repository.update), ("delete_item", repository.delete)):
        setattr(container, method, AsyncMock(side_effect=CosmosHttpResponseError(status_code=412)))
        with pytest.raises(TaskPreconditionError):
            await operation(current if method == "replace_item" else task.id, expected_etag=current.etag)


@pytest.mark.anyio
async def test_repository_page_bounds_and_ping_do_not_enumerate():
    repository = InMemoryTaskRepository()
    for index in range(6):
        await repository.add(Task.create(f"Task {index}"))
    tasks, total = await repository.page(offset=2, limit=2)
    assert [task.title for task in tasks] == ["Task 2", "Task 3"]
    assert total == 6
    assert await repository.page(offset=9, limit=2) == ((), 6)
    await repository.ping()


@pytest.mark.parametrize("length", [0, 1, 199, 200, 201])
@pytest.mark.parametrize("alphabet", ["x", "é", "🚀"])
def test_deterministic_title_boundary_properties(length, alphabet):
    value = f" \t{alphabet * length}\n "
    if 1 <= length <= 200:
        task = Task.create(value)
        assert task.title == alphabet * length
        assert task.status is TaskStatus.TODO
        assert task.update(title=task.title, description="", status=TaskStatus.DONE).id == task.id
    else:
        with pytest.raises(InvalidTaskError):
            Task.create(value)


@pytest.mark.parametrize("length", [0, 1, 1999, 2000, 2001])
def test_deterministic_description_boundary_properties(length):
    description = f" \t{'d' * length}\n "
    if length <= 2000:
        assert Task.create("Valid", description).description == "d" * length
    else:
        with pytest.raises(InvalidTaskError):
            Task.create("Valid", description)
