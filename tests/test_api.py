import json
import runpy
from pathlib import Path
from unittest.mock import patch

import azure.functions as func
import pytest
from fastapi.testclient import TestClient

from function_app import app as functions_app
from template_azure_python.api import app, create_app
from template_azure_python.domain import Task


def test_mock_root_is_removed():
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 404


def test_app_factory_configures_telemetry():
    with patch("template_azure_python.api.configure_api_telemetry") as configure:
        application = create_app()

    configure.assert_called_once_with()
    with TestClient(application) as client:
        assert client.get("/tasks").status_code == 200


def test_no_items_endpoint():
    with TestClient(app) as client:
        response = client.get("/items/1")

    assert response.status_code == 404


def test_api_documentation():
    with TestClient(app) as client:
        response = client.get("/docs")

    assert response.status_code == 200


def test_router_is_in_openapi():
    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()

    assert set(schema["paths"]) == {"/tasks", "/tasks/{task_id}"}
    assert schema["paths"]["/tasks"]["post"]["operationId"] == "create_task"


def test_functions_wraps_the_same_fastapi_app():
    assert isinstance(functions_app, func.AsgiFunctionApp)

    with patch("azure.functions.AsgiFunctionApp") as asgi_app:
        module = runpy.run_path(str(Path(__file__).resolve().parents[1] / "function_app.py"))

    asgi_app.assert_called_once_with(app=app, http_auth_level=func.AuthLevel.ANONYMOUS)
    assert module["app"] is asgi_app.return_value


def test_functions_routes_have_no_api_prefix():
    config = json.loads((Path(__file__).resolve().parents[1] / "host.json").read_text())

    assert config["extensions"]["http"]["routePrefix"] == ""


def test_task_crud_api():
    application = create_app()
    with TestClient(application) as client:
        create_response = client.post("/tasks", json={"title": "  Ship template  ", "description": "Document it"})
        assert create_response.status_code == 201
        created = create_response.json()
        assert created["title"] == "Ship template"
        assert created["status"] == "todo"

        task_id = created["id"]
        assert client.get("/tasks").json() == [created]
        assert client.get(f"/tasks/{task_id}").json() == created

        update_response = client.put(
            f"/tasks/{task_id}",
            json={"title": "Ship template", "description": "Complete", "status": "done"},
        )
        assert update_response.status_code == 200
        assert update_response.json()["status"] == "done"

        assert client.delete(f"/tasks/{task_id}").status_code == 204
        missing_response = client.get(f"/tasks/{task_id}")
        assert missing_response.status_code == 404
        assert missing_response.json() == {"detail": f"Task {task_id} was not found"}


def test_task_api_validation_and_application_state_isolation():
    first_application = create_app()
    second_application = create_app()

    with TestClient(first_application) as first_client:
        assert first_client.post("/tasks", json={"title": " "}).json() == {"detail": "Task title must not be empty"}
        invalid_response = first_client.post("/tasks", json={"title": ""})
        assert invalid_response.status_code == 422
        assert invalid_response.json() == {"detail": "String should have at least 1 character"}
        assert first_client.post("/tasks", json={"title": "Persist only here"}).status_code == 201

    with TestClient(second_application) as second_client:
        assert second_client.get("/tasks").json() == []


@pytest.mark.parametrize(
    ("method", "path", "body", "schema_path"),
    [
        ("post", "/tasks", {"title": ""}, "/tasks"),
        ("get", "/tasks/not-a-uuid", None, "/tasks/{task_id}"),
        (
            "put",
            "/tasks/not-a-uuid",
            {"title": "Valid", "description": "", "status": "todo"},
            "/tasks/{task_id}",
        ),
        ("delete", "/tasks/not-a-uuid", None, "/tasks/{task_id}"),
    ],
)
def test_task_validation_response_matches_openapi(method: str, path: str, body: object, schema_path: str):
    with TestClient(create_app()) as client:
        response = client.request(method, path, json=body)
        schema = client.get("/openapi.json").json()

    assert response.status_code == 422
    assert set(response.json()) == {"detail"}
    assert isinstance(response.json()["detail"], str)
    assert response.json()["detail"]
    assert schema["paths"][schema_path][method]["responses"]["422"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }
    assert schema["components"]["schemas"]["ErrorResponse"]["properties"]["detail"]["type"] == "string"


