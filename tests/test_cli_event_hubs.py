import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from azure.core.exceptions import AzureError
from azure.eventhub import EventData
from azure.eventhub.aio import EventHubConsumerClient
from click import unstyle
from typer.testing import CliRunner

from scripts.cli_event_hubs import (
    DEFAULT_CONSUMER_GROUP,
    DEFAULT_MAX_EVENTS,
    DEFAULT_MAX_WAIT_TIME,
    DEFAULT_MESSAGES,
    app,
)
from template_azure_python.internals.azure.event_hubs import _receive_bounded

NAMESPACE = "example.servicebus.windows.net"
RESOURCE_ARGS = ["--fully-qualified-namespace", NAMESPACE, "--event-hub", "events"]


@pytest.fixture
def clients():
    credential = MagicMock()
    async_credential = MagicMock()
    async_credential.close = AsyncMock()
    producer = MagicMock()
    consumer = MagicMock()
    consumer.receive = AsyncMock()
    consumer.close = AsyncMock()
    with (
        patch(
            "template_azure_python.internals.azure._common.DefaultAzureCredential", return_value=credential
        ) as credential_type,
        patch(
            "template_azure_python.internals.azure._common.AsyncDefaultAzureCredential", return_value=async_credential
        ) as async_credential_type,
        patch(
            "template_azure_python.internals.azure.event_hubs.EventHubProducerClient", return_value=producer
        ) as producer_type,
        patch(
            "template_azure_python.internals.azure.event_hubs.EventHubConsumerClient", return_value=consumer
        ) as consumer_type,
    ):
        yield SimpleNamespace(
            credential=credential,
            async_credential=async_credential,
            credential_type=credential_type,
            async_credential_type=async_credential_type,
            producer=producer,
            consumer=consumer,
            producer_type=producer_type,
            consumer_type=consumer_type,
        )


def records(output):
    return [json.loads(line) for line in output.splitlines()]


