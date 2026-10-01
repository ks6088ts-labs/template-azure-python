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
def test_serve_command(options: list[str], expected_host: str, expected_port: int):
    with patch("scripts.template.uvicorn.run") as run:
        result = CliRunner().invoke(app, ["serve", *options])

    assert result.exit_code == 0, result.output
    run.assert_called_once_with(
        "template_azure_python.api:app",
        host=expected_host,
        port=expected_port,
    )


@pytest.mark.parametrize("port", ["0", "65536"])
def test_serve_rejects_invalid_port(port: str):
    with patch("scripts.template.uvicorn.run") as run:
        result = CliRunner().invoke(app, ["serve", "--port", port])

    assert result.exit_code != 0
    assert "port" in result.output.lower()
    run.assert_not_called()
