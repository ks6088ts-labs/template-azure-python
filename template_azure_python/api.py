from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from template_azure_python.application import CreateTask, DeleteTask, GetTask, ListTasks, UpdateTask
from template_azure_python.application.ports import TaskRepository
from template_azure_python.infrastructure import InMemoryTaskRepository, open_cosmos_task_repository
from template_azure_python.presentation.http import create_task_router, register_task_error_handlers
from template_azure_python.settings import TaskRepositoryBackend, get_azure_settings, get_project_settings
from template_azure_python.telemetry import configure_api_telemetry


def create_app(
    *,
    repository: TaskRepository | None = None,
    repository_backend: TaskRepositoryBackend | None = None,
) -> FastAPI:
    if repository is not None and repository_backend is not None:
        raise ValueError("Specify either repository or repository_backend, not both")
    configure_api_telemetry()
    backend = (
        TaskRepositoryBackend.IN_MEMORY
        if repository is not None
        else TaskRepositoryBackend(repository_backend or get_project_settings().task_repository)
    )
    task_repository = repository
    if task_repository is None and backend is TaskRepositoryBackend.IN_MEMORY:
        task_repository = InMemoryTaskRepository()

    @asynccontextmanager
    async def lifespan(_application: FastAPI) -> AsyncIterator[None]:
        nonlocal task_repository
        if backend is TaskRepositoryBackend.COSMOSDB:
            async with open_cosmos_task_repository(get_azure_settings().cosmos_db) as cosmos_repository:
                task_repository = cosmos_repository
                try:
                    yield
                finally:
                    task_repository = None
        else:
            yield

    def repository_dependency() -> TaskRepository:
        if task_repository is None:
            raise RuntimeError("Task repository requires application lifespan startup")
        return task_repository

    application = FastAPI(lifespan=lifespan)
    application.include_router(
        create_task_router(
            create_task=lambda: CreateTask(repository_dependency()),
            get_task=lambda: GetTask(repository_dependency()),
            list_tasks=lambda: ListTasks(repository_dependency()),
            update_task=lambda: UpdateTask(repository_dependency()),
            delete_task=lambda: DeleteTask(repository_dependency()),
        )
    )
    register_task_error_handlers(application)
    return application


app = create_app()
