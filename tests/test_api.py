from fastapi.testclient import TestClient

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
