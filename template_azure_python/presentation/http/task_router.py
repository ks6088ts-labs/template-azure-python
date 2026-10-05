import logging
from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from template_azure_python.application import (
    CreateTask,
    CreateTaskCommand,
    DeleteTask,
    GetTask,
    ListTasks,
    TaskAlreadyExistsError,
    TaskNotFoundError,
    TaskRepositoryError,
    UpdateTask,
    UpdateTaskCommand,
)
from template_azure_python.domain import InvalidTaskError, TaskId
from template_azure_python.presentation.http.task_schemas import (
    CreateTaskRequest,
    ErrorResponse,
    TaskResponse,
    UpdateTaskRequest,
)


def register_task_error_handlers(application: FastAPI) -> None:
    @application.exception_handler(RequestValidationError)
    async def request_validation_handler(_request: Request, error: RequestValidationError) -> JSONResponse:
        detail = "; ".join(str(item["msg"]) for item in error.errors())
        return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content={"detail": detail})

    @application.exception_handler(InvalidTaskError)
    async def invalid_task_handler(_request: Request, error: InvalidTaskError) -> JSONResponse:
        return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content={"detail": str(error)})

    @application.exception_handler(TaskNotFoundError)
    async def task_not_found_handler(_request: Request, error: TaskNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(error)})

    @application.exception_handler(TaskAlreadyExistsError)
    async def task_conflict_handler(_request: Request, error: TaskAlreadyExistsError) -> JSONResponse:
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(error)})

    @application.exception_handler(TaskRepositoryError)
    async def task_storage_handler(request: Request, error: TaskRepositoryError) -> JSONResponse:
        logging.getLogger(__name__).error("Task storage unavailable for %s %s", request.method, request.url.path)
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": str(error)})


def create_task_router(
    *,
    create_task: Callable[[], CreateTask],
    get_task: Callable[[], GetTask],
    list_tasks: Callable[[], ListTasks],
    update_task: Callable[[], UpdateTask],
    delete_task: Callable[[], DeleteTask],
) -> APIRouter:
    router = APIRouter(prefix="/tasks", tags=["tasks"], responses={503: {"model": ErrorResponse}})

    @router.post(
        "",
        status_code=status.HTTP_201_CREATED,
        response_model=TaskResponse,
        responses={409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
        operation_id="create_task",
    )
    async def create(request: CreateTaskRequest, use_case: Annotated[CreateTask, Depends(create_task)]) -> TaskResponse:
        task = await use_case(CreateTaskCommand(title=request.title, description=request.description))
        return TaskResponse.from_domain(task)

    @router.get("", response_model=list[TaskResponse], operation_id="list_tasks")
    async def list_all(use_case: Annotated[ListTasks, Depends(list_tasks)]) -> list[TaskResponse]:
        return [TaskResponse.from_domain(task) for task in await use_case()]

    @router.get(
        "/{task_id}",
        response_model=TaskResponse,
        responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
        operation_id="get_task",
    )
    async def get(task_id: UUID, use_case: Annotated[GetTask, Depends(get_task)]) -> TaskResponse:
        task = await use_case(TaskId(task_id))
        return TaskResponse.from_domain(task)

    @router.put(
        "/{task_id}",
        response_model=TaskResponse,
        responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
        operation_id="update_task",
    )
    async def update(
        task_id: UUID, request: UpdateTaskRequest, use_case: Annotated[UpdateTask, Depends(update_task)]
    ) -> TaskResponse:
        task = await use_case(
            UpdateTaskCommand(
                task_id=TaskId(task_id),
                title=request.title,
                description=request.description,
                status=request.status,
            )
        )
        return TaskResponse.from_domain(task)

    @router.delete(
        "/{task_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        response_class=Response,
        responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
        operation_id="delete_task",
    )
    async def delete(task_id: UUID, use_case: Annotated[DeleteTask, Depends(delete_task)]) -> Response:
        await use_case(TaskId(task_id))
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
