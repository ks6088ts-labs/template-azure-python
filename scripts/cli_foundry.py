"""Run the Microsoft Foundry Python SDK quickstart from the command line."""

from typing import Annotated

import typer

from scripts._cli import cli_errors
from template_azure_python.internals.azure import foundry

DEFAULT_MODEL = "gpt-5-mini"
DEFAULT_AGENT_NAME = "MyAgent"
DEFAULT_INSTRUCTIONS = "You are a helpful assistant that answers general questions"
DEFAULT_PROMPT = "What is the size of France in square miles?"
DEFAULT_FOLLOW_UP_PROMPT = "And what is the capital city?"

app = typer.Typer(
    add_completion=False,
    help=(
        "Run the Microsoft Foundry SDK quickstart with Azure authentication. "
        "Set FOUNDRY_PROJECT_ENDPOINT in .env and run `az login` before using a command."
    ),
    no_args_is_help=True,
    rich_markup_mode="markdown",
)

EndpointOption = Annotated[
    str | None,
    typer.Option(
        "--endpoint",
        help="HTTPS Foundry project URL containing /api/projects/. Reads FOUNDRY_PROJECT_ENDPOINT when omitted.",
        metavar="URL",
    ),
]
ModelOption = Annotated[
    str, typer.Option("--model", "-m", help="Foundry model deployment name or instant model name.", show_default=True)
]
AgentNameOption = Annotated[
    str,
    typer.Option(
        "--agent-name", "-a", help="Stable name used to create or version the prompt agent.", show_default=True
    ),
]
InstructionsOption = Annotated[
    str, typer.Option("--instructions", "-i", help="System instructions for the prompt agent.", show_default=True)
]
PromptOption = Annotated[
    str, typer.Option("--prompt", "-p", help="User prompt sent to the model or agent.", show_default=True)
]


@app.command()
def chat_model(
    endpoint: EndpointOption = None, model: ModelOption = DEFAULT_MODEL, prompt: PromptOption = DEFAULT_PROMPT
) -> None:
    """Send one prompt directly to a Foundry model deployment."""
    with cli_errors():
        typer.echo(foundry.chat_model(endpoint, model, prompt))


@app.command()
def create_agent(
    endpoint: EndpointOption = None,
    agent_name: AgentNameOption = DEFAULT_AGENT_NAME,
    model: ModelOption = DEFAULT_MODEL,
    instructions: InstructionsOption = DEFAULT_INSTRUCTIONS,
) -> None:
    """Create a prompt agent, or create a new version when its name already exists."""
    with cli_errors():
        agent = foundry.create_agent(endpoint, agent_name, model, instructions)
        typer.echo(f"Agent created (id: {agent['id']}, name: {agent['name']}, version: {agent['version']})")


@app.command()
def chat_agent(
    endpoint: EndpointOption = None,
    agent_name: AgentNameOption = DEFAULT_AGENT_NAME,
    model: ModelOption = DEFAULT_MODEL,
    instructions: InstructionsOption = DEFAULT_INSTRUCTIONS,
    prompt: PromptOption = DEFAULT_PROMPT,
    follow_up_prompt: Annotated[
        str,
        typer.Option(
            "--follow-up-prompt", "-f", help="Second user prompt sent in the same conversation.", show_default=True
        ),
    ] = DEFAULT_FOLLOW_UP_PROMPT,
) -> None:
    """Create or version an agent, then run a two-turn conversation with it."""
    with cli_errors():
        foundry.chat_agent(endpoint, agent_name, model, instructions, prompt, follow_up_prompt, typer.echo)


if __name__ == "__main__":
    app()
