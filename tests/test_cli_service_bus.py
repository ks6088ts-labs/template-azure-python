import json
import runpy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch
from uuid import UUID

import pytest
from azure.core.exceptions import AzureError
from azure.servicebus import ServiceBusMessage, ServiceBusReceiveMode
from click import unstyle
from typer.testing import CliRunner

from scripts import cli_service_bus
from scripts.cli_service_bus import DEFAULT_MESSAGE, app

NAMESPACE = "example.servicebus.windows.net"
QUEUE = "quickstart"
OPTIONS = ["--fully-qualified-namespace", NAMESPACE, "--queue", QUEUE]
COMMANDS = ["send-message", "send-message-list", "send-message-batch", "receive-messages"]
ENV = {
    "AZURE_SERVICE_BUS_FULLY_QUALIFIED_NAMESPACE": NAMESPACE,
    "AZURE_SERVICE_BUS_QUEUE_NAME": QUEUE,
}


@pytest.fixture
def clients():
    credential = MagicMock()
    client = MagicMock()
    sender = client.get_queue_sender.return_value
    receiver = client.get_queue_receiver.return_value
    receiver.receive_messages.return_value = []
    with (
        patch(
            "template_azure_python.internals.azure._common.DefaultAzureCredential", return_value=credential
        ) as credential_type,
        patch("template_azure_python.internals.azure.service_bus.ServiceBusClient", return_value=client) as client_type,
    ):
        yield SimpleNamespace(
            credential=credential,
            credential_type=credential_type,
            client=client,
            client_type=client_type,
            sender=sender,
            receiver=receiver,
            batch=sender.create_message_batch.return_value,
        )


def assert_closed(clients: SimpleNamespace, command: str) -> None:
    clients.client.close.assert_called_once_with()
    clients.credential.close.assert_called_once_with()
    if command == "receive-messages":
        clients.receiver.close.assert_called_once_with()
        clients.sender.close.assert_not_called()
    else:
        clients.sender.close.assert_called_once_with()
        clients.receiver.close.assert_not_called()


@pytest.mark.parametrize("command", COMMANDS[:3])
@pytest.mark.parametrize("custom", [False, True])
def test_send_shapes_and_defaults(clients: SimpleNamespace, command: str, custom: bool):
    options = ["--message", "hello ☀"] if custom else []
    count = 1 if command == "send-message" else (4 if custom else 3)
    if custom and command != "send-message":
        options += ["--count", str(count)]
    result = CliRunner().invoke(app, [command, *OPTIONS, *options])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"sent": count}
    clients.credential_type.assert_called_once_with()
    clients.client_type.assert_called_once_with(fully_qualified_namespace=NAMESPACE, credential=clients.credential)
    clients.client.get_queue_sender.assert_called_once_with(queue_name=QUEUE)
    clients.sender.send_messages.assert_called_once()
    payload = clients.sender.send_messages.call_args.args[0]
    if command == "send-message-batch":
        assert payload is clients.batch
        clients.sender.create_message_batch.assert_called_once_with()
        messages = [item.args[0] for item in clients.batch.add_message.call_args_list]
    elif command == "send-message-list":
        assert isinstance(payload, list)
        messages = payload
        clients.sender.create_message_batch.assert_not_called()
    else:
        messages = [payload]
        clients.sender.create_message_batch.assert_not_called()
    assert len(messages) == count
    assert all(isinstance(message, ServiceBusMessage) for message in messages)
    assert [str(message) for message in messages] == [("hello ☀" if custom else DEFAULT_MESSAGE)] * count
    assert_closed(clients, command)


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("override", [False, True])
def test_environment_and_explicit_override(clients: SimpleNamespace, command: str, override: bool):
    options = ["--fully-qualified-namespace", "other.servicebus.windows.net", "--queue", "other"] if override else []
    result = CliRunner().invoke(app, [command, *options], env=ENV)

    assert result.exit_code == 0, result.output
    clients.client_type.assert_called_once_with(
        fully_qualified_namespace="other.servicebus.windows.net" if override else NAMESPACE,
        credential=clients.credential,
    )
    resource_factory = (
        clients.client.get_queue_receiver if command == "receive-messages" else clients.client.get_queue_sender
    )
    assert resource_factory.call_args.kwargs["queue_name"] == ("other" if override else QUEUE)
    assert_closed(clients, command)


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize(
    ("envvar", "option"),
    [
        ("AZURE_SERVICE_BUS_FULLY_QUALIFIED_NAMESPACE", "--fully-qualified-namespace"),
        ("AZURE_SERVICE_BUS_QUEUE_NAME", "--queue"),
    ],
)
def test_missing_required_options(clients: SimpleNamespace, command: str, envvar: str, option: str):
    result = CliRunner().invoke(app, [command], env={**ENV, envvar: ""})
    assert result.exit_code == 2
    assert f"Missing option '{option}'" in unstyle(result.output)
    clients.credential_type.assert_not_called()
    clients.client_type.assert_not_called()


