import asyncio
import hashlib
import json
import logging
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

import duckdb

from template_azure_python.application import (
    TaskAlreadyExistsError,
    TaskReadOnlyError,
    TaskRepositoryError,
)
from template_azure_python.domain import Task, TaskId, TaskStatus
from template_azure_python.infrastructure.repositories._errors import TaskStorageConfigurationError

logger = logging.getLogger(__name__)
TASK_COLUMNS = "task_id, task_title, task_description, status, is_completed"
TASK_QUERY = f"SELECT {TASK_COLUMNS} FROM main.fct_tasks"


def _failure(operation: str, error: Exception) -> TaskRepositoryError:
    logger.error("Task storage %s failed (%s)", operation, type(error).__name__)
    return TaskRepositoryError()


async def _run_sync[T](operation: Callable[[], T]) -> T:
    worker = asyncio.create_task(asyncio.to_thread(operation))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        # Cancellation cannot stop a worker thread; retain ownership until it finishes.
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                continue
        worker.result()
        raise


def _task(row: tuple[object, ...]) -> Task:
    try:
        task_id, title, description, status, is_completed = row
        if (
            not isinstance(task_id, str)
            or not isinstance(title, str)
            or not isinstance(description, str)
            or not isinstance(status, str)
            or not isinstance(is_completed, bool)
            or is_completed != (status == TaskStatus.DONE.value)
        ):
            raise ValueError("Invalid Task row")
        parsed_id = UUID(task_id)
        if str(parsed_id) != task_id.lower():
            raise ValueError("Task UUID must use the dbt model's hyphenated format")
        etag = '"' + hashlib.sha256(json.dumps(row).encode()).hexdigest() + '"'
        return Task(TaskId(parsed_id), title, description, TaskStatus(status), etag=etag)
    except (ValueError, TypeError) as error:
        raise _failure("decode", error) from None


class DuckdbTaskRepository:
    def __init__(self, connection: duckdb.DuckDBPyConnection, *, read_only: bool = False) -> None:
        self._connection = connection
        self._read_only = read_only
        self._lock = asyncio.Lock()

    async def _execute(
        self, operation: str, query: str, parameters: tuple[object, ...] = ()
    ) -> list[tuple[object, ...]]:
        def execute() -> list[tuple[object, ...]]:
            return self._connection.execute(query, list(parameters)).fetchall()

        try:
            return await _run_sync(execute)
        except duckdb.Error as error:
            raise _failure(operation, error) from None

    async def add(self, task: Task) -> None:
        if self._read_only:
            raise TaskReadOnlyError()
        async with self._lock:
            if await self._execute("add", f"{TASK_QUERY} WHERE lower(task_id) = ?", (str(task.id),)):
                raise TaskAlreadyExistsError(task.id)
            await self._execute(
                "add",
                f"INSERT INTO main.fct_tasks ({TASK_COLUMNS}) VALUES (?, ?, ?, ?, ?)",
                (str(task.id), task.title, task.description, task.status.value, task.status is TaskStatus.DONE),
            )

    async def get(self, task_id: TaskId) -> Task | None:
        async with self._lock:
            rows = await self._execute("get", f"{TASK_QUERY} WHERE lower(task_id) = ?", (str(task_id),))
            return _task(rows[0]) if rows else None

    async def list(self) -> tuple[Task, ...]:
        async with self._lock:
            return tuple(_task(row) for row in await self._execute("list", TASK_QUERY))

    async def page(self, *, offset: int, limit: int) -> tuple[tuple[Task, ...], int]:
        async with self._lock:
            rows = await self._execute(
                "page", f"{TASK_QUERY} ORDER BY lower(task_id) LIMIT ? OFFSET ?", (limit, offset)
            )
            counts = await self._execute("page", "SELECT count(*) FROM main.fct_tasks")
            total = counts[0][0]
            if not isinstance(total, int):
                raise TaskRepositoryError()
            return tuple(_task(row) for row in rows), total

    async def ping(self) -> None:
        async with self._lock:
            await self._execute("ping", "SELECT task_id FROM main.fct_tasks LIMIT 0")

    async def update(self, task: Task, *, expected_etag: str | None = None) -> bool:
        if self._read_only or expected_etag is not None:
            raise TaskReadOnlyError()
        async with self._lock:
            rows = await self._execute(
                "update",
                "UPDATE main.fct_tasks SET task_title = ?, task_description = ?, status = ?, is_completed = ? "
                "WHERE lower(task_id) = ? RETURNING task_id",
                (task.title, task.description, task.status.value, task.status is TaskStatus.DONE, str(task.id)),
            )
            return bool(rows)

    async def delete(self, task_id: TaskId, *, expected_etag: str | None = None) -> bool:
        if self._read_only or expected_etag is not None:
            raise TaskReadOnlyError()
        async with self._lock:
            rows = await self._execute(
                "delete", "DELETE FROM main.fct_tasks WHERE lower(task_id) = ? RETURNING task_id", (str(task_id),)
            )
            return bool(rows)


def validate_duckdb_task_path(path: Path | None) -> Path:
    if path is None:
        raise TaskStorageConfigurationError("DUCKDB_PATH is required for the duckdb repository")
    if not path.is_file():
        raise TaskStorageConfigurationError("DUCKDB_PATH must refer to an existing DuckDB file")
    return path.resolve()


def _validate_table(connection: duckdb.DuckDBPyConnection) -> None:
    relation = connection.execute(
        "SELECT table_type FROM information_schema.tables WHERE table_schema = 'main' AND table_name = 'fct_tasks'"
    ).fetchall()
    if relation != [("BASE TABLE",)]:
        raise TaskStorageConfigurationError("DuckDB requires the dbt-created main.fct_tasks table; run dbt build first")
    columns = dict(
        connection.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'main' AND table_name = 'fct_tasks'"
        ).fetchall()
    )
    required = {
        "task_id": "VARCHAR",
        "task_title": "VARCHAR",
        "task_description": "VARCHAR",
        "status": "VARCHAR",
        "is_completed": "BOOLEAN",
    }
    if any(columns.get(name) != data_type for name, data_type in required.items()):
        raise TaskStorageConfigurationError(
            "main.fct_tasks must have the Task VARCHAR columns and BOOLEAN is_completed"
        )
    if connection.execute(
        "SELECT lower(task_id) FROM main.fct_tasks GROUP BY lower(task_id) "
        "HAVING lower(task_id) IS NULL OR count(*) > 1 LIMIT 1"
    ).fetchall():
        raise TaskStorageConfigurationError("main.fct_tasks must have unique, non-NULL task_id values")


@asynccontextmanager
async def open_duckdb_task_repository(
    path: Path | None, *, read_only: bool = False
) -> AsyncGenerator[DuckdbTaskRepository]:
    database_path = validate_duckdb_task_path(path)
    connection: duckdb.DuckDBPyConnection | None = None

    def connect() -> None:
        nonlocal connection
        connection = duckdb.connect(str(database_path), read_only=read_only)
        _validate_table(connection)

    try:
        await _run_sync(connect)
        if connection is None:
            raise RuntimeError("DuckDB connection was not initialized")
        yield DuckdbTaskRepository(connection, read_only=read_only)
    except duckdb.Error as error:
        raise _failure("lifespan", error) from None
    finally:
        if connection is not None:
            try:
                await _run_sync(connection.close)
            except duckdb.Error as error:
                raise _failure("close", error) from None
