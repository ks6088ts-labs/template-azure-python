import base64
import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from template_azure_python.api import create_app
from template_azure_python.infrastructure import InMemoryTaskRepository
from template_azure_python.settings import ProjectSettings


def principal(*, role: str | None = None) -> str:
    claims = [{"typ": "sub", "val": "test-user"}]
    if role:
        claims.append({"typ": "roles", "val": role})
    return base64.b64encode(json.dumps({"auth_typ": "aad", "role_typ": "roles", "claims": claims}).encode()).decode()


def secure_app(**kwargs):
    return create_app(settings=ProjectSettings(_env_file=None, auth_mode="easyauth", **kwargs))


@pytest.mark.parametrize("header", [None, "", "not-base64", "e30=", "bnVsbA==", "W10=", "a" * 16385])
def test_easyauth_fails_closed_for_missing_or_malformed_principal(header):
    headers = {} if header is None else {"x-ms-client-principal": header}
    with TestClient(secure_app()) as client:
        response = client.get("/tasks", headers=headers)
        assert client.get("/healthz").status_code == 200
        assert client.get("/readyz").status_code == 200
    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"


@pytest.mark.parametrize(
    "payload",
    [
        {"auth_typ": "aad", "claims": []},
        {"auth_typ": "", "claims": [{"typ": "sub", "val": "user"}]},
        {"auth_typ": "aad", "claims": [{"typ": "sub", "val": ""}]},
        {"auth_typ": "aad", "claims": [{"typ": "sub", "val": 42}]},
        {"auth_typ": "aad", "claims": [{"typ": "roles", "val": "writer"}]},
        {"auth_typ": "aad", "claims": [None]},
    ],
)
def test_invalid_principal_claim_shapes_are_unauthorized(payload):
    header = base64.b64encode(json.dumps(payload).encode()).decode()
    with TestClient(secure_app()) as client:
        assert client.get("/tasks", headers={"x-ms-client-principal": header}).status_code == 401


def test_duplicate_principal_headers_are_rejected():
    with TestClient(secure_app()) as client:
        response = client.get(
            "/tasks",
            headers=[
                ("x-ms-client-principal", principal()),
                ("x-ms-client-principal", principal()),
            ],
        )
    assert response.status_code == 401


def test_required_role_is_enforced_for_reads_and_mutations():
    with TestClient(secure_app(auth_required_role="writer")) as client:
        for method in ("GET", "POST"):
            assert (
                client.request(
                    method,
                    "/tasks",
                    headers={"x-ms-client-principal": principal(role="reader")},
                    json={"title": "Task"},
                ).status_code
                == 403
            )
        response = client.post(
            "/tasks",
            headers={"x-ms-client-principal": principal(role="writer")},
            json={"title": "Task"},
        )
        assert response.status_code == 201
        assert client.get("/tasks", headers={"x-ms-client-principal": principal(role="writer")}).status_code == 200


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_deployed_docs_are_disabled_and_explicit_override_works(environment):
    with TestClient(create_app(settings=ProjectSettings(_env_file=None, app_environment=environment))) as client:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert client.get(path).status_code == 404
    settings = ProjectSettings(_env_file=None, app_environment=environment, app_docs_enabled=True)
    with TestClient(create_app(settings=settings)) as client:
        assert client.get("/docs").status_code == 200


def test_probes_are_cheap_and_readiness_failure_is_sanitized():
    repository = InMemoryTaskRepository()
    settings = ProjectSettings(_env_file=None, app_version="1.2.3")
    with (
        patch.object(
            repository, "list", AsyncMock(side_effect=AssertionError("must not enumerate"))
        ) as enumerate_tasks,
        patch.object(repository, "ping", AsyncMock()) as ping,
        TestClient(create_app(repository=repository, settings=settings)) as client,
    ):
        assert client.get("/healthz").json() == {"status": "ok", "version": "1.2.3"}
        assert client.get("/readyz").json() == {"status": "ready", "version": "1.2.3"}
        ping.assert_awaited_once()
        enumerate_tasks.assert_not_awaited()
        ping.side_effect = RuntimeError("credential-secret")
        response = client.get("/readyz")
    assert response.status_code == 503
    assert "credential-secret" not in response.text


