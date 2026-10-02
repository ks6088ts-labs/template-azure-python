import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from azure.core.exceptions import AzureError
from azure.storage.queue import QueueMessage
from click import unstyle
from typer.testing import CliRunner

from scripts import _azure_messaging as helper
from scripts import cli_queue_storage as cli

ENDPOINT = "https://example.queue.core.windows.net"
QUEUE = "quickstart"
RESOURCE_ARGS = ["--endpoint", ENDPOINT, "--queue", QUEUE]
MESSAGE_ARGS = ["--message-id", "message-id", "--pop-receipt", "receipt"]
COMMANDS = [
    ("create-queue", []),
    ("send-message", []),
    ("peek-messages", []),
    ("update-message", [*MESSAGE_ARGS, "--message", "updated"]),
    ("get-queue-length", []),
    ("receive-messages", []),
    ("delete-message", MESSAGE_ARGS),
    ("delete-queue", ["--yes"]),
]


@pytest.fixture
def clients(monkeypatch):
    credential = MagicMock()
    client = MagicMock()
    credential_type = MagicMock(return_value=credential)
    client_type = MagicMock(return_value=client)
    monkeypatch.setattr(helper, "DefaultAzureCredential", credential_type)
    monkeypatch.setattr(cli, "QueueClient", client_type)
    monkeypatch.delenv("AZURE_QUEUE_STORAGE_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_QUEUE_STORAGE_QUEUE_NAME", raising=False)
    client.send_message.return_value = QueueMessage(content=cli.DEFAULT_MESSAGE, id="message-id", pop_receipt="receipt")
    client.update_message.return_value = QueueMessage(content="updated", id="message-id", pop_receipt="new-receipt")
    client.get_queue_properties.return_value = SimpleNamespace(approximate_message_count=42)
    return SimpleNamespace(
        credential=credential, client=client, credential_type=credential_type, client_type=client_type
    )


def invoke(command, *args, **kwargs):
    return CliRunner().invoke(cli.app, [command, *RESOURCE_ARGS, *args], **kwargs)


def assert_closed(clients):
    clients.credential_type.assert_called_once_with()
    clients.client_type.assert_called_once_with(account_url=ENDPOINT, queue_name=QUEUE, credential=clients.credential)
    clients.client.close.assert_called_once_with()
    clients.credential.close.assert_called_once_with()


def assert_no_clients(clients):
    clients.credential_type.assert_not_called()
    clients.client_type.assert_not_called()


@pytest.mark.parametrize(
    ("command", "args", "method", "expected_args", "expected"),
    [
        ("create-queue", [], "create_queue", {}, {"queue": QUEUE, "created": True}),
        (
            "send-message",
            [],
            "send_message",
            {"content": cli.DEFAULT_MESSAGE, "visibility_timeout": 0},
            {"content": cli.DEFAULT_MESSAGE, "id": "message-id", "pop_receipt": "receipt"},
        ),
        (
            "update-message",
            [*MESSAGE_ARGS, "--message", "updated"],
            "update_message",
            {"message": "message-id", "pop_receipt": "receipt", "content": "updated", "visibility_timeout": 0},
            {"content": "updated", "id": "message-id", "pop_receipt": "new-receipt"},
        ),
        (
            "get-queue-length",
            [],
            "get_queue_properties",
            {},
            {"queue": QUEUE, "approximate_message_count": 42},
        ),
        (
            "delete-message",
            MESSAGE_ARGS,
            "delete_message",
            {"message": "message-id", "pop_receipt": "receipt"},
            {"queue": QUEUE, "id": "message-id", "deleted": True},
        ),
        ("delete-queue", ["--yes"], "delete_queue", {}, {"queue": QUEUE, "deleted": True}),
    ],
)
def test_operations(clients, command, args, method, expected_args, expected):
    result = invoke(command, *args)
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == expected
    getattr(clients.client, method).assert_called_once_with(**expected_args)
    assert_closed(clients)


@pytest.mark.parametrize("command", ["send-message", "update-message"])
@pytest.mark.parametrize("timeout", [0, 604800])
def test_send_update_custom_content_and_visibility(clients, command, timeout):
    args = MESSAGE_ARGS if command == "update-message" else []
    result = invoke(command, *args, "--message", "hello 🌍", "--visibility-timeout", str(timeout))
    assert result.exit_code == 0, result.output
    expected = {"content": "hello 🌍", "visibility_timeout": timeout}
    if command == "update-message":
        expected.update(message="message-id", pop_receipt="receipt")
    getattr(clients.client, command.replace("-", "_")).assert_called_once_with(**expected)
    assert_closed(clients)


