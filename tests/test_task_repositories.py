import asyncio
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, create_autospec, patch
from uuid import UUID

import azure.functions as func
import pytest
from azure.core.exceptions import AzureError
from azure.cosmos.aio import ContainerProxy, CosmosClient
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceExistsError, CosmosResourceNotFoundError
from azure.identity.aio import DefaultAzureCredential
from fastapi.testclient import TestClient

from template_azure_python.api import create_app
from template_azure_python.application import TaskAlreadyExistsError, TaskRepositoryError
from template_azure_python.domain import Task, TaskId, TaskStatus
from template_azure_python.infrastructure import (
    CosmosdbTaskRepository,
    InMemoryTaskRepository,
    TaskStorageConfigurationError,
    open_cosmos_task_repository,
)
from template_azure_python.infrastructure.repositories.cosmosdb_task import TASK_QUERY
from template_azure_python.settings import TaskRepositoryBackend
from template_azure_python.settings.azure import CosmosDBSettings

TASK = Task(TaskId(UUID(int=1)), "First", "Details", TaskStatus.TODO)
MISSING_ID = TaskId(UUID(int=2))
ENDPOINT = "https://example.documents.azure.com/"


@pytest.fixture
def container():
    documents: dict[str, dict[str, object]] = {}
    proxy = create_autospec(ContainerProxy, instance=True)
    proxy.read.return_value = {"partitionKey": {"paths": ["/id"]}}

    async def create(*, body):
        if body["id"] in documents:
            raise CosmosResourceExistsError(status_code=409)
        documents[body["id"]] = body.copy()
        return body

    async def read(*, item, partition_key):
        assert item == partition_key
        if item not in documents:
            raise CosmosResourceNotFoundError(status_code=404)
        return documents[item].copy()

    async def replace(*, item, body, partition_key):
        await read(item=item, partition_key=partition_key)
        assert body["id"] == item
        documents[item] = body.copy()
        return body

    async def delete(*, item, partition_key):
        await read(item=item, partition_key=partition_key)
        del documents[item]

    async def query() -> AsyncIterator[dict[str, object]]:
        for document in documents.values():
            yield document.copy()

    proxy.create_item.side_effect = create
    proxy.read_item.side_effect = read
    proxy.replace_item.side_effect = replace
    proxy.delete_item.side_effect = delete
    proxy.query_items.side_effect = lambda **kwargs: query()
    return proxy


@pytest.mark.parametrize("backend", ["in-memory", "cosmosdb"])
def test_repository_contract(backend, container):
    repository = InMemoryTaskRepository() if backend == "in-memory" else CosmosdbTaskRepository(container)

    async def scenario():
        assert await repository.list() == ()
        assert await repository.get(MISSING_ID) is None
        assert not await repository.update(TASK)
        assert not await repository.delete(MISSING_ID)
        await repository.add(TASK)
        with pytest.raises(TaskAlreadyExistsError):
            await repository.add(TASK)
        assert await repository.get(TASK.id) == TASK
        second = Task.create("Second")
        await repository.add(second)
        assert {task.id: task for task in await repository.list()} == {TASK.id: TASK, second.id: second}
        replacement = TASK.update(title="Updated", description="", status=TaskStatus.DONE)
        assert await repository.update(replacement)
        assert await repository.get(TASK.id) == replacement
        assert await repository.delete(TASK.id)
        assert not await repository.delete(TASK.id)
        assert not await repository.update(replacement)
        assert await repository.list() == (second,)

    asyncio.run(scenario())
    if backend == "cosmosdb":
        container.create_item.assert_any_await(
            body={"id": str(TASK.id), "title": "First", "description": "Details", "status": "todo"}
        )
        container.query_items.assert_called_with(query=TASK_QUERY)
        container.replace_item.assert_any_await(
            item=str(TASK.id),
            partition_key=str(TASK.id),
            body={"id": str(TASK.id), "title": "Updated", "description": "", "status": "done"},
        )