def test_cors_is_allowlisted_and_security_headers_preserve_context():
    settings = ProjectSettings(_env_file=None, cors_allowed_origins=["https://frontend.example"])
    with TestClient(create_app(settings=settings), base_url="https://api.example") as client:
        allowed = client.get("/tasks", headers={"Origin": "https://frontend.example"})
        denied = client.get("/tasks", headers={"Origin": "https://attacker.example"})
        preflight = client.options(
            "/tasks",
            headers={
                "Origin": "https://frontend.example",
                "Access-Control-Request-Method": "PUT",
                "Access-Control-Request-Headers": "Authorization,If-Match",
            },
        )
    assert allowed.headers["access-control-allow-origin"] == "https://frontend.example"
    assert "access-control-allow-origin" not in denied.headers
    assert preflight.status_code == 200
    assert "authorization" in preflight.headers["access-control-allow-headers"].lower()
    for response in (allowed, denied, preflight):
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["strict-transport-security"] == "max-age=31536000"


def test_unexpected_failures_do_not_expose_sensitive_details(caplog):
    repository = InMemoryTaskRepository()
    with (
        patch.object(repository, "page", AsyncMock(side_effect=RuntimeError("unexpected-sensitive-value"))),
        TestClient(create_app(repository=repository), raise_server_exceptions=False) as client,
    ):
        response = client.get("/tasks")
    assert response.status_code == 500
    assert response.headers["content-type"] == "application/problem+json"
    assert "unexpected-sensitive-value" not in response.text
    assert "unexpected-sensitive-value" not in caplog.text
    assert response.headers["x-content-type-options"] == "nosniff"


def test_etags_support_conditional_update_and_delete():
    with TestClient(create_app()) as client:
        created = client.post("/tasks", json={"title": "Task"})
        task_id = created.json()["id"]
        original_etag = created.headers["etag"]
        assert client.get(f"/tasks/{task_id}").headers["etag"] == original_etag
        updated = client.put(
            f"/tasks/{task_id}",
            json={"title": "Updated", "status": "done"},
            headers={"If-Match": original_etag},
        )
        assert updated.status_code == 200
        assert updated.headers["etag"] != original_etag
        stale = client.put(
            f"/tasks/{task_id}",
            json={"title": "Stale", "status": "todo"},
            headers={"If-Match": original_etag},
        )
        assert stale.status_code == 412
        assert client.delete(f"/tasks/{task_id}", headers={"If-Match": original_etag}).status_code == 412
        assert client.get(f"/tasks/{task_id}").json()["title"] == "Updated"
        assert client.delete(f"/tasks/{task_id}", headers={"If-Match": updated.headers["etag"]}).status_code == 204


@pytest.mark.parametrize("etag", ["*", 'W/"version"', "unquoted", '""', '"a", "b"'])
def test_if_match_rejects_unsupported_etags(etag):
    with TestClient(create_app()) as client:
        task_id = client.post("/tasks", json={"title": "Task"}).json()["id"]
        assert client.delete(f"/tasks/{task_id}", headers={"If-Match": etag}).status_code == 400


def test_pagination_preserves_array_and_total_count():
    with TestClient(create_app()) as client:
        for index in range(105):
            assert client.post("/tasks", json={"title": f"Task {index}"}).status_code == 201
        first = client.get("/tasks")
        second = client.get("/tasks?offset=100&limit=5")
        assert len(first.json()) == 100
        assert len(second.json()) == 5
        assert first.headers["x-total-count"] == second.headers["x-total-count"] == "105"
        assert not {task["id"] for task in first.json()} & {task["id"] for task in second.json()}
        for query in ("offset=-1", "offset=100001", "limit=0", "limit=101"):
            assert client.get(f"/tasks?{query}").status_code == 422
