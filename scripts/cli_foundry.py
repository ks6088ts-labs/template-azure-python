"""Run the Microsoft Foundry Python SDK quickstart from the command line."""

# Usage:
#   cp .env.template .env
#   az login
#   uv run --locked python -m scripts.cli_foundry --help
#   uv run --locked python -m scripts.cli_foundry chat-model
#   uv run --locked python -m scripts.cli_foundry create-agent
#   uv run --locked python -m scripts.cli_foundry chat-agent

from typing import Annotated, Protocol, cast
from urllib.parse import urlparse

import typer
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import AgentVersionDetails, PromptAgentDefinition
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv
from openai import OpenAI

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


class TextResponse(Protocol):
    @property
    def output_text(self) -> str: ...


class AgentVersions(Protocol):
    def create_version(
        self,
        agent_name: str,
        *,
        definition: PromptAgentDefinition,
    ) -> AgentVersionDetails: ...


class FoundryProjectClient(Protocol):
    agents: AgentVersions

    def get_openai_client(
        self,
        *,
        agent_name: str | None = None,
    ) -> OpenAI: ...


EndpointOption = Annotated[
    str,
    typer.Option(
        "--endpoint",
        envvar="FOUNDRY_PROJECT_ENDPOINT",
        help=("HTTPS Foundry project URL containing /api/projects/. Reads FOUNDRY_PROJECT_ENDPOINT when omitted."),
        metavar="URL",
        show_envvar=True,
    ),
]
ModelOption = Annotated[
    str,
    typer.Option(
        "--model",
        "-m",
        help="Foundry model deployment name or instant model name.",
        show_default=True,
    ),
]
AgentNameOption = Annotated[
    str,
    typer.Option(
        "--agent-name",
        "-a",
        help="Stable name used to create or version the prompt agent.",
        show_default=True,
    ),
]
InstructionsOption = Annotated[
    str,
    typer.Option(
        "--instructions",
        "-i",
        help="System instructions that define the prompt agent's behavior.",
        show_default=True,
    ),
]
PromptOption = Annotated[
    str,
    typer.Option(
        "--prompt",
        "-p",
        help="User prompt sent to the model or agent.",
        show_default=True,
    ),
]


def _project_client(endpoint: str) -> FoundryProjectClient:
    parsed_endpoint = urlparse(endpoint)
    if parsed_endpoint.scheme != "https" or not parsed_endpoint.netloc or "/api/projects/" not in parsed_endpoint.path:
        raise typer.BadParameter(
            "must be an HTTPS Foundry project URL containing '/api/projects/'",
            param_hint="--endpoint",
        )

    project = AIProjectClient(
        endpoint=endpoint,
        credential=DefaultAzureCredential(),
    )
    return cast(FoundryProjectClient, project)


def _agent_definition(model: str, instructions: str) -> PromptAgentDefinition:
    return PromptAgentDefinition(
        model=model,
        instructions=instructions,
    )


def _print_response(response: TextResponse, response_name: str) -> None:
    if not response.output_text or not response.output_text.strip():
        typer.echo(f"Error: {response_name} output text was empty.", err=True)
        raise typer.Exit(code=1)
    typer.echo(response.output_text)


@app.command()
def chat_model(
    endpoint: EndpointOption,
    model: ModelOption = DEFAULT_MODEL,
    prompt: PromptOption = DEFAULT_PROMPT,
) -> None:
    """Send one prompt directly to a Foundry model deployment."""
    project = _project_client(endpoint)
    response = project.get_openai_client().responses.create(
        model=model,
        input=prompt,
    )
    _print_response(response, "Model response")


@app.command()
def create_agent(
    endpoint: EndpointOption,
    agent_name: AgentNameOption = DEFAULT_AGENT_NAME,
    model: ModelOption = DEFAULT_MODEL,
    instructions: InstructionsOption = DEFAULT_INSTRUCTIONS,
) -> None:
    """Create a prompt agent, or create a new version when its name already exists."""
    project = _project_client(endpoint)
    agent = project.agents.create_version(
        agent_name=agent_name,
        definition=_agent_definition(model, instructions),
    )
    typer.echo(f"Agent created (id: {agent.id}, name: {agent.name}, version: {agent.version})")


@app.command()
def chat_agent(
    endpoint: EndpointOption,
    agent_name: AgentNameOption = DEFAULT_AGENT_NAME,
    model: ModelOption = DEFAULT_MODEL,
    instructions: InstructionsOption = DEFAULT_INSTRUCTIONS,
    prompt: PromptOption = DEFAULT_PROMPT,
    follow_up_prompt: Annotated[
        str,
        typer.Option(
            "--follow-up-prompt",
            "-f",
            help="Second user prompt sent in the same conversation.",
            show_default=True,
        ),
    ] = DEFAULT_FOLLOW_UP_PROMPT,
) -> None:
    """Create or version an agent, then run a two-turn conversation with it."""
    project = _project_client(endpoint)
    project.agents.create_version(
        agent_name=agent_name,
        definition=_agent_definition(model, instructions),
    )

    openai = project.get_openai_client(agent_name=agent_name)
    conversation = openai.conversations.create()

    first_response = openai.responses.create(
        conversation=conversation.id,
        input=prompt,
    )
    _print_response(first_response, "First agent response")

    follow_up_response = openai.responses.create(
        conversation=conversation.id,
        input=follow_up_prompt,
    )
    _print_response(follow_up_response, "Follow-up agent response")


if __name__ == "__main__":
    load_dotenv(override=False)
    app()
