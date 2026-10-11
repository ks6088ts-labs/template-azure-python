import asyncio
from threading import Event
from unittest.mock import MagicMock, patch
from uuid import UUID

import azure.functions as func
import duckdb
import pytest
from fastapi.testclient import TestClient

from template_azure_python.api import create_app
from template_azure_python.application import TaskAlreadyExistsError, TaskRepositoryError
from template_azure_python.domain import Task, TaskId, TaskStatus
from template_azure_python.infrastructure import (
    DuckdbTaskRepository,
    TaskStorageConfigurationError,
    open_duckdb_task_repository,
    validate_duckdb_task_path,
)
from template_azure_python.settings import TaskRepositoryBackend

TASK = Task(TaskId(UUID(int=1)), "First", "", TaskStatus.TODO)
MODULE = "template_azure_python.infrastructure.repositories.duckdb_task"


def test_existing_rows_and_persistent_crud(duckdb_file):
    with duckdb.connect(str(duckdb_file)) as connection:
        connection.execute(
            "INSERT INTO main.fct_tasks VALUES (?, ?, ?, ?, ?)",
            [str(TASK.id), " First ", " ", "todo", False],
        )

    async def scenario():
        async with open_duckdb_task_repository(duckdb_file) as repository:
            assert await repository.get(TASK.id) == TASK
            replacement = TASK.update(title="SQL ' ? ; --", description="Details", status=TaskStatus.DONE)
            assert await repository.update(replacement)
            second = Task.create("Second")
            await repository.add(second)
        async with open_duckdb_task_repository(duckdb_file) as repository:
            assert await repository.get(TASK.id) == replacement
            assert await repository.delete(second.id)
        async with open_duckdb_task_repository(duckdb_file) as repository:
            assert await repository.list() == (replacement,)
            assert await repository.get(second.id) is None

    asyncio.run(scenario())
    with duckdb.connect(str(duckdb_file)) as connection:
        assert connection.execute("SELECT is_completed FROM main.fct_tasks").fetchall() == [(True,)]


@pytest.mark.parametrize("status", list(TaskStatus))
def test_completion_flag_follows_add_and_update(duckdb_file, status):
    async def scenario():
        async with open_duckdb_task_repository(duckdb_file) as repository:
            task = TASK.update(title="First", description="", status=status)
            await repository.add(task)
        with duckdb.connect(str(duckdb_file)) as connection:
            assert connection.execute("SELECT is_completed FROM main.fct_tasks").fetchone() == (
                status is TaskStatus.DONE,
            )
        async with open_duckdb_task_repository(duckdb_file) as repository:
            assert await repository.update(task.update(title="Done", description="", status=TaskStatus.DONE))
            assert await repository.update(task)

    asyncio.run(scenario())
    with duckdb.connect(str(duckdb_file)) as connection:
        assert connection.execute("SELECT is_completed FROM main.fct_tasks").fetchone() == (status is TaskStatus.DONE,)


def test_concurrent_add_without_primary_key_is_serialized(duckdb_file):
    async def scenario():
        async with open_duckdb_task_repository(duckdb_file) as repository:
            results = await asyncio.gather(*(repository.add(TASK) for _ in range(8)), return_exceptions=True)
            assert results.count(None) == 1
            assert sum(isinstance(result, TaskAlreadyExistsError) for result in results) == 7
            assert await repository.list() == (TASK,)

    asyncio.run(scenario())


def test_dbt_uuid_case_does_not_change_task_identity(duckdb_file):
    task = Task(TaskId(UUID("abcdef01-0000-0000-0000-000000000001")), "First", "", TaskStatus.TODO)
    with duckdb.connect(str(duckdb_file)) as connection:
        connection.execute(
            "INSERT INTO main.fct_tasks VALUES (?, ?, ?, ?, ?)",
            [str(task.id).upper(), task.title, task.description, task.status.value, False],
        )

    async def scenario():
        async with open_duckdb_task_repository(duckdb_file) as repository:
            assert await repository.list() == (task,)
            assert await repository.get(task.id) == task
            with pytest.raises(TaskAlreadyExistsError):
                await repository.add(task)
            assert await repository.update(task.update(title="Done", description="", status=TaskStatus.DONE))
            updated = await repository.get(task.id)
            assert updated is not None and updated.status is TaskStatus.DONE
            assert await repository.delete(task.id)
            assert await repository.list() == ()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "row",
    [
        ("not-a-uuid", "Title", "", "todo", False),
        (str(TASK.id).replace("-", ""), "Title", "", "todo", False),
        ("{" + str(TASK.id) + "}", "Title", "", "todo", False),
        (str(TASK.id), None, "", "todo", False),
        (str(TASK.id), "Title", None, "todo", False),
        (str(TASK.id), "Title", "", None, False),
        (str(TASK.id), "Title", "", "invalid", False),
        (str(TASK.id), " ", "", "todo", False),
        (str(TASK.id), "a" * 201, "", "todo", False),
        (str(TASK.id), "Title", "b" * 2001, "todo", False),
        (str(TASK.id), "Title", "", "done", None),
        (str(TASK.id), "Title", "", "done", False),
    ],
)
def test_invalid_stored_rows_fail_without_partial_results(duckdb_file, row, caplog):
    with duckdb.connect(str(duckdb_file)) as connection:
        connection.execute("INSERT INTO main.fct_tasks VALUES (?, ?, ?, ?, ?)", row)

    async def scenario():
        async with open_duckdb_task_repository(duckdb_file) as repository:
            with pytest.raises(TaskRepositoryError):
                await repository.list()

    asyncio.run(scenario())
    assert "decode failed" in caplog.text
    assert "not-a-uuid" not in caplog.text