@pytest.mark.parametrize("command", ["peek-messages", "receive-messages"])
@pytest.mark.parametrize("limit", [1, 2, 32])
def test_read_messages_metadata_and_total_limit(clients, command, limit):
    date = datetime(2026, 1, 1, tzinfo=timezone.utc)
    message = QueueMessage(
        id=UUID("aaaaaaaa-0000-1111-2222-bbbbbbbbbbbb"),
        content="hello 🌍",
        inserted_on=date,
        expires_on=date,
        dequeue_count=2,
        pop_receipt="receipt" if command == "receive-messages" else None,
        next_visible_on=date if command == "receive-messages" else None,
    )
    method = getattr(clients.client, command.replace("-", "_"))
    messages = iter([message] * (limit + 3))
    method.return_value = messages if command == "receive-messages" else [message] * limit
    result = invoke(command, "--max-messages", str(limit))
    assert result.exit_code == 0, result.output
    expected = {
        "id": str(message.id),
        "content": message.content,
        "inserted_on": date.isoformat(),
        "expires_on": date.isoformat(),
        "dequeue_count": 2,
    }
    if command == "receive-messages":
        expected.update(pop_receipt="receipt", next_visible_on=date.isoformat())
        method.assert_called_once_with(messages_per_page=limit, max_messages=limit, visibility_timeout=30)
        assert len(list(messages)) == 3
    else:
        method.assert_called_once_with(max_messages=limit)
    assert json.loads(result.output) == [expected] * limit
    clients.client.delete_message.assert_not_called()
    clients.client.update_message.assert_not_called()
    assert_closed(clients)


@pytest.mark.parametrize("timeout", [1, 604800])
def test_receive_visibility_boundaries(clients, timeout):
    clients.client.receive_messages.return_value = iter([])
    result = invoke("receive-messages", "--visibility-timeout", str(timeout))
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == []
    clients.client.receive_messages.assert_called_once_with(
        messages_per_page=1, max_messages=1, visibility_timeout=timeout
    )
    assert_closed(clients)


@pytest.mark.parametrize(("command", "args"), COMMANDS)
def test_environment_and_explicit_overrides(clients, command, args):
    result = CliRunner().invoke(
        cli.app,
        [command, *args],
        env={"AZURE_QUEUE_STORAGE_ENDPOINT": ENDPOINT, "AZURE_QUEUE_STORAGE_QUEUE_NAME": QUEUE},
    )
    assert result.exit_code == 0, result.output
    assert_closed(clients)
    clients.client_type.reset_mock()
    result = invoke(
        command,
        *args,
        env={
            "AZURE_QUEUE_STORAGE_ENDPOINT": "https://other.queue.core.windows.net",
            "AZURE_QUEUE_STORAGE_QUEUE_NAME": "other-queue",
        },
    )
    assert result.exit_code == 0, result.output
    clients.client_type.assert_called_once_with(account_url=ENDPOINT, queue_name=QUEUE, credential=clients.credential)


@pytest.mark.parametrize(("command", "args"), COMMANDS)
@pytest.mark.parametrize("missing", ["--endpoint", "--queue"])
def test_required_resources(clients, command, args, missing):
    resources = ["--queue", QUEUE] if missing == "--endpoint" else ["--endpoint", ENDPOINT]
    result = CliRunner().invoke(cli.app, [command, *args, *resources])
    assert result.exit_code == 2
    assert f"Missing option '{missing}'" in unstyle(result.output)
    assert_no_clients(clients)


@pytest.mark.parametrize(("command", "args"), COMMANDS)
@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("--endpoint", "http://example.queue.core.windows.net"),
        ("--endpoint", "not-a-url"),
        ("--endpoint", "https://example.queue.core.windows.net/path"),
        ("--endpoint", "https://user@example.queue.core.windows.net"),
        ("--endpoint", "https://example.queue.core.windows.net?sig=secret"),
        ("--endpoint", "https://example.queue.core.windows.net#fragment"),
        ("--endpoint", "https://[broken"),
        ("--queue", ""),
        ("--queue", "   "),
    ],
)
def test_invalid_resources_before_auth(clients, command, args, option, value):
    result = invoke(command, *args, option, value)
    assert result.exit_code == 2, result.output
    assert option in unstyle(result.output)
    assert_no_clients(clients)


@pytest.mark.parametrize(
    ("command", "args", "option", "values"),
    [
        ("send-message", [], "--visibility-timeout", [-1, 604801]),
        ("update-message", [*MESSAGE_ARGS, "--message", "updated"], "--visibility-timeout", [-1, 604801]),
        ("receive-messages", [], "--visibility-timeout", [0, -1, 604801]),
        ("receive-messages", [], "--max-messages", [0, -1, 33]),
        ("peek-messages", [], "--max-messages", [0, -1, 33]),
    ],
)
def test_invalid_ranges_before_auth(clients, command, args, option, values):
    for value in values:
        result = invoke(command, *args, option, str(value))
        assert result.exit_code == 2, result.output
        assert_no_clients(clients)


@pytest.mark.parametrize("command", ["update-message", "delete-message"])
@pytest.mark.parametrize("option", ["--message-id", "--pop-receipt"])
@pytest.mark.parametrize("value", ["", "   "])
def test_blank_message_identifiers(clients, command, option, value):
    args = ["--message", "updated"] if command == "update-message" else []
    result = invoke(command, *MESSAGE_ARGS, *args, option, value)
    assert result.exit_code == 2, result.output
    assert option in unstyle(result.output)
    assert_no_clients(clients)