def event(body="hello"):
    return SimpleNamespace(
        body_as_str=lambda: body,
        offset="17",
        sequence_number=3,
        enqueued_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def assert_no_clients(clients):
    clients.credential_type.assert_not_called()
    clients.async_credential_type.assert_not_called()
    clients.producer_type.assert_not_called()
    clients.consumer_type.assert_not_called()


@pytest.mark.parametrize("messages", [None, ["custom one", "custom two"], ["", "世界"]])
def test_send_one_batch_with_exact_messages(clients, messages):
    args = ["send-events", *RESOURCE_ARGS]
    if messages is not None:
        for message in messages:
            args.extend(["--message", message])
    result = CliRunner().invoke(app, args)

    assert result.exit_code == 0, result.output
    expected = list(DEFAULT_MESSAGES) if messages is None else messages
    batch = clients.producer.create_batch.return_value
    assert [call.args[0].body_as_str() for call in batch.add.call_args_list] == expected
    assert all(isinstance(call.args[0], EventData) for call in batch.add.call_args_list)
    clients.producer.create_batch.assert_called_once_with()
    clients.producer.send_batch.assert_called_once_with(batch)
    clients.producer_type.assert_called_once_with(
        fully_qualified_namespace=NAMESPACE, eventhub_name="events", credential=clients.credential
    )
    clients.producer.close.assert_called_once_with()
    clients.credential.close.assert_called_once_with()
    assert records(result.output) == [{"sent": len(expected)}]


@pytest.mark.parametrize("command", ["send-events", "receive-events"])
def test_resource_options_from_environment_and_cli_override(clients, command):
    env = {
        "AZURE_EVENT_HUBS_FULLY_QUALIFIED_NAMESPACE": "environment.servicebus.windows.net",
        "AZURE_EVENT_HUB_NAME": "environment-events",
        "AZURE_EVENT_HUB_CONSUMER_GROUP": "environment-group",
    }
    result = CliRunner().invoke(app, [command], env=env)
    assert result.exit_code == 0, result.output
    factory = clients.producer_type if command == "send-events" else clients.consumer_type
    assert factory.call_args.kwargs["fully_qualified_namespace"] == env["AZURE_EVENT_HUBS_FULLY_QUALIFIED_NAMESPACE"]
    assert factory.call_args.kwargs["eventhub_name"] == "environment-events"
    if command == "receive-events":
        assert factory.call_args.kwargs["consumer_group"] == "environment-group"
    args = [command, *RESOURCE_ARGS]
    if command == "receive-events":
        args.extend(["--consumer-group", "cli-group"])
    result = CliRunner().invoke(app, args, env=env)
    assert result.exit_code == 0, result.output
    assert factory.call_args.kwargs["fully_qualified_namespace"] == NAMESPACE
    assert factory.call_args.kwargs["eventhub_name"] == "events"
    if command == "receive-events":
        assert factory.call_args.kwargs["consumer_group"] == "cli-group"


@pytest.mark.parametrize("command", ["send-events", "receive-events"])
@pytest.mark.parametrize(
    ("args", "missing"),
    [([], "--fully-qualified-namespace"), (["--fully-qualified-namespace", NAMESPACE], "--event-hub")],
)
def test_required_options(clients, command, args, missing):
    result = CliRunner().invoke(
        app,
        [command, *args],
        env={"AZURE_EVENT_HUBS_FULLY_QUALIFIED_NAMESPACE": "", "AZURE_EVENT_HUB_NAME": ""},
    )
    assert result.exit_code == 2
    assert missing in unstyle(result.output)
    assert_no_clients(clients)


@pytest.mark.parametrize("command", ["send-events", "receive-events"])
@pytest.mark.parametrize(
    "namespace",
    [
        "https://example.servicebus.windows.net",
        "example.servicebus.windows.net/path",
        "example.servicebus.windows.net:443",
        "user:password@example.servicebus.windows.net",
        "example.servicebus.windows.net?sig=secret",
        "example.servicebus.windows.net#fragment",
        "localhost",
        "example..net",
        "-bad.example.net",
        " example.servicebus.windows.net",
        "",
    ],
)
def test_namespace_validation_precedes_auth(clients, command, namespace):
    result = CliRunner().invoke(app, [command, "--fully-qualified-namespace", namespace, "--event-hub", "events"])
    assert result.exit_code == 2
    assert_no_clients(clients)


@pytest.mark.parametrize(
    ("command", "option", "value"),
    [
        ("send-events", "--event-hub", " "),
        ("receive-events", "--event-hub", ""),
        ("receive-events", "--consumer-group", " "),
        ("receive-events", "--max-events", "0"),
        ("receive-events", "--max-events", "-1"),
        ("receive-events", "--max-events", "10001"),
        ("receive-events", "--max-events", "1.5"),
        ("receive-events", "--max-wait-time", "0"),
        ("receive-events", "--max-wait-time", "-1"),
        ("receive-events", "--max-wait-time", "nan"),
        ("receive-events", "--max-wait-time", "inf"),
        ("receive-events", "--max-wait-time", "-inf"),
        ("receive-events", "--starting-position", " "),
    ],
)
def test_invalid_options_precede_auth(clients, command, option, value):
    result = CliRunner().invoke(app, [command, *RESOURCE_ARGS, option, value])
    assert result.exit_code == 2
    assert_no_clients(clients)


@pytest.mark.parametrize("command", ["send-events", "receive-events"])
def test_help_without_auth(clients, command, monkeypatch):
    monkeypatch.setattr("typer.rich_utils.MAX_WIDTH", 240)
    result = CliRunner().invoke(
        app, [command, "--help"], env={"COLUMNS": "240", "TERM": "xterm-256color"}, terminal_width=240
    )
    assert result.exit_code == 0, result.output
    assert "AZURE_EVENT_HUBS_FULLY_QUALIFIED_NAMESPACE" in result.output
    assert "AZURE_EVENT_HUB_NAME" in result.output
    if command == "receive-events":
        assert "AZURE_EVENT_HUB_CONSUMER_GROUP" in result.output
        assert "$Default" in result.output
    assert_no_clients(clients)


def test_receive_defaults_and_cleanup(clients):
    result = CliRunner().invoke(app, ["receive-events", *RESOURCE_ARGS])
    assert result.exit_code == 0, result.output
    clients.consumer_type.assert_called_once_with(
        fully_qualified_namespace=NAMESPACE,
        eventhub_name="events",
        consumer_group=DEFAULT_CONSUMER_GROUP,
        credential=clients.async_credential,
    )
    kwargs = clients.consumer.receive.call_args.kwargs
    assert kwargs["starting_position"] == "-1"
    assert kwargs["max_wait_time"] == DEFAULT_MAX_WAIT_TIME
    assert records(result.output) == [{"received": 0}]
    clients.consumer.close.assert_awaited_once_with()
    clients.async_credential.close.assert_awaited_once_with()
    clients.credential_type.assert_not_called()


def test_default_timeout_allows_initial_connection_delay(clients):
    async def receive(**kwargs):
        loop = asyncio.get_running_loop()
        with patch.object(loop, "time", return_value=loop.time() + 10.0):
            await kwargs["on_event"](SimpleNamespace(partition_id="0"), event())

    clients.consumer.receive.side_effect = receive
    result = CliRunner().invoke(app, ["receive-events", *RESOURCE_ARGS, "--max-events", "1"])

    assert result.exit_code == 0, result.output
    output = records(result.output)
    assert output[0]["body"] == "hello"
    assert output[-1] == {"received": 1}


@pytest.mark.parametrize("limit", [1, 3, DEFAULT_MAX_EVENTS])
def test_receive_total_limit_across_partitions_and_metadata(clients, limit):
    cancelled = []
    contexts = [MagicMock(partition_id=str(partition)) for partition in range(3)]

    async def receive(**kwargs):
        try:
            for index in range(limit + 5):
                await kwargs["on_event"](contexts[index % 3], event(f"body {index}"))
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)

    clients.consumer.receive.side_effect = receive
    result = CliRunner().invoke(
        app,
        ["receive-events", *RESOURCE_ARGS, "--max-events", str(limit), "--starting-position", "@latest"],
    )
    assert result.exit_code == 0, result.output
    output = records(result.output)
    assert len(output) == limit + 1
    assert output[0] == {
        "body": "body 0",
        "partition_id": "0",
        "offset": "17",
        "sequence_number": 3,
        "enqueued_time": "2026-01-01T00:00:00+00:00",
    }
    assert output[-1] == {"received": limit}
    assert clients.consumer.receive.call_args.kwargs["starting_position"] == "@latest"
    for context in contexts:
        context.update_checkpoint.assert_not_called()
    assert cancelled == [True]
    clients.consumer.close.assert_awaited_once_with()
    clients.async_credential.close.assert_awaited_once_with()


