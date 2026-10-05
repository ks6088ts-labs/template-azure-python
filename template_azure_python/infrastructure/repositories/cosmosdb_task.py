import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import AsyncExitStack, asynccontextmanager
from uuid import UUID

from azure.core.exceptions import AzureError
from azure.cosmos.aio import ContainerProxy, CosmosClient
from azure.cosmos.exceptions import CosmosResourceExistsError, CosmosResourceNotFoundError
from azure.identity.aio import DefaultAzureCredential

from template_azure_python.application import TaskAlreadyExistsError, TaskRepositoryError
from template_azure_python.domain import Task, TaskId, TaskStatus
from template_azure_python.internals.azure._common import (
    InputError,
    required_value,
    validate_cosmos_resource_name,
    validate_endpoint,
)
from template_azure_python.settings.azure import CosmosDBSettings

PARTITION_KEY_PATH = "/id"
TASK_QUERY = "SELECT c.id, c.title, c.description, c.status FROM c"
logger = logging.getLogger(__name__)


class TaskStorageConfigurationError(ValueError):
    pass


def _failure(operation: str, error: Exception) -> TaskRepositoryError:
    logger.error(
        "Task storage %s failed (%s, status=%s)",
        operation,
        type(error).__name__,
        getattr(error, "status_code", None),
    )
    return TaskRepositoryError()


def _document(task: Task) -> dict[str, object]:
    return {"id": str(task.id), "title": task.title, "description": task.description, "status": task.status.value}


def _task(document: Mapping[str, object]) -> Task:
    try:
        task_id, title, description, status = (document[key] for key in ("id", "title", "description", "status"))
        if (
            not isinstance(task_id, str)
            or not isinstance(title, str)
            or not isinstance(description, str)
            or not isinstance(status, str)
        ):
            raise ValueError("Task document fields must be strings")
        return Task(id=TaskId(UUID(task_id)), title=title, description=description, status=TaskStatus(status))
    except (KeyError, ValueError, TypeError) as error:
        raise _failure("decode", error) from None


class CosmosdbTaskRepository:
    def __init__(self, container: ContainerProxy) -> None:
        self._container = container

    async def _confirm_task_absence(self) -> None:
        # A deleted container must not masquerade as a missing Task.
        try:
            await self._container.read()
        except AzureError as error:
            raise _failure("check container", error) from None

    async def add(self, task: Task) -> None:
        try:
            await self._container.create_item(body=_document(task))
        except CosmosResourceExistsError:
            raise TaskAlreadyExistsError(task.id) from None
        except AzureError as error:
            raise _failure("add", error) from None

    async def get(self, task_id: TaskId) -> Task | None:
        try:
            document = await self._container.read_item(item=str(task_id), partition_key=str(task_id))
        except CosmosResourceNotFoundError:
            await self._confirm_task_absence()
            return None
        except AzureError as error:
            raise _failure("get", error) from None
        return _task(document)

    async def list(self) -> tuple[Task, ...]:
        try:
            return tuple([_task(document) async for document in self._container.query_items(query=TASK_QUERY)])
        except AzureError as error:
            raise _failure("list", error) from None

    async def update(self, task: Task) -> bool:
        try:
            await self._container.replace_item(item=str(task.id), body=_document(task), partition_key=str(task.id))
        except CosmosResourceNotFoundError:
            await self._confirm_task_absence()
            return False
        except AzureError as error:
            raise _failure("update", error) from None
        return True

    async def delete(self, task_id: TaskId) -> bool:
        try:
            await self._container.delete_item(item=str(task_id), partition_key=str(task_id))
        except CosmosResourceNotFoundError:
            await self._confirm_task_absence()
            return False
        except AzureError as error:
            raise _failure("delete", error) from None
        return True


def validate_cosmos_task_settings(settings: CosmosDBSettings) -> tuple[str, str, str]:
    try:
        endpoint = validate_endpoint(required_value(None, settings.endpoint, "AZURE_COSMOS_DB_ENDPOINT"))
        database_id = validate_cosmos_resource_name(settings.database, "AZURE_COSMOS_DB_DATABASE")
        container_id = validate_cosmos_resource_name(settings.task_container, "AZURE_COSMOS_DB_TASK_CONTAINER")
    except InputError as error:
        raise TaskStorageConfigurationError(str(error)) from None
    return endpoint, database_id, container_id


@asynccontextmanager
async def open_cosmos_task_repository(settings: CosmosDBSettings) -> AsyncIterator[CosmosdbTaskRepository]:
    endpoint, database_id, container_id = validate_cosmos_task_settings(settings)
    try:
        async with AsyncExitStack() as stack:
            credential = DefaultAzureCredential()
            stack.push_async_callback(credential.close)
            client = CosmosClient(url=endpoint, credential=credential)
            stack.push_async_callback(client.close)
            # Register cleanup before SDK initialization, which can itself fail.
            await client.__aenter__()
            database = client.get_database_client(database_id)
            await database.read()
            container = database.get_container_client(container_id)
            properties = await container.read()
            partition = properties.get("partitionKey")
            if not isinstance(partition, dict) or partition.get("paths") != [PARTITION_KEY_PATH]:
                raise TaskStorageConfigurationError("Task container must use partition key /id")
            yield CosmosdbTaskRepository(container)
    except AzureError as error:
        raise _failure("lifespan", error) from None