@pytest.mark.parametrize("operation", ["add", "get", "list", "update", "delete"])
@pytest.mark.parametrize("failure", ["closed", "missing-table"])
def test_storage_failure_is_not_task_absence(duckdb_file, operation, failure, caplog):
    with duckdb.connect(str(duckdb_file)) as connection:
        repository = DuckdbTaskRepository(connection)
        if failure == "closed":
            connection.close()
        else:
            connection.execute("DROP TABLE main.fct_tasks")

        async def scenario():
            with pytest.raises(TaskRepositoryError) as error:
                if operation == "list":
                    await repository.list()
                else:
                    await getattr(repository, operation)(TASK if operation in {"add", "update"} else TASK.id)
            assert str(error.value) == "Task storage is unavailable"
            assert error.value.__cause__ is None

        asyncio.run(scenario())
    assert f"{operation} failed" in caplog.text
    assert "SELECT" not in caplog.text


@pytest.mark.parametrize("path", [None, "missing", "directory"])
def test_invalid_path_does_not_connect(tmp_path, path):
    candidate = None if path is None else tmp_path / path
    if path == "directory":
        assert candidate is not None
        candidate.mkdir()
    with patch(f"{MODULE}.duckdb.connect") as connect:
        with pytest.raises(TaskStorageConfigurationError, match="DUCKDB_PATH"):
            validate_duckdb_task_path(candidate)
    connect.assert_not_called()


@pytest.mark.parametrize("schema", ["missing", "view", "columns", "type", "duplicate", "null-id", "uuid-case"])
def test_startup_rejects_invalid_table_and_closes_connection(duckdb_file, schema):
    connection = duckdb.connect(str(duckdb_file))
    if schema in {"missing", "view", "columns", "type"}:
        connection.execute("DROP TABLE main.fct_tasks")
    if schema == "view":
        connection.execute("CREATE VIEW main.fct_tasks AS SELECT 1 AS task_id")
    elif schema == "columns":
        connection.execute("CREATE TABLE main.fct_tasks (task_id VARCHAR)")
    elif schema == "type":
        connection.execute(
            "CREATE TABLE main.fct_tasks (task_id INTEGER, task_title VARCHAR, "
            "task_description VARCHAR, status VARCHAR, is_completed BOOLEAN)"
        )
    elif schema in {"duplicate", "null-id", "uuid-case"}:
        task_id = "abcdef01-0000-0000-0000-000000000001" if schema == "uuid-case" else str(TASK.id)
        row = [task_id if schema != "null-id" else None, "Task", "", "todo", False]
        connection.execute("INSERT INTO main.fct_tasks VALUES (?, ?, ?, ?, ?)", row)
        if schema in {"duplicate", "uuid-case"}:
            row[0] = task_id.upper()
            connection.execute("INSERT INTO main.fct_tasks VALUES (?, ?, ?, ?, ?)", row)
    proxy = MagicMock(wraps=connection)

    async def scenario():
        async with open_duckdb_task_repository(duckdb_file):
            pytest.fail("Invalid schema must not start")

    with patch(f"{MODULE}.duckdb.connect", return_value=proxy):
        with pytest.raises(TaskStorageConfigurationError):
            asyncio.run(scenario())
    proxy.close.assert_called_once()
    with pytest.raises(duckdb.ConnectionException):
        connection.execute("SELECT 1")


def test_corrupt_file_is_logged_as_storage_failure(tmp_path, caplog):
    path = tmp_path / "corrupt.duckdb"
    path.write_bytes(b"not a database")

    async def scenario():
        async with open_duckdb_task_repository(path):
            pytest.fail("Corrupt file must not start")

    with pytest.raises(TaskRepositoryError):
        asyncio.run(scenario())
    assert "lifespan failed" in caplog.text
    assert "not a database" not in caplog.text


