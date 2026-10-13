import logging
from collections.abc import Callable
from http import HTTPStatus
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from template_azure_python.application import (
    CreateTask,
    CreateTaskCommand,
    DeleteTask,
    GetTask,
    ListTasks,
    TaskAlreadyExistsError,
    TaskNotFoundError,
    TaskPreconditionError,
    TaskReadOnlyError,
    TaskRepositoryError,
    UpdateTask,
    UpdateTaskCommand,
)
from template_azure_python.domain import InvalidTaskError, TaskId
from template_azure_python.presentation.http.security import SECURITY_HEADERS
from template_azure_python.presentation.http.task_schemas import (
    CreateTaskRequest,
    ErrorResponse,
    TaskResponse,
    UpdateTaskRequest,
)


def problem_response(request: Request, code: int, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=code,
        media_type="application/problem+json",
        headers={
            **SECURITY_HEADERS,
            **({"strict-transport-security": "max-age=31536000"} if request.url.scheme == "https" else {}),
        },
        content={
            "type": "about:blank",
            "title": HTTPStatus(code).phrase,
            "status": code,
            "detail": detail,
            "instance": request.url.path,
        },
    )


def register_task_error_handlers(application: FastAPI) -> None:
    @application.exception_handler(RequestValidationError)
    async def request_validation_handler(request: Request, error: RequestValidationError) -> JSONResponse:
        detail = "; ".join(str(item["msg"]) for item in error.errors())
        return problem_response(request, 422, detail)

    @application.exception_handler(InvalidTaskError)
    async def invalid_task_handler(request: Request, error: InvalidTaskError) -> JSONResponse:
        return problem_response(request, 422, str(error))

    @application.exception_handler(TaskNotFoundError)
    async def task_not_found_handler(request: Request, error: TaskNotFoundError) -> JSONResponse:
        return problem_response(request, 404, str(error))

    @application.exception_handler(TaskAlreadyExistsError)
    async def task_conflict_handler(request: Request, error: TaskAlreadyExistsError) -> JSONResponse:
        return problem_response(request, 409, str(error))

    @application.exception_handler(TaskPreconditionError)
    async def precondition_handler(request: Request, error: TaskPreconditionError) -> JSONResponse:
        return problem_response(request, 412, str(error))

    @application.exception_handler(TaskReadOnlyError)
    async def read_only_handler(request: Request, error: TaskReadOnlyError) -> JSONResponse:
        response = problem_response(request, 405, str(error))
        response.headers["Allow"] = "GET"
        return response

    @application.exception_handler(TaskRepositoryError)
    async def task_storage_handler(request: Request, error: TaskRepositoryError) -> JSONResponse:
        logging.getLogger(__name__).error("Task storage unavailable for %s %s", request.method, request.url.path)
        return problem_response(request, 503, "Task storage is unavailable")

    @application.exception_handler(HTTPException)
    async def http_error_handler(request: Request, error: HTTPException) -> JSONResponse:
        response = problem_response(request, error.status_code, str(error.detail))
        if error.headers:
            response.headers.update(error.headers)
        return response

    @application.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, error: Exception) -> JSONResponse:
        logging.getLogger(__name__).error("Unexpected request failure (%s)", type(error).__name__)
        return problem_response(request, 500, "An unexpected error occurred")


def _expected_etag(value: str | None) -> str | None:
    if value is not None and (
        len(value) < 3
        or len(value) > 256
        or not value.startswith('"')
        or not value.endswith('"')
        or any(ord(character) < 33 or ord(character) > 126 or character == '"' for character in value[1:-1])
        or "," in value
    ):
        raise HTTPException(status_code=400, detail="If-Match must contain one strong ETag")
    return value


def _set_etag(response: Response, etag: str | None) -> None:
    if etag:
        response.headers["ETag"] = etag


def create_task_router(
    *,
    create_task: Callable[[], CreateTask],
    get_task: Callable[[], GetTask],
    list_tasks: Callable[[], ListTasks],
    update_task: Callable[[], UpdateTask],
    delete_task: Callable[[], DeleteTask],
) -> APIRouter:
    errors: dict[int | str, dict[str, Any]] = {
        code: {
            "content": {"application/problem+json": {"schema": ErrorResponse.model_json_schema()}},
        }
        for code in (400, 401, 403, 404, 405, 409, 412, 422, 503)
    }
    router = APIRouter(prefix="/tasks", tags=["tasks"], responses=errors)

    @router.post(
        "",
        status_code=status.HTTP_201_CREATED,
        response_model=TaskResponse,
        operation_id="create_task",
    )
    async def create(
        request: CreateTaskRequest, response: Response, use_case: Annotated[CreateTask, Depends(create_task)]
    ) -> TaskResponse:
        task = await use_case(CreateTaskCommand(title=request.title, description=request.description))
        _set_etag(response, task.etag)
        return TaskResponse.from_domain(task)

    @router.get("", response_model=list[TaskResponse], operation_id="list_tasks")
    async def list_all(
        response: Response,
        use_case: Annotated[ListTasks, Depends(list_tasks)],
        offset: Annotated[int, Query(ge=0, le=100000)] = 0,
        limit: Annotated[int, Query(ge=1, le=100)] = 100,
    ) -> list[TaskResponse]:
        tasks, total = await use_case.page(offset=offset, limit=limit)
        response.headers["X-Total-Count"] = str(total)
        return [TaskResponse.from_domain(task) for task in tasks]

    @router.get(
        "/{task_id}",
        response_model=TaskResponse,
        operation_id="get_task",
    )
    async def get(task_id: UUID, response: Response, use_case: Annotated[GetTask, Depends(get_task)]) -> TaskResponse:
        task = await use_case(TaskId(task_id))
        _set_etag(response, task.etag)
        return TaskResponse.from_domain(task)

    @router.put(
        "/{task_id}",
        response_model=TaskResponse,
        operation_id="update_task",
    )
    async def update(
        task_id: UUID,
        request: UpdateTaskRequest,
        response: Response,
        use_case: Annotated[UpdateTask, Depends(update_task)],
        if_match: Annotated[str | None, Header()] = None,
    ) -> TaskResponse:
        task = await use_case(
            UpdateTaskCommand(
                task_id=TaskId(task_id),
                title=request.title,
                description=request.description,
                status=request.status,
                expected_etag=_expected_etag(if_match),
            )
        )
        _set_etag(response, task.etag)
        return TaskResponse.from_domain(task)

    @router.delete(
        "/{task_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        response_class=Response,
        operation_id="delete_task",
    )
    async def delete(
        task_id: UUID,
        use_case: Annotated[DeleteTask, Depends(delete_task)],
        if_match: Annotated[str | None, Header()] = None,
    ) -> Response:
        await use_case(TaskId(task_id), expected_etag=_expected_etag(if_match))
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
