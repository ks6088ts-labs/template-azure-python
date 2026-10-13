from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from template_azure_python.application.ports import TaskRepository
from template_azure_python.infrastructure.repositories._errors import TaskStorageConfigurationError
from template_azure_python.infrastructure.repositories.in_memory_task import InMemoryTaskRepository
from template_azure_python.settings.azure import CosmosDBSettings

if TYPE_CHECKING:
    from template_azure_python.infrastructure.repositories.cosmosdb_task import CosmosdbTaskRepository
    from template_azure_python.infrastructure.repositories.duckdb_task import DuckdbTaskRepository

__all__ = [
    "CosmosdbTaskRepository",
    "DuckdbTaskRepository",
    "InMemoryTaskRepository",
    "TaskStorageConfigurationError",
    "open_cosmos_task_repository",
    "open_duckdb_task_repository",
    "validate_cosmos_task_settings",
    "validate_duckdb_task_path",
]


@asynccontextmanager
async def open_cosmos_task_repository(settings: CosmosDBSettings) -> AsyncGenerator[TaskRepository]:
    try:
        from template_azure_python.infrastructure.repositories.cosmosdb_task import (
            open_cosmos_task_repository as open_it,
        )
    except ImportError:
        raise TaskStorageConfigurationError("Install template-azure-python[cosmos] for Cosmos storage") from None
    async with open_it(settings) as repository:
        yield repository


@asynccontextmanager
async def open_duckdb_task_repository(path: Path | None, *, read_only: bool = False) -> AsyncGenerator[TaskRepository]:
    try:
        from template_azure_python.infrastructure.repositories.duckdb_task import open_duckdb_task_repository as open_it
    except ImportError:
        raise TaskStorageConfigurationError("Install template-azure-python[duckdb] for DuckDB storage") from None
    async with open_it(path, read_only=read_only) as repository:
        yield repository


def validate_cosmos_task_settings(settings: CosmosDBSettings) -> tuple[str, str, str]:
    try:
        from template_azure_python.infrastructure.repositories.cosmosdb_task import (
            validate_cosmos_task_settings as validate,
        )
    except ImportError:
        raise TaskStorageConfigurationError("Install template-azure-python[cosmos] for Cosmos storage") from None
    return validate(settings)


def validate_duckdb_task_path(path: Path | None) -> Path:
    try:
        from template_azure_python.infrastructure.repositories.duckdb_task import validate_duckdb_task_path as validate
    except ImportError:
        raise TaskStorageConfigurationError("Install template-azure-python[duckdb] for DuckDB storage") from None
    return validate(path)


def __getattr__(name: str) -> Any:
    from template_azure_python.infrastructure import repositories

    if name not in {"CosmosdbTaskRepository", "DuckdbTaskRepository"}:
        raise AttributeError(name)
    return getattr(repositories, name)
