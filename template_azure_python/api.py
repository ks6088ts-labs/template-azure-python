import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from template_azure_python.application import CreateTask, DeleteTask, GetTask, ListTasks, UpdateTask
from template_azure_python.application.ports import TaskRepository
from template_azure_python.infrastructure import (
    InMemoryTaskRepository,
    open_cosmos_task_repository,
    open_duckdb_task_repository,
)
from template_azure_python.loggers import configure_logging
from template_azure_python.presentation.http import create_task_router, register_task_error_handlers
from template_azure_python.presentation.http.security import SecurityHeadersMiddleware, authentication_dependency
from template_azure_python.presentation.http.task_router import problem_response
from template_azure_python.settings import (
    ProjectSettings,
    TaskRepositoryBackend,
    get_azure_settings,
    get_project_settings,
)
from template_azure_python.telemetry import configure_api_telemetry


def create_app(
    *,
    repository: TaskRepository | None = None,
    repository_backend: TaskRepositoryBackend | None = None,
    settings: ProjectSettings | None = None,
) -> FastAPI:
    if repository is not None and repository_backend is not None:
        raise ValueError("Specify either repository or repository_backend, not both")
    settings = settings or get_project_settings()
    backend = (
        TaskRepositoryBackend.IN_MEMORY
        if repository is not None
        else TaskRepositoryBackend(repository_backend or settings.task_repository)
    )
    task_repository = repository
    if task_repository is None and backend is TaskRepositoryBackend.IN_MEMORY:
        task_repository = InMemoryTaskRepository()

    @asynccontextmanager
    async def lifespan(_application: FastAPI) -> AsyncGenerator[None]:
        nonlocal task_repository
        configure_logging(settings.project_log_level)
        configure_api_telemetry(project=settings)
        async with AsyncExitStack() as stack:
            if backend is TaskRepositoryBackend.COSMOSDB:
                task_repository = await stack.enter_async_context(
                    open_cosmos_task_repository(get_azure_settings().cosmos_db)
                )
            elif backend is TaskRepositoryBackend.DUCKDB:
                task_repository = await stack.enter_async_context(
                    open_duckdb_task_repository(settings.duckdb_path, read_only=True)
                )
            try:
                yield
            finally:
                if backend is not TaskRepositoryBackend.IN_MEMORY:
                    task_repository = None

    def repository_dependency() -> TaskRepository:
        if task_repository is None:
            raise RuntimeError("Task repository requires application lifespan startup")
        return task_repository

    application = FastAPI(
        lifespan=lifespan,
        version=settings.app_version,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        telemetry={
            "tracing": settings.telemetry_enabled,
            "metrics": settings.telemetry_enabled,
            "logs": False,
            "operation_spans": False,
            "auto_configure": False,
            "exclude": lambda scope: scope.get("path") in {"/healthz", "/readyz", "/docs", "/redoc", "/openapi.json"},
        },
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "If-Match"],
        expose_headers=["ETag", "X-Total-Count"],
    )
    application.add_middleware(SecurityHeadersMiddleware)

    @application.get("/healthz", include_in_schema=False)
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": settings.app_version}

    @application.get("/readyz", include_in_schema=False, response_model=None)
    async def ready(request: Request) -> Response | dict[str, str]:
        try:
            async with asyncio.timeout(2):
                await repository_dependency().ping()
        except Exception as error:
            logging.getLogger(__name__).warning("Readiness check failed (%s)", type(error).__name__)
            return problem_response(request, 503, "Task storage is unavailable")
        return {"status": "ready", "version": settings.app_version}

    application.include_router(
        create_task_router(
            create_task=lambda: CreateTask(repository_dependency()),
            get_task=lambda: GetTask(repository_dependency()),
            list_tasks=lambda: ListTasks(repository_dependency()),
            update_task=lambda: UpdateTask(repository_dependency()),
            delete_task=lambda: DeleteTask(repository_dependency()),
        ),
        dependencies=[Depends(authentication_dependency(settings.auth_mode, settings.auth_required_role))],
    )
    register_task_error_handlers(application)
    return application