@pytest.mark.parametrize(
    ("command", "missing"),
    [
        ("update-message", "--message"),
        ("update-message", "--message-id"),
        ("update-message", "--pop-receipt"),
        ("delete-message", "--message-id"),
        ("delete-message", "--pop-receipt"),
    ],
)
def test_required_message_options(clients, command, missing):
    values = {"--message-id": "message-id", "--pop-receipt": "receipt"}
    if command == "update-message":
        values["--message"] = "updated"
    args = [part for option, value in values.items() if option != missing for part in (option, value)]
    result = invoke(command, *args)
    assert result.exit_code == 2
    assert f"Missing option '{missing}'" in unstyle(result.output)
    assert_no_clients(clients)


def test_rejected_confirmation_has_no_side_effects(clients):
    with (
        patch("typer.testing._NamedTextIOWrapper.isatty", return_value=True),
        patch.object(helper.typer, "confirm", return_value=False),
    ):
        result = invoke("delete-queue")
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"queue": QUEUE, "cancelled": True}
    assert_no_clients(clients)


def test_accepted_interactive_confirmation(clients):
    with (
        patch("typer.testing._NamedTextIOWrapper.isatty", return_value=True),
        patch.object(helper.typer, "confirm", return_value=True) as confirm,
    ):
        result = invoke("delete-queue")
    assert result.exit_code == 0, result.output
    assert confirm.call_args.kwargs["default"] is False
    assert QUEUE in confirm.call_args.args[0]
    clients.client.delete_queue.assert_called_once_with()
    assert_closed(clients)


def test_yes_bypasses_confirmation(clients):
    with patch.object(helper.typer, "confirm") as confirm:
        result = invoke("delete-queue", "--yes")
    assert result.exit_code == 0, result.output
    confirm.assert_not_called()
    assert_closed(clients)


def test_noninteractive_delete_requires_yes(clients):
    with (
        patch("typer.testing._NamedTextIOWrapper.isatty", return_value=False),
        patch.object(helper.typer, "confirm") as confirm,
    ):
        result = invoke("delete-queue")
    assert result.exit_code == 2, result.output
    assert "--yes" in unstyle(result.output)
    confirm.assert_not_called()
    assert_no_clients(clients)


def test_delete_validates_before_confirmation(clients):
    with patch.object(cli, "confirm_delete") as confirm:
        result = invoke("delete-queue", "--queue", " ")
    assert result.exit_code == 2
    confirm.assert_not_called()
    assert_no_clients(clients)


@pytest.mark.parametrize(("command", "args"), COMMANDS)
def test_sdk_failure_closes_resources(clients, command, args):
    method = "get_queue_properties" if command == "get-queue-length" else command.replace("-", "_")
    getattr(clients.client, method).side_effect = AzureError("operation failed")
    result = invoke(command, *args)
    assert result.exit_code == 1
    assert "Azure Queue Storage" in result.stderr
    assert "operation failed" in result.stderr
    assert result.stdout == ""
    assert_closed(clients)


def test_receive_iteration_failure_closes_resources(clients):
    def messages():
        yield QueueMessage(content="first")
        raise AzureError("paging failed")

    clients.client.receive_messages.return_value = messages()
    result = invoke("receive-messages", "--max-messages", "2")
    assert result.exit_code == 1
    assert "paging failed" in result.stderr
    assert result.stdout == ""
    assert_closed(clients)


@pytest.mark.parametrize("constructor", ["credential_type", "client_type"])
def test_constructor_failure_cleanup(clients, constructor):
    getattr(clients, constructor).side_effect = AzureError("constructor failed")
    result = invoke("create-queue")
    assert result.exit_code == 1
    assert "Azure Queue Storage" in result.stderr
    assert "constructor failed" in result.stderr
    clients.client.close.assert_not_called()
    if constructor == "client_type":
        clients.credential.close.assert_called_once_with()
    else:
        clients.client_type.assert_not_called()
        clients.credential.close.assert_not_called()


@pytest.mark.parametrize(("command", "_args"), COMMANDS)
def test_command_help_without_auth(clients, command, _args):
    result = CliRunner().invoke(cli.app, [command, "--help"], env={"COLUMNS": "240", "TERM": "xterm"})
    assert result.exit_code == 0, result.output
    output = unstyle(result.output)
    assert "--endpoint" in output
    assert "--queue" in output
    assert "AZURE_QUEUE_STORAGE_ENDPOINT" in output
    assert "AZURE_QUEUE_STORAGE_QUEUE_NAME" in output
    assert_no_clients(clients)


def test_root_help_without_auth(clients):
    result = CliRunner().invoke(cli.app, ["--help"])
    assert result.exit_code == 0, result.output
    for command, _args in COMMANDS:
        assert command in unstyle(result.output)
    assert_no_clients(clients)
