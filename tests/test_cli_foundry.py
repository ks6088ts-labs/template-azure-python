from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest
from click import unstyle
from typer.testing import CliRunner

from scripts.cli_foundry import (
    DEFAULT_AGENT_NAME,
    DEFAULT_FOLLOW_UP_PROMPT,
    DEFAULT_INSTRUCTIONS,
    DEFAULT_MODEL,
    DEFAULT_PROMPT,
    app,
)

ENDPOINT = "https://example.services.ai.azure.com/api/projects/example"


@pytest.fixture
def project_client():
    project = MagicMock()
    with (
        patch("scripts.cli_foundry.DefaultAzureCredential") as credential_type,
        patch("scripts.cli_foundry.AIProjectClient", return_value=project) as project_type,
    ):
        yield project

    credential_type.assert_called()
    project_type.assert_called_once_with(
        endpoint=ENDPOINT,
        credential=credential_type.return_value,
    )


def test_chat_model_uses_cli_options(project_client: MagicMock):
    project_client.get_openai_client.return_value.responses.create.return_value.output_text = "Paris"

    result = CliRunner().invoke(
        app,
        [
            "chat-model",
            "--endpoint",
            ENDPOINT,
            "--model",
            "custom-model",
            "--prompt",
            "Custom question",
        ],
    )

    assert result.exit_code == 0, result.output
    assert result.output == "Paris\n"
    project_client.get_openai_client.assert_called_once_with()
    project_client.get_openai_client.return_value.responses.create.assert_called_once_with(
        model="custom-model",
        input="Custom question",
    )


def test_chat_model_reads_endpoint_from_environment(project_client: MagicMock):
    project_client.get_openai_client.return_value.responses.create.return_value.output_text = "Paris"

    result = CliRunner().invoke(
        app,
        ["chat-model"],
        env={"FOUNDRY_PROJECT_ENDPOINT": ENDPOINT},
    )

    assert result.exit_code == 0, result.output
    project_client.get_openai_client.return_value.responses.create.assert_called_once_with(
        model=DEFAULT_MODEL,
        input=DEFAULT_PROMPT,
    )


def test_create_agent_uses_cli_options(project_client: MagicMock):
    project_client.agents.create_version.return_value = SimpleNamespace(
        id="agent-id",
        name="CustomAgent",
        version="7",
    )

    with patch("scripts.cli_foundry.PromptAgentDefinition") as definition_type:
        result = CliRunner().invoke(
            app,
            [
                "create-agent",
                "--endpoint",
                ENDPOINT,
                "--agent-name",
                "CustomAgent",
                "--model",
                "custom-model",
                "--instructions",
                "Custom instructions",
            ],
        )

    assert result.exit_code == 0, result.output
    assert "Agent created (id: agent-id, name: CustomAgent, version: 7)" in result.output
    definition_type.assert_called_once_with(
        model="custom-model",
        instructions="Custom instructions",
    )
    project_client.agents.create_version.assert_called_once_with(
        agent_name="CustomAgent",
        definition=definition_type.return_value,
    )


def test_chat_agent_runs_two_turn_conversation(project_client: MagicMock):
    openai = project_client.get_openai_client.return_value
    openai.conversations.create.return_value.id = "conversation-id"
    openai.responses.create.side_effect = [
        SimpleNamespace(output_text="First answer"),
        SimpleNamespace(output_text="Follow-up answer"),
    ]

    with patch("scripts.cli_foundry.PromptAgentDefinition") as definition_type:
        result = CliRunner().invoke(
            app,
            [
                "chat-agent",
                "--endpoint",
                ENDPOINT,
                "--agent-name",
                "CustomAgent",
                "--model",
                "custom-model",
                "--instructions",
                "Custom instructions",
                "--prompt",
                "First question",
                "--follow-up-prompt",
                "Follow-up question",
            ],
        )

    assert result.exit_code == 0, result.output
    assert result.output == "First answer\nFollow-up answer\n"
    definition_type.assert_called_once_with(
        model="custom-model",
        instructions="Custom instructions",
    )
    project_client.agents.create_version.assert_called_once_with(
        agent_name="CustomAgent",
        definition=definition_type.return_value,
    )
    project_client.get_openai_client.assert_called_once_with(agent_name="CustomAgent")
    openai.conversations.create.assert_called_once_with()
    assert openai.responses.create.call_args_list == [
        call(conversation="conversation-id", input="First question"),
        call(conversation="conversation-id", input="Follow-up question"),
    ]


def test_chat_agent_uses_tutorial_defaults(project_client: MagicMock):
    openai = project_client.get_openai_client.return_value
    openai.conversations.create.return_value.id = "conversation-id"
    openai.responses.create.side_effect = [
        SimpleNamespace(output_text="First answer"),
        SimpleNamespace(output_text="Follow-up answer"),
    ]

    with patch("scripts.cli_foundry.PromptAgentDefinition") as definition_type:
        result = CliRunner().invoke(app, ["chat-agent", "--endpoint", ENDPOINT])

    assert result.exit_code == 0, result.output
    definition_type.assert_called_once_with(
        model=DEFAULT_MODEL,
        instructions=DEFAULT_INSTRUCTIONS,
    )
    project_client.agents.create_version.assert_called_once_with(
        agent_name=DEFAULT_AGENT_NAME,
        definition=definition_type.return_value,
    )
    assert openai.responses.create.call_args_list == [
        call(conversation="conversation-id", input=DEFAULT_PROMPT),
        call(conversation="conversation-id", input=DEFAULT_FOLLOW_UP_PROMPT),
    ]


def test_chat_model_requires_endpoint():
    result = CliRunner().invoke(
        app,
        ["chat-model"],
        env={"FOUNDRY_PROJECT_ENDPOINT": ""},
    )

    assert result.exit_code == 2
    assert "Missing option '--endpoint'" in unstyle(result.output)


def test_chat_model_rejects_invalid_endpoint():
    with (
        patch("scripts.cli_foundry.DefaultAzureCredential") as credential_type,
        patch("scripts.cli_foundry.AIProjectClient") as project_type,
    ):
        result = CliRunner().invoke(app, ["chat-model", "--endpoint", "https://example.com"])

    assert result.exit_code == 2
    assert "must be an HTTPS Foundry project URL" in result.output
    credential_type.assert_not_called()
    project_type.assert_not_called()


def test_chat_model_reports_empty_response(project_client: MagicMock):
    project_client.get_openai_client.return_value.responses.create.return_value.output_text = "  "

    result = CliRunner().invoke(app, ["chat-model", "--endpoint", ENDPOINT])

    assert result.exit_code == 1
    assert "Error: Model response output text was empty." in result.output


@pytest.mark.parametrize("command", ["chat-model", "create-agent", "chat-agent"])
def test_command_help_describes_endpoint_environment_variable(command: str):
    result = CliRunner().invoke(app, [command, "--help"], terminal_width=240)

    assert result.exit_code == 0, result.output
    assert "FOUNDRY_PROJECT_ENDPOINT" in result.output
    assert "/api/projects/" in result.output