@pytest.mark.parametrize("command", ["", *COMMANDS])
def test_help_without_credentials(clients: SimpleNamespace, command: str):
    with patch("typer.rich_utils.MAX_WIDTH", 240):
        result = CliRunner().invoke(
            app,
            [*([command] if command else []), "--help"],
            env={**dict.fromkeys(ENV, ""), "TERM": "xterm-256color"},
            terminal_width=240,
        )
    assert result.exit_code == 0
    if command:
        assert "AZURE_SERVICE_BUS_FULLY_QUALIFIED_NAMESPACE" in unstyle(result.output)
        assert "AZURE_SERVICE_BUS_QUEUE_NAME" in unstyle(result.output)
    else:
        assert all(name in unstyle(result.output) for name in COMMANDS)
    clients.credential_type.assert_not_called()
    clients.client_type.assert_not_called()


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("--fully-qualified-namespace", "https://example.servicebus.windows.net"),
        ("--fully-qualified-namespace", "Endpoint=sb://example;SharedAccessKey=invalid"),
        ("--fully-qualified-namespace", "example.servicebus.windows.net/path"),
        ("--fully-qualified-namespace", " "),
        ("--queue", " "),
    ],
)
def test_invalid_resources_fail_before_clients(clients: SimpleNamespace, command: str, option: str, value: str):
    result = CliRunner().invoke(app, [command, *OPTIONS, option, value])
    assert result.exit_code == 2, result.output
    clients.credential_type.assert_not_called()
    clients.client_type.assert_not_called()


@pytest.mark.parametrize(
    ("command", "option", "value"),
    [
        *[(command, "--count", value) for command in COMMANDS[1:3] for value in ["0", "-1"]],
        *[("receive-messages", "--max-messages", value) for value in ["0", "-1"]],
        *[("receive-messages", "--max-wait-time", value) for value in ["0", "-1", "nan", "inf", "-inf"]],
    ],
)
def test_invalid_limits_fail_before_clients(clients: SimpleNamespace, command: str, option: str, value: str):
    result = CliRunner().invoke(app, [command, *OPTIONS, option, value])
    assert result.exit_code == 2, result.output
    clients.credential_type.assert_not_called()
    clients.client_type.assert_not_called()


@pytest.mark.parametrize("failure_index", [0, 1, 2])
def test_batch_overflow_never_sends_partial_batch(clients: SimpleNamespace, failure_index: int):
    clients.batch.add_message.side_effect = [None] * failure_index + [ValueError("batch full")]
    result = CliRunner().invoke(app, ["send-message-batch", *OPTIONS])
    assert result.exit_code == 1
    assert "Azure Service Bus" in result.stderr
    assert "overflow" in result.stderr
    assert "no messages were sent" in result.stderr
    clients.sender.send_messages.assert_not_called()
    assert_closed(clients, "send-message-batch")


@pytest.mark.parametrize("command", COMMANDS)
def test_sdk_operation_failure_reports_service_and_closes(clients: SimpleNamespace, command: str):
    operation = clients.receiver.receive_messages if command == "receive-messages" else clients.sender.send_messages
    operation.side_effect = AzureError("service unavailable")
    result = CliRunner().invoke(app, [command, *OPTIONS])
    assert result.exit_code == 1
    assert "Azure Service Bus" in result.stderr
    assert "service unavailable" in result.stderr
    assert_closed(clients, command)


@pytest.mark.parametrize("operation", ["create_message_batch", "add_message"])
def test_batch_creation_and_add_sdk_failures_close(clients: SimpleNamespace, operation: str):
    target = clients.sender if operation == "create_message_batch" else clients.batch
    getattr(target, operation).side_effect = AzureError("batch failure")
    result = CliRunner().invoke(app, ["send-message-batch", *OPTIONS])
    assert result.exit_code == 1
    assert "Azure Service Bus" in result.stderr
    clients.sender.send_messages.assert_not_called()
    assert_closed(clients, "send-message-batch")


@pytest.mark.parametrize("command", COMMANDS)
def test_client_construction_failure_closes_credential(clients: SimpleNamespace, command: str):
    clients.client_type.side_effect = AzureError("construction failure")
    result = CliRunner().invoke(app, [command, *OPTIONS])
    assert result.exit_code == 1
    assert "Azure Service Bus" in result.stderr
    clients.credential.close.assert_called_once_with()