@pytest.mark.parametrize("empty_callbacks", [False, True])
def test_global_idle_deadline_even_without_callbacks(clients, empty_callbacks):
    cancelled = []

    async def receive(**kwargs):
        try:
            while True:
                if empty_callbacks:
                    await kwargs["on_event"](SimpleNamespace(partition_id="0"), None)
                await asyncio.sleep(0.001)
        finally:
            cancelled.append(True)

    clients.consumer.receive.side_effect = receive
    result = CliRunner().invoke(app, ["receive-events", *RESOURCE_ARGS, "--max-wait-time", "0.015"])
    assert result.exit_code == 0, result.output
    assert records(result.output) == [{"received": 0}]
    assert cancelled == [True]
    clients.consumer.close.assert_awaited_once_with()
    clients.async_credential.close.assert_awaited_once_with()


def test_idle_timeout_resets_on_actual_events(clients):
    async def receive(**kwargs):
        for index in range(4):
            await kwargs["on_event"](SimpleNamespace(partition_id=str(index % 2)), event(str(index)))
            await asyncio.sleep(0.02)
        await asyncio.Event().wait()

    clients.consumer.receive.side_effect = receive
    result = CliRunner().invoke(app, ["receive-events", *RESOURCE_ARGS, "--max-wait-time", "0.05"])
    assert result.exit_code == 0, result.output
    assert records(result.output)[-1] == {"received": 4}


@pytest.mark.parametrize("callback_error", [False, True])
def test_receive_errors_propagate_and_cancel_worker(clients, callback_error):
    cancelled = []

    async def receive(**kwargs):
        try:
            error = AzureError("receive failed")
            if callback_error:
                await kwargs["on_error"](None, error)
                await asyncio.Event().wait()
            raise error
        finally:
            cancelled.append(True)

    clients.consumer.receive.side_effect = receive
    result = CliRunner().invoke(app, ["receive-events", *RESOURCE_ARGS])
    assert result.exit_code == 1
    assert "Event Hubs operation failed: receive failed" in result.stderr
    assert not result.stdout
    assert cancelled == [True]
    clients.consumer.close.assert_awaited_once_with()
    clients.async_credential.close.assert_awaited_once_with()


def test_metadata_failure_is_not_swallowed(clients):
    async def receive(**kwargs):
        invalid = event()
        invalid.body_as_str = MagicMock(side_effect=ValueError("invalid body"))
        await kwargs["on_event"](SimpleNamespace(partition_id="0"), invalid)
        await asyncio.Event().wait()

    clients.consumer.receive.side_effect = receive
    result = CliRunner().invoke(app, ["receive-events", *RESOURCE_ARGS])
    assert result.exit_code == 1
    assert isinstance(result.exception, ValueError)
    assert str(result.exception) == "invalid body"
    clients.consumer.close.assert_awaited_once_with()
    clients.async_credential.close.assert_awaited_once_with()


