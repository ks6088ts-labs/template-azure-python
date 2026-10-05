import logging
import subprocess
from pathlib import Path
from typing import Annotated

import typer
import uvicorn
from pydantic import ValidationError

from template_azure_python.core import hello_world
from template_azure_python.infrastructure import TaskStorageConfigurationError, validate_cosmos_task_settings
from template_azure_python.loggers import get_logger
from template_azure_python.settings import (
    TaskRepositoryBackend,
    functions_environment,
    get_azure_settings,
    get_project_settings,
)

app = typer.Typer(
    add_completion=False,
    help="template-azure-python CLI",
)

logger = get_logger(__name__)

RepositoryOption = Annotated[
    TaskRepositoryBackend | None,
    typer.Option("--repository", help="Task storage backend. Reads TASK_REPOSITORY; defaults to in-memory."),
]


def _repository(value: TaskRepositoryBackend | None) -> TaskRepositoryBackend:
    try:
        backend = value if value is not None else get_project_settings().task_repository
        if backend is TaskRepositoryBackend.COSMOSDB:
            validate_cosmos_task_settings(get_azure_settings().cosmos_db)
        return backend
    except (ValidationError, TaskStorageConfigurationError) as error:
        raise typer.BadParameter(str(error), param_hint="--repository") from None


@app.callback()
def main(
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            "-v",
            help="Enable verbose output",
        ),
    ] = False,
):
    if verbose:
        logging.basicConfig(level=logging.DEBUG)
        logger.setLevel(logging.DEBUG)


@app.command()
def hello(
    name: Annotated[
        str,
        typer.Option(
            "--name",
            "-n",
            help="Name of the person to greet",
        ),
    ] = "World",
):
    hello_world()
    logger.debug(f"This is a debug message with name: {name}")
    logger.info(f"Settings from .env: {get_project_settings().model_dump_json(indent=2)}")


@app.command()
def serve_container_apps(
    host: Annotated[
        str,
        typer.Option(
            "--host",
            help="Host to bind the server to",
        ),
    ] = "127.0.0.1",
    port: Annotated[
        int,
        typer.Option(
            "--port",
            min=1,
            max=65535,
            help="Port to bind the server to",
        ),
    ] = 8000,
    repository: RepositoryOption = None,
):
    backend = _repository(repository)
    from template_azure_python.api import create_app

    uvicorn.run(create_app(repository_backend=backend), host=host, port=port)


@app.command()
def serve_functions(
    port: Annotated[
        int,
        typer.Option(
            "--port",
            min=1,
            max=65535,
            help="Port to bind the Functions host to",
        ),
    ] = 7071,
    repository: RepositoryOption = None,
):
    backend = _repository(repository)
    try:
        result = subprocess.run(
            ["func", "start", "--port", str(port)],
            cwd=Path(__file__).resolve().parents[1],
            check=False,
            env=functions_environment(backend),
        )
    except FileNotFoundError as exc:
        typer.echo("Azure Functions Core Tools (func) not found. Install Core Tools v4.", err=True)
        raise typer.Exit(code=1) from exc

    if result.returncode != 0:
        typer.echo(f"Azure Functions host exited with status {result.returncode}.", err=True)
        raise typer.Exit(code=result.returncode)


if __name__ == "__main__":
    app()
