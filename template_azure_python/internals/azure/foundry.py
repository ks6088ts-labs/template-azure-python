from collections.abc import Callable, Generator
from contextlib import closing, contextmanager
from typing import Protocol, cast
from urllib.parse import urlparse

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import AgentVersionDetails, PromptAgentDefinition
from azure.identity import DefaultAzureCredential
from openai import OpenAI, OpenAIError

from template_azure_python.internals.azure._common import InputError, OperationError, azure_errors, required_value
from template_azure_python.settings import get_azure_settings


class _AgentVersions(Protocol):
    def create_version(self, agent_name: str, *, definition: PromptAgentDefinition) -> AgentVersionDetails: ...


class _ProjectClient(Protocol):
    agents: _AgentVersions

    def get_openai_client(self, *, agent_name: str | None = None) -> OpenAI: ...


@contextmanager
def _project_client(endpoint: str | None) -> Generator[_ProjectClient, None, None]:
    endpoint = required_value(endpoint, get_azure_settings().foundry_project_endpoint, "--endpoint")
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.netloc or "/api/projects/" not in parsed.path:
        raise InputError("must be an HTTPS Foundry project URL containing '/api/projects/'", "--endpoint")
    with azure_errors("Microsoft Foundry operation failed."):
        try:
            with closing(DefaultAzureCredential()) as credential:
                with closing(AIProjectClient(endpoint=endpoint, credential=credential)) as project:
                    yield cast(_ProjectClient, project)
        except OpenAIError as exc:
            raise OperationError("Microsoft Foundry operation failed.") from exc


def _response_text(text: str, name: str) -> str:
    if not text or not text.strip():
        raise OperationError(f"{name} output text was empty.")
    return text


def chat_model(endpoint: str | None, model: str, prompt: str) -> str:
    with _project_client(endpoint) as project, closing(project.get_openai_client()) as openai:
        response = openai.responses.create(model=model, input=prompt)
        return _response_text(response.output_text, "Model response")


def create_agent(endpoint: str | None, agent_name: str, model: str, instructions: str) -> dict[str, object]:
    with _project_client(endpoint) as project:
        agent = project.agents.create_version(
            agent_name=agent_name, definition=PromptAgentDefinition(model=model, instructions=instructions)
        )
        return {"id": agent.id, "name": agent.name, "version": agent.version}


def chat_agent(
    endpoint: str | None,
    agent_name: str,
    model: str,
    instructions: str,
    prompt: str,
    follow_up_prompt: str,
    emit: Callable[[str], None],
) -> None:
    with _project_client(endpoint) as project:
        project.agents.create_version(
            agent_name=agent_name, definition=PromptAgentDefinition(model=model, instructions=instructions)
        )
        with closing(project.get_openai_client(agent_name=agent_name)) as openai:
            conversation = openai.conversations.create()
            first = openai.responses.create(conversation=conversation.id, input=prompt)
            emit(_response_text(first.output_text, "First agent response"))
            follow_up = openai.responses.create(conversation=conversation.id, input=follow_up_prompt)
            emit(_response_text(follow_up.output_text, "Follow-up agent response"))
