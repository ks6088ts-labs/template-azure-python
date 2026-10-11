import subprocess
from pathlib import Path
from unittest.mock import ANY, patch

import pytest
from typer.testing import CliRunner

from scripts.template import app


@pytest.mark.parametrize(
    ("options", "expected_host", "expected_port"),
    [
        ([], "127.0.0.1", 8000),
        (["--host", "0.0.0.0", "--port", "8080"], "0.0.0.0", 8080),
    ],
)
def test_serve_container_apps_command(options: list[str], expected_host: str, expected_port: int):
    with patch("scripts.template.uvicorn.run") as run, patch("template_azure_python.api.create_app") as create_app:
        result = CliRunner().invoke(app, ["serve-container-apps", *options])

    assert result.exit_code == 0, result.output
    run.assert_called_once_with(
        create_app.return_value,
        host=expected_host,
        port=expected_port,
    )


@pytest.mark.parametrize(
    ("options", "expected_port"),
    [
        ([], 7071),
        (["--port", "8080"], 8080),
    ],
)
def test_serve_functions_command(options: list[str], expected_port: int):
    completed = subprocess.CompletedProcess(["func", "start"], 0)
    with patch("scripts.template.subprocess.run", return_value=completed) as run:
        result = CliRunner().invoke(app, ["serve-functions", *options])

    assert result.exit_code == 0, result.output
    run.assert_called_once_with(
        ["func", "start", "--port", str(expected_port)],
        cwd=Path(__file__).resolve().parents[1],
        check=False,
        env=ANY,
    )
    assert run.call_args.kwargs["env"]["TASK_REPOSITORY"] == "in-memory"


@pytest.mark.parametrize("command", ["serve-container-apps", "serve-functions"])
@pytest.mark.parametrize("port", ["0", "65536"])
def test_serve_rejects_invalid_port(command: str, port: str):
    with (
        patch("scripts.template.uvicorn.run") as uvicorn_run,
        patch("scripts.template.subprocess.run") as functions_run,
    ):
        result = CliRunner().invoke(app, [command, "--port", port])

    assert result.exit_code != 0
    assert "port" in result.output.lower()
    uvicorn_run.assert_not_called()
    functions_run.assert_not_called()


def test_serve_functions_reports_missing_core_tools():
    with patch("scripts.template.subprocess.run", side_effect=FileNotFoundError("func")) as run:
        result = CliRunner().invoke(app, ["serve-functions"])

    assert result.exit_code == 1
    assert "Core Tools" in result.output
    run.assert_called_once()


def test_serve_functions_propagates_host_failure():
    completed = subprocess.CompletedProcess(["func", "start"], 42)
    with patch("scripts.template.subprocess.run", return_value=completed):
        result = CliRunner().invoke(app, ["serve-functions"])

    assert result.exit_code == 42
    assert "status 42" in result.output


@pytest.mark.parametrize("command", ["serve-container-apps", "serve-functions"])
@pytest.mark.parametrize("backend", ["in-memory", "cosmosdb", "duckdb"])
def test_serve_repository_selection(command, backend, duckdb_file):
    from template_azure_python.settings import TaskRepositoryBackend

    with (
        patch("scripts.template.uvicorn.run"),
        patch("template_azure_python.api.create_app") as create_app,
        patch("scripts.template.subprocess.run", return_value=subprocess.CompletedProcess([], 0)) as run,
    ):
        result = CliRunner().invoke(
            app,
            [command, "--repository", backend],
            env={
                "AZURE_COSMOS_DB_ENDPOINT": "https://example.documents.azure.com/",
                "DUCKDB_PATH": str(duckdb_file),
            },
        )
    assert result.exit_code == 0, result.output
    if command == "serve-container-apps":
        create_app.assert_called_once_with(repository_backend=TaskRepositoryBackend(backend))
    else:
        assert run.call_args.kwargs["env"]["TASK_REPOSITORY"] == backend
        if backend == "duckdb":
            assert run.call_args.kwargs["env"]["DUCKDB_PATH"] == str(duckdb_file)


@pytest.mark.parametrize("command", ["serve-container-apps", "serve-functions"])
def test_serve_rejects_unknown_repository_and_missing_cosmos_settings(command):
    with patch("scripts.template.uvicorn.run") as uvicorn_run, patch("scripts.template.subprocess.run") as run:
        invalid = CliRunner().invoke(app, [command, "--repository", "unknown"])
        missing = CliRunner().invoke(app, [command, "--repository", "cosmosdb"])
    assert invalid.exit_code == missing.exit_code == 2
    assert "AZURE_COSMOS_DB_ENDPOINT" in missing.output
    uvicorn_run.assert_not_called()
    run.assert_not_called()


@pytest.mark.parametrize("command", ["serve-container-apps", "serve-functions"])
def test_explicit_memory_overrides_environment_cosmos_without_endpoint(command):
    with (
        patch("scripts.template.uvicorn.run"),
        patch("template_azure_python.api.create_app") as create_app,
        patch("scripts.template.subprocess.run", return_value=subprocess.CompletedProcess([], 0)) as run,
    ):
        result = CliRunner().invoke(app, [command, "--repository", "in-memory"], env={"TASK_REPOSITORY": "cosmosdb"})
    assert result.exit_code == 0, result.output
    if command == "serve-container-apps":
        assert create_app.call_args.kwargs["repository_backend"].value == "in-memory"
    else:
        assert run.call_args.kwargs["env"]["TASK_REPOSITORY"] == "in-memory"


@pytest.mark.parametrize("command", ["serve-container-apps", "serve-functions"])
@pytest.mark.parametrize("path", [None, "", "/nonexistent/task-file.duckdb"])
def test_duckdb_cli_rejects_missing_file(command, path):
    env = {} if path is None else {"DUCKDB_PATH": path}
    with patch("scripts.template.uvicorn.run") as server, patch("scripts.template.subprocess.run") as functions:
        result = CliRunner().invoke(app, [command, "--repository", "duckdb"], env=env)
    assert result.exit_code == 2
    assert "DUCKDB_PATH" in result.output
    server.assert_not_called()
    functions.assert_not_called()


@pytest.mark.parametrize("command", ["serve-container-apps", "serve-functions"])
def test_memory_override_does_not_require_duckdb_file(command):
    with (
        patch("scripts.template.uvicorn.run"),
        patch("scripts.template.subprocess.run", return_value=subprocess.CompletedProcess([], 0)),
    ):
        result = CliRunner().invoke(app, [command, "--repository", "in-memory"], env={"TASK_REPOSITORY": "duckdb"})
    assert result.exit_code == 0, result.output
