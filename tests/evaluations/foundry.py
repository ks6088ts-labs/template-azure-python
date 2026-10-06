import logging
from collections.abc import Callable, Generator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from types import TracebackType
from typing import Literal, Protocol, cast
from uuid import uuid4

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition
from azure.ai.projects.operations import AgentsOperations
from azure.identity import DefaultAzureCredential
from openai import OpenAI

from tests.evaluations.config import EvaluationSettings, Scenario

logger = logging.getLogger(__name__)


class EvaluationProject(Protocol):
    agents: AgentsOperations

    def get_openai_client(self, *, agent_name: str, timeout: float, max_retries: int) -> OpenAI: ...

    def close(self) -> None: ...


class ResourceScope(ExitStack):
    def __init__(self) -> None:
        super().__init__()
        self.failures: list[str] = []

    def register_cleanup(self, description: str, action: Callable[[], object]) -> None:
        self.callback(self._attempt_cleanup, description, action)

    def _attempt_cleanup(self, description: str, action: Callable[[], object]) -> None:
        try:
            action()
        except Exception as error:
            self.failures.append(f"{description} ({type(error).__name__})")

    def __exit__(
        self, exc_type: type[BaseException] | None, exc_value: BaseException | None, traceback: TracebackType | None
    ) -> Literal[False]:
        super().__exit__(exc_type, exc_value, traceback)
        if self.failures:
            message = "Evaluation cleanup failed: " + "; ".join(self.failures)
            if exc_value is None:
                raise RuntimeError(message)
            logger.error(message)
        return False


@dataclass(frozen=True)
class AgentTurn:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class FoundryAgent:
    client: OpenAI
    name: str
    version: str
    settings: EvaluationSettings

    def run(self, scenario: Scenario) -> list[AgentTurn]:
        turns: list[AgentTurn] = []
        with ResourceScope() as resources:
            conversation = self.client.conversations.create()
            resources.register_cleanup(
                f"conversation {conversation.id}", lambda: self.client.conversations.delete(conversation.id)
            )
            for prompt in scenario.prompts:
                actual_input = scenario.agent_prompt(prompt)
                response = self.client.responses.create(
                    conversation=conversation.id, input=actual_input, max_output_tokens=self.settings.max_output_tokens
                )
                if not response.output_text.strip():
                    raise RuntimeError("Foundry returned empty output text")
                turns.extend([AgentTurn("user", actual_input), AgentTurn("assistant", response.output_text)])
        return turns


@contextmanager
def create_evaluation_agent(settings: EvaluationSettings, instructions: str) -> Generator[FoundryAgent, None, None]:
    with ResourceScope() as resources:
        credential = DefaultAzureCredential()
        resources.register_cleanup("Foundry credential", credential.close)
        project = cast(
            EvaluationProject,
            AIProjectClient(endpoint=settings.project_endpoint, credential=credential, allow_preview=True),
        )
        resources.register_cleanup("Foundry project client", project.close)
        name = f"deepeval-{uuid4().hex}"
        agent = project.agents.create_version(
            agent_name=name, definition=PromptAgentDefinition(model=settings.agent_model, instructions=instructions)
        )
        resources.register_cleanup(
            f"agent {name} version {agent.version}", lambda: project.agents.delete(agent_name=name)
        )
        client = project.get_openai_client(agent_name=name, timeout=settings.timeout_seconds, max_retries=1)
        resources.register_cleanup("Foundry OpenAI client", client.close)
        yield FoundryAgent(client=client, name=name, version=agent.version, settings=settings)