@pytest.mark.parametrize("command", ["send-message", "receive-messages"])
def test_child_construction_failure_closes_client_and_credential(clients: SimpleNamespace, command: str):
    factory = clients.client.get_queue_receiver if command == "receive-messages" else clients.client.get_queue_sender
    factory.side_effect = AzureError("link failure")
    result = CliRunner().invoke(app, [command, *OPTIONS])
    assert result.exit_code == 1
    assert "Azure Service Bus" in result.stderr
    clients.client.close.assert_called_once_with()
    clients.credential.close.assert_called_once_with()


def received_message(body: str = "hello") -> MagicMock:
    message = MagicMock()
    message.__str__ = MagicMock(return_value=body)
    message.message_id = "message-1"
    message.correlation_id = None
    message.content_type = "text/plain"
    message.sequence_number = 12
    message.enqueued_time_utc = datetime(2026, 1, 1, tzinfo=timezone.utc)
    message.delivery_count = 1
    message.lock_token = UUID("aaaaaaaa-0000-1111-2222-bbbbbbbbbbbb")
    return message


@pytest.mark.parametrize("count", [0, 2])
@pytest.mark.parametrize("custom", [False, True])
def test_receive_is_bounded_and_displays_before_completing(clients: SimpleNamespace, count: int, custom: bool):
    messages = [received_message(f"hello {index}") for index in range(count)]
    clients.receiver.receive_messages.return_value = messages
    events = MagicMock()
    events.attach_mock(clients.receiver.complete_message, "complete")
    options = ["--max-messages", "2", "--max-wait-time", "0.25"] if custom else []
    with patch("scripts.cli_service_bus.print_json", wraps=cli_service_bus.print_json) as output:
        events.attach_mock(output, "display")
        result = CliRunner().invoke(app, ["receive-messages", *OPTIONS, *options])

    assert result.exit_code == 0, result.output
    clients.client.get_queue_receiver.assert_called_once_with(
        queue_name=QUEUE, receive_mode=ServiceBusReceiveMode.PEEK_LOCK
    )
    clients.receiver.receive_messages.assert_called_once_with(
        max_message_count=2 if custom else 10,
        max_wait_time=0.25 if custom else 5.0,
    )
    clients.receiver.__iter__.assert_not_called()
    assert clients.receiver.complete_message.call_args_list == [call(message) for message in messages]
    assert [event[0] for event in events.mock_calls] == ["display", "complete"] * count + ["display"]
    assert output.call_args_list[-1] == call({"received": count})
    for index, message in enumerate(messages):
        assert output.call_args_list[index].args[0] == {
            "body": f"hello {index}",
            "message_id": message.message_id,
            "correlation_id": None,
            "content_type": "text/plain",
            "sequence_number": 12,
            "enqueued_time_utc": message.enqueued_time_utc,
            "delivery_count": 1,
            "lock_token": message.lock_token,
        }
    if count:
        assert "2026-01-01" in result.output
        assert "aaaaaaaa-0000-1111-2222-bbbbbbbbbbbb" in result.output
    else:
        assert json.loads(result.output) == {"received": 0}
    assert_closed(clients, "receive-messages")


@pytest.mark.parametrize("failure", ["output", "processing", "completion"])
def test_receive_failure_does_not_complete_unprocessed_messages(clients: SimpleNamespace, failure: str):
    first, second, third = received_message("first"), received_message("second"), received_message("third")
    clients.receiver.receive_messages.return_value = [first, second, third]
    if failure == "processing":
        second.__str__ = MagicMock(side_effect=ValueError("invalid body"))
    elif failure == "completion":
        clients.receiver.complete_message.side_effect = [None, AzureError("lock lost")]
    with patch("scripts.cli_service_bus.print_json", wraps=cli_service_bus.print_json) as output:
        if failure == "output":
            output.side_effect = [None, OSError("output failed")]
        result = CliRunner().invoke(app, ["receive-messages", *OPTIONS])

    assert result.exit_code == 1
    expected = [call(first), call(second)] if failure == "completion" else [call(first)]
    assert clients.receiver.complete_message.call_args_list == expected
    assert not any(item == call({"received": 3}) for item in output.call_args_list)
    assert_closed(clients, "receive-messages")


@pytest.mark.parametrize("command", ["send-message", "receive-messages"])
def test_child_close_failure_still_closes_outer_resources(clients: SimpleNamespace, command: str):
    child = clients.receiver if command == "receive-messages" else clients.sender
    child.close.side_effect = AzureError("close failed")
    result = CliRunner().invoke(app, [command, *OPTIONS])
    assert result.exit_code == 1
    assert "Azure Service Bus" in result.stderr
    assert_closed(clients, command)


def test_module_entrypoint_does_not_load_dotenv():
    with patch("dotenv.load_dotenv") as load, patch("typer.Typer.__call__"):
        with pytest.warns(RuntimeWarning, match="found in sys.modules"):
            runpy.run_module("scripts.cli_service_bus", run_name="__main__")
    load.assert_not_called()
