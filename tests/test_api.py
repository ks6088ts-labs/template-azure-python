import json
import runpy
from pathlib import Path
from unittest.mock import patch

import azure.functions as func
from fastapi.testclient import TestClient

from function_app import app as functions_app
from template_azure_python.api import app


def test_root_returns_hello_world():
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"Hello": "World"}


def test_no_items_endpoint():
    with TestClient(app) as client:
        response = client.get("/items/1")

    assert response.status_code == 404


def test_api_documentation():
    with TestClient(app) as client:
        response = client.get("/docs")

    assert response.status_code == 200


def test_functions_wraps_the_same_fastapi_app():
    assert isinstance(functions_app, func.AsgiFunctionApp)

    with patch("azure.functions.AsgiFunctionApp") as asgi_app:
        module = runpy.run_path(str(Path(__file__).resolve().parents[1] / "function_app.py"))

    asgi_app.assert_called_once_with(app=app, http_auth_level=func.AuthLevel.ANONYMOUS)
    assert module["app"] is asgi_app.return_value


def test_functions_routes_have_no_api_prefix():
    config = json.loads((Path(__file__).resolve().parents[1] / "host.json").read_text())

    assert config["extensions"]["http"]["routePrefix"] == ""
