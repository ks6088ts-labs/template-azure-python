from importlib import import_module
from typing import TYPE_CHECKING, Any

from template_azure_python.infrastructure.repositories._errors import TaskStorageConfigurationError
from template_azure_python.infrastructure.repositories.in_memory_task import InMemoryTaskRepository

if TYPE_CHECKING:
    from template_azure_python.infrastructure.repositories.cosmosdb_task import (
        CosmosdbTaskRepository,
        open_cosmos_task_repository,
        validate_cosmos_task_settings,
    )
    from template_azure_python.infrastructure.repositories.duckdb_task import (
        DuckdbTaskRepository,
        open_duckdb_task_repository,
        validate_duckdb_task_path,
    )

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


def __getattr__(name: str) -> Any:
    modules = {
        "CosmosdbTaskRepository": "cosmosdb_task",
        "open_cosmos_task_repository": "cosmosdb_task",
        "validate_cosmos_task_settings": "cosmosdb_task",
        "DuckdbTaskRepository": "duckdb_task",
        "open_duckdb_task_repository": "duckdb_task",
        "validate_duckdb_task_path": "duckdb_task",
    }
    if name not in modules:
        raise AttributeError(name)
    return getattr(import_module(f"{__name__}.{modules[name]}"), name)
