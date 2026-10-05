import json
import runpy
from pathlib import Path
from unittest.mock import patch

import azure.functions as func
from fastapi.testclient import TestClient

from function_app import app as functions_app
from template_azure_python.api import app, create_app


def test_root_returns_hello_world():
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"Hello": "World"}


def test_app_factory_configures_telemetry():
    with patch("template_azure_python.api.configure_api_telemetry") as configure:
        application = create_app()

    configure.assert_called_once_with()
    with TestClient(application) as client:
        assert client.get("/").status_code == 200


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

    assert set(schema["paths"]) == {"/", "/tasks", "/tasks/{task_id}"}
    assert schema["paths"]["/"]["get"]["operationId"] == "read_root__get"
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
