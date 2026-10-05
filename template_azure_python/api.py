from fastapi import FastAPI

from template_azure_python.application import CreateTask, DeleteTask, GetTask, ListTasks, UpdateTask
from template_azure_python.infrastructure import InMemoryTaskRepository
from template_azure_python.presentation.http import create_task_router, register_task_error_handlers
from template_azure_python.routers import root
from template_azure_python.telemetry import configure_api_telemetry


def create_app() -> FastAPI:
    configure_api_telemetry()
    application = FastAPI()
    task_repository = InMemoryTaskRepository()

    application.include_router(root.router)
    application.include_router(
        create_task_router(
            create_task=CreateTask(task_repository),
            get_task=GetTask(task_repository),
            list_tasks=ListTasks(task_repository),
            update_task=UpdateTask(task_repository),
            delete_task=DeleteTask(task_repository),
        )
    )
    register_task_error_handlers(application)
    return application


app = create_app()