@pytest.mark.parametrize(
    ("operation", "method"),
    [
        ("add", "create_item"),
        ("get", "read_item"),
        ("list", "query_items"),
        ("update", "replace_item"),
        ("delete", "delete_item"),
    ],
)
@pytest.mark.parametrize("status", [400, 401, 403, 429, 500, 503])
def test_sdk_failures_are_not_disguised(operation, method, status, container, caplog):
    getattr(container, method).side_effect = CosmosHttpResponseError(status_code=status, message="secret-detail")
    repository = CosmosdbTaskRepository(container)

    async def scenario():
        with pytest.raises(TaskRepositoryError) as error:
            if operation == "list":
                await repository.list()
            else:
                argument = TASK if operation in {"add", "update"} else TASK.id
                await getattr(repository, operation)(argument)
        assert "secret-detail" not in str(error.value)
        assert error.value.__cause__ is None

    asyncio.run(scenario())
    assert "secret-detail" not in caplog.text
    assert f"status={status}" in caplog.text


@pytest.mark.parametrize("operation", ["get", "update", "delete"])
def test_missing_container_is_not_missing_task(operation, container):
    container.read.side_effect = CosmosResourceNotFoundError(status_code=404)
    repository = CosmosdbTaskRepository(container)

    async def scenario():
        with pytest.raises(TaskRepositoryError):
            await getattr(repository, operation)(TASK if operation == "update" else TASK.id)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "document",
    [
        {},
        {"id": "not-uuid", "title": "Task", "description": "", "status": "todo"},
        {"id": str(TASK.id), "title": " ", "description": "", "status": "todo"},
        {"id": str(TASK.id), "title": "Task", "description": "", "status": "invalid"},
        {"id": str(TASK.id), "title": 12, "description": "", "status": "todo"},
    ],
)
def test_invalid_documents_are_storage_failures(document, container):
    container.read_item.side_effect = None
    container.read_item.return_value = document
    with pytest.raises(TaskRepositoryError):
        asyncio.run(CosmosdbTaskRepository(container).get(TASK.id))


def test_list_consumes_all_pages_and_does_not_return_partial_results(container):
    async def pages(fail=False):
        yield {"id": str(TASK.id), "title": "One", "description": "", "status": "todo"}
        await asyncio.sleep(0)
        if fail:
            raise AzureError("not a complete result")
        yield {"id": str(MISSING_ID), "title": "Two", "description": "", "status": "done"}

    container.query_items.side_effect = lambda **kwargs: pages()
    repository = CosmosdbTaskRepository(container)
    assert len(asyncio.run(repository.list())) == 2
    container.query_items.side_effect = lambda **kwargs: pages(fail=True)
    with pytest.raises(TaskRepositoryError):
        asyncio.run(repository.list())


@pytest.fixture
def cosmos_clients(container):
    credential = create_autospec(DefaultAzureCredential, instance=True)
    client = create_autospec(CosmosClient, instance=True)
    client.__aenter__.return_value = client
    database = MagicMock()
    database.read = AsyncMock(return_value={})
    database.get_container_client.return_value = container
    client.get_database_client.return_value = database
    with (
        patch(
            "template_azure_python.infrastructure.repositories.cosmosdb_task.DefaultAzureCredential",
            return_value=credential,
        ) as credential_type,
        patch(
            "template_azure_python.infrastructure.repositories.cosmosdb_task.CosmosClient", return_value=client
        ) as client_type,
    ):
        yield credential, client, database, credential_type, client_type


@pytest.mark.parametrize(
    "failure", [None, "enter", "enter_cancel", "database", "container", "partition", "body", "cancel", "close"]
)
def test_lifespan_cleans_up_success_failure_and_cancellation(failure, cosmos_clients, container):
    credential, client, database, _, _ = cosmos_clients
    if failure in {"enter", "database", "container", "close"}:
        method = {
            "enter": client.__aenter__,
            "database": database.read,
            "container": container.read,
            "close": client.close,
        }[failure]
        method.side_effect = AzureError("sensitive SDK detail")
    elif failure == "partition":
        container.read.return_value = {"partitionKey": {"paths": ["/category"]}}
    elif failure == "enter_cancel":
        client.__aenter__.side_effect = asyncio.CancelledError()

    async def scenario():
        async with open_cosmos_task_repository(CosmosDBSettings(_env_file=None, endpoint=ENDPOINT)) as repository:
            assert isinstance(repository, CosmosdbTaskRepository)
            if failure == "body":
                raise RuntimeError("body")
            if failure == "cancel":
                raise asyncio.CancelledError()

    expected = {
        "partition": TaskStorageConfigurationError,
        "body": RuntimeError,
        "cancel": asyncio.CancelledError,
        "enter_cancel": asyncio.CancelledError,
    }.get(failure, TaskRepositoryError)
    if failure is None:
        asyncio.run(scenario())
    else:
        with pytest.raises(expected):
            asyncio.run(scenario())
    client.close.assert_awaited_once()
    credential.close.assert_awaited_once()