@pytest.mark.parametrize("stage", ["create_batch", "send_batch", "close"])
def test_producer_errors_cleanup(clients, stage):
    getattr(clients.producer, stage).side_effect = AzureError("send failed")
    result = CliRunner().invoke(app, ["send-events", *RESOURCE_ARGS])
    assert result.exit_code == 1
    assert "Event Hubs operation failed: send failed" in result.stderr
    clients.producer.close.assert_called_once_with()
    clients.credential.close.assert_called_once_with()


def test_batch_overflow_does_not_send_partial_batch(clients):
    clients.producer.create_batch.return_value.add.side_effect = ValueError("too large")
    result = CliRunner().invoke(app, ["send-events", *RESOURCE_ARGS])
    assert result.exit_code == 2
    assert "one Event Hubs batch" in unstyle(result.output)
    clients.producer.send_batch.assert_not_called()
    clients.producer.close.assert_called_once_with()
    clients.credential.close.assert_called_once_with()


@pytest.mark.parametrize("command", ["send-events", "receive-events"])
def test_client_constructor_failure_closes_credential(clients, command):
    factory = clients.producer_type if command == "send-events" else clients.consumer_type
    factory.side_effect = AzureError("construction failed")
    result = CliRunner().invoke(app, [command, *RESOURCE_ARGS])
    assert result.exit_code == 1
    assert "construction failed" in result.stderr
    if command == "send-events":
        clients.credential.close.assert_called_once_with()
    else:
        clients.async_credential.close.assert_awaited_once_with()


def test_consumer_close_failure_still_closes_credential(clients):
    clients.consumer.close.side_effect = AzureError("close failed")
    result = CliRunner().invoke(app, ["receive-events", *RESOURCE_ARGS])
    assert result.exit_code == 1
    assert "close failed" in result.stderr
    clients.async_credential.close.assert_awaited_once_with()


@pytest.mark.parametrize("discovery", ["empty", "blocked", "error"])
def test_real_sdk_discovery_is_bounded_and_leaves_no_tasks(discovery):
    async def run():
        credential = MagicMock()
        consumer = EventHubConsumerClient(
            fully_qualified_namespace=NAMESPACE,
            eventhub_name="events",
            consumer_group=DEFAULT_CONSUMER_GROUP,
            credential=credential,
        )
        pending_before = asyncio.all_tasks()

        async def get_partition_ids():
            if discovery == "blocked":
                await asyncio.Event().wait()
            if discovery == "error":
                raise AzureError("discovery failed")
            return []

        with patch.object(consumer, "get_partition_ids", side_effect=get_partition_ids):
            try:
                operation = _receive_bounded(consumer, 100, 0.015, "-1", lambda _record: None)
                if discovery == "error":
                    with pytest.raises(AzureError, match="discovery failed"):
                        await asyncio.wait_for(operation, timeout=1)
                else:
                    assert await asyncio.wait_for(operation, timeout=1) == 0
            finally:
                await consumer.close()
        assert asyncio.all_tasks() == pending_before

    asyncio.run(run())


@pytest.mark.parametrize("outcome", ["idle", "limit", "error"])
def test_real_sdk_partition_shutdown_cancels_load_balancing_sleep(outcome):
    async def run():
        consumer = EventHubConsumerClient(
            fully_qualified_namespace=NAMESPACE,
            eventhub_name="events",
            consumer_group=DEFAULT_CONSUMER_GROUP,
            credential=MagicMock(),
        )
        partition_consumer = MagicMock()
        partition_consumer.close = AsyncMock()
        pending_before = asyncio.all_tasks()

        def create_consumer(_group, _partition_id, _position, on_event, **_kwargs):
            async def receive(*_args):
                if outcome == "limit":
                    await on_event(event())
                elif outcome == "error":
                    raise AzureError("partition failed")
                await asyncio.Event().wait()

            partition_consumer.receive = AsyncMock(side_effect=receive)
            return partition_consumer

        with (
            patch.object(consumer, "get_partition_ids", new=AsyncMock(return_value=["0"])),
            patch.object(consumer, "_create_consumer", side_effect=create_consumer),
        ):
            try:
                operation = _receive_bounded(consumer, 1, 0.015, "-1", lambda _record: None)
                if outcome == "error":
                    with pytest.raises(AzureError, match="partition failed"):
                        await asyncio.wait_for(operation, timeout=2)
                else:
                    assert await asyncio.wait_for(operation, timeout=2) == (1 if outcome == "limit" else 0)
            finally:
                await consumer.close()
        partition_consumer.close.assert_awaited_once_with()
        await asyncio.sleep(0)
        assert asyncio.all_tasks() == pending_before

    asyncio.run(run())
