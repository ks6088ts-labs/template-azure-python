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

    assert set(schema["paths"]) == {"/"}
    assert schema["paths"]["/"]["get"]["operationId"] == "read_root__get"


def test_functions_wraps_the_same_fastapi_app():
    assert isinstance(functions_app, func.AsgiFunctionApp)

    with patch("azure.functions.AsgiFunctionApp") as asgi_app:
        module = runpy.run_path(str(Path(__file__).resolve().parents[1] / "function_app.py"))

    asgi_app.assert_called_once_with(app=app, http_auth_level=func.AuthLevel.ANONYMOUS)
    assert module["app"] is asgi_app.return_value


def test_functions_routes_have_no_api_prefix():
    config = json.loads((Path(__file__).resolve().parents[1] / "host.json").read_text())

    assert config["extensions"]["http"]["routePrefix"] == ""
