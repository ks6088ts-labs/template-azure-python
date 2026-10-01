import subprocess
from pathlib import Path
from unittest.mock import patch

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
    with patch("scripts.template.uvicorn.run") as run:
        result = CliRunner().invoke(app, ["serve-container-apps", *options])

    assert result.exit_code == 0, result.output
    run.assert_called_once_with(
        "template_azure_python.api:app",
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
    )


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