def test_constructor_failure_still_closes_credential(cosmos_clients):
    credential, _, _, _, client_type = cosmos_clients
    client_type.side_effect = AzureError("constructor failure")

    async def scenario():
        async with open_cosmos_task_repository(CosmosDBSettings(_env_file=None, endpoint=ENDPOINT)):
            pytest.fail("Must not start")

    with pytest.raises(TaskRepositoryError):
        asyncio.run(scenario())
    credential.close.assert_awaited_once()


@pytest.mark.parametrize(
    "options",
    [
        {},
        {"endpoint": "http://example.documents.azure.com/"},
        {"endpoint": ENDPOINT, "database": " "},
        {"endpoint": ENDPOINT, "task_container": "bad/path"},
    ],
)
def test_invalid_settings_fail_before_credentials(cosmos_clients, options):
    _, _, _, credential_type, client_type = cosmos_clients

    async def scenario():
        async with open_cosmos_task_repository(CosmosDBSettings(_env_file=None, **options)):
            pytest.fail("Must not start")

    with pytest.raises(TaskStorageConfigurationError):
        asyncio.run(scenario())
    credential_type.assert_not_called()
    client_type.assert_not_called()


def test_cosmos_api_uses_one_client_only_during_lifespan(cosmos_clients, container, monkeypatch):
    _, client, database, credential_type, client_type = cosmos_clients
    monkeypatch.setenv("AZURE_COSMOS_DB_ENDPOINT", ENDPOINT)
    monkeypatch.setenv("TASK_REPOSITORY", "cosmosdb")
    application = create_app()
    assert set(application.openapi()["paths"]) == {"/tasks", "/tasks/{task_id}"}
    credential_type.assert_not_called()
    client_type.assert_not_called()
    with TestClient(application) as http:
        created = http.post("/tasks", json={"title": "Stored"}).json()
        assert http.get(f"/tasks/{created['id']}").json() == created
        assert http.put(f"/tasks/{created['id']}", json={"title": "Done", "status": "done"}).status_code == 200
        assert http.delete(f"/tasks/{created['id']}").status_code == 204
        assert http.get("/tasks").json() == []
        client.close.assert_not_awaited()
    client_type.assert_called_once()
    database.get_container_client.assert_called_once_with("tasks")
    client.close.assert_awaited_once()
    with TestClient(create_app(repository_backend=TaskRepositoryBackend.IN_MEMORY)) as http:
        assert http.get("/tasks").json() == []
    client_type.assert_called_once()


def test_functions_asgi_startup_and_shutdown_manage_cosmos_lifespan(cosmos_clients, monkeypatch):
    _, client, _, _, client_type = cosmos_clients
    monkeypatch.setenv("AZURE_COSMOS_DB_ENDPOINT", ENDPOINT)

    async def scenario():
        middleware = func.AsgiMiddleware(create_app(repository_backend=TaskRepositoryBackend.COSMOSDB))
        assert await middleware.notify_startup()
        try:
            request = func.HttpRequest(method="GET", url="http://localhost/tasks", body=b"")
            response = await middleware.handle_async(request, None)
            assert response.status_code == 200
            assert response.get_body() == b"[]"
            client.close.assert_not_awaited()
        finally:
            await middleware.notify_shutdown()

    asyncio.run(scenario())
    client_type.assert_called_once()
    client.close.assert_awaited_once()