@pytest.mark.parametrize(
    ("title", "description", "expected_status"),
    [
        ("a", "", 201),
        ("a" * 200, "b" * 2000, 201),
        ("a" * 201, "", 422),
        ("Valid", "b" * 2001, 422),
        (" ", "", 422),
    ],
)
def test_task_http_validation_boundaries(title: str, description: str, expected_status: int):
    with TestClient(create_app()) as client:
        response = client.post("/tasks", json={"title": title, "description": description})
        tasks = client.get("/tasks").json()

    assert response.status_code == expected_status
    assert len(tasks) == (1 if expected_status == 201 else 0)


@pytest.mark.parametrize("method", ["put", "delete"])
def test_task_missing_mutation_returns_not_found(method: str):
    task_id = "00000000-0000-0000-0000-000000000001"
    with TestClient(create_app()) as client:
        response = client.request(
            method, f"/tasks/{task_id}", json={"title": "Missing", "description": "", "status": "todo"}
        )

    assert response.status_code == 404
    assert response.json() == {"detail": f"Task {task_id} was not found"}


def test_task_duplicate_returns_conflict():
    task = Task.create("Duplicate")
    with (
        TestClient(create_app()) as client,
        patch("template_azure_python.application.task.Task.create", return_value=task),
    ):
        assert client.post("/tasks", json={"title": "Duplicate"}).status_code == 201
        response = client.post("/tasks", json={"title": "Duplicate"})
        assert len(client.get("/tasks").json()) == 1

    assert response.status_code == 409
    assert response.json() == {"detail": f"Task {task.id} already exists"}


def test_explicit_repository_is_used_and_ambiguous_injection_is_rejected():
    from template_azure_python.infrastructure import InMemoryTaskRepository
    from template_azure_python.settings import TaskRepositoryBackend

    repository = InMemoryTaskRepository()
    with TestClient(create_app(repository=repository)) as client:
        task = client.post("/tasks", json={"title": "Injected"}).json()
    with TestClient(create_app(repository=repository)) as client:
        assert client.get("/tasks").json() == [task]
    with pytest.raises(ValueError, match="either"):
        create_app(repository=repository, repository_backend=TaskRepositoryBackend.IN_MEMORY)


@pytest.mark.parametrize(
    ("method", "path", "operation"),
    [
        ("post", "/tasks", "add"),
        ("get", "/tasks", "list"),
        ("get", "/tasks/00000000-0000-0000-0000-000000000001", "get"),
        ("put", "/tasks/00000000-0000-0000-0000-000000000001", "get"),
        ("delete", "/tasks/00000000-0000-0000-0000-000000000001", "delete"),
    ],
)
def test_storage_failure_matches_openapi(method, path, operation, caplog):
    from unittest.mock import AsyncMock

    from template_azure_python.application import TaskRepositoryError
    from template_azure_python.infrastructure import InMemoryTaskRepository

    repository = InMemoryTaskRepository()
    with (
        patch.object(repository, operation, AsyncMock(side_effect=TaskRepositoryError())),
        TestClient(create_app(repository=repository)) as client,
    ):
        body = {"title": "Task", "status": "todo"} if method == "put" else {"title": "Task"}
        response = client.request(method, path, json=body)
        schema = client.get("/openapi.json").json()
    assert response.status_code == 503
    assert response.json() == {"detail": "Task storage is unavailable"}
    schema_path = "/tasks" if path == "/tasks" else "/tasks/{task_id}"
    assert schema["paths"][schema_path][method]["responses"]["503"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }
    assert "Task storage unavailable" in caplog.text
