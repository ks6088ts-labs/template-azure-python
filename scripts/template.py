import logging
from typing import Annotated

import typer
from dotenv import load_dotenv

from template_python.core import hello_world
from template_python.loggers import get_logger
from template_python.settings import get_project_settings

app = typer.Typer(
    add_completion=False,
    help="template-python CLI",
)

logger = get_logger(__name__)


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


if __name__ == "__main__":
    if not load_dotenv(override=True, verbose=True):
        logging.warning("No .env file found; using defaults")
    app()