@pytest.mark.parametrize("failure", [None, RuntimeError, asyncio.CancelledError])
def test_lifespan_closes_on_exit_exception_and_cancellation(duckdb_file, failure):
    connection = duckdb.connect(str(duckdb_file))
    proxy = MagicMock(wraps=connection)

    async def scenario():
        async with open_duckdb_task_repository(duckdb_file) as repository:
            await repository.add(TASK)
            if failure is not None:
                raise failure()

    with patch(f"{MODULE}.duckdb.connect", return_value=proxy):
        if failure is None:
            asyncio.run(scenario())
        else:
            with pytest.raises(failure):
                asyncio.run(scenario())
    proxy.close.assert_called_once()


def test_cancelled_query_retains_lock_until_worker_finishes():
    started, release = Event(), Event()
    connection = MagicMock()

    def execute(*_args):
        started.set()
        assert release.wait(5)
        return connection

    connection.execute.side_effect = execute
    connection.fetchall.return_value = []
    repository = DuckdbTaskRepository(connection)

    async def scenario():
        first = asyncio.create_task(repository.get(TASK.id))
        assert await asyncio.to_thread(started.wait, 5)
        first.cancel()
        await asyncio.sleep(0)
        second = asyncio.create_task(repository.list())
        first.cancel()
        await asyncio.sleep(0)
        assert connection.execute.call_count == 1
        assert not first.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert await second == ()

    try:
        asyncio.run(scenario())
    finally:
        release.set()


def test_cancelled_startup_still_closes_acquired_connection(duckdb_file):
    connection = duckdb.connect(str(duckdb_file))
    proxy = MagicMock(wraps=connection)
    started, release = Event(), Event()

    def validate(_connection):
        started.set()
        assert release.wait(5)

    async def start():
        async with open_duckdb_task_repository(duckdb_file):
            pytest.fail("Cancelled startup must not yield")

    async def scenario():
        task = asyncio.create_task(start())
        assert await asyncio.to_thread(started.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
        proxy.close.assert_not_called()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    try:
        with (
            patch(f"{MODULE}.duckdb.connect", return_value=proxy),
            patch(f"{MODULE}._validate_table", side_effect=validate),
        ):
            asyncio.run(scenario())
    finally:
        release.set()
    proxy.close.assert_called_once()


def test_api_lifespan_and_persistence_without_azure(duckdb_file, monkeypatch):
    monkeypatch.setenv("TASK_REPOSITORY", "duckdb")
    monkeypatch.setenv("DUCKDB_PATH", str(duckdb_file))
    with patch(f"{MODULE}.duckdb.connect", wraps=duckdb.connect) as connect:
        application = create_app()
        assert set(application.openapi()["paths"]) == {"/tasks", "/tasks/{task_id}"}
        connect.assert_not_called()
        with TestClient(application) as client:
            created = client.post("/tasks", json={"title": " Persist "})
            assert created.status_code == 201
            task = created.json()
            assert set(task) == {"id", "title", "description", "status"}
            assert client.get(f"/tasks/{task['id']}").json() == task
            assert client.put(f"/tasks/{task['id']}", json={"title": "Updated", "status": "done"}).status_code == 200
        connect.assert_called_once()
    with TestClient(create_app()) as client:
        assert client.get("/tasks").json() == [{**task, "title": "Updated", "status": "done"}]
        assert client.delete(f"/tasks/{task['id']}").status_code == 204
        assert client.get(f"/tasks/{task['id']}").status_code == 404


def test_invalid_database_row_uses_existing_503_http_contract(duckdb_file, monkeypatch):
    monkeypatch.setenv("DUCKDB_PATH", str(duckdb_file))
    with duckdb.connect(str(duckdb_file)) as connection:
        connection.execute("INSERT INTO main.fct_tasks VALUES (?, 'Task', '', 'secret-status', false)", [str(TASK.id)])
    with TestClient(create_app(repository_backend=TaskRepositoryBackend.DUCKDB)) as client:
        response = client.get("/tasks")
    assert response.status_code == 503
    assert response.json() == {"detail": "Task storage is unavailable"}


def test_functions_asgi_lifespan_uses_duckdb(duckdb_file, monkeypatch):
    monkeypatch.setenv("DUCKDB_PATH", str(duckdb_file))

    async def scenario():
        middleware = func.AsgiMiddleware(create_app(repository_backend=TaskRepositoryBackend.DUCKDB))
        assert await middleware.notify_startup()
        try:
            response = await middleware.handle_async(
                func.HttpRequest(
                    method="POST",
                    url="http://localhost/tasks",
                    headers={"Content-Type": "application/json"},
                    body=b'{"title":"Functions"}',
                ),
                None,
            )
            assert response.status_code == 201
            response = await middleware.handle_async(
                func.HttpRequest(method="GET", url="http://localhost/tasks", body=b""), None
            )
            assert response.status_code == 200
            assert b"Functions" in response.get_body()
        finally:
            await middleware.notify_shutdown()

    asyncio.run(scenario())
    with duckdb.connect(str(duckdb_file)) as connection:
        assert connection.execute("SELECT task_title FROM main.fct_tasks").fetchall() == [("Functions",)]
