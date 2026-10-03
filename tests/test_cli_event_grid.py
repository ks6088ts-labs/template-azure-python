import json
import runpy
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from azure.core.exceptions import AzureError
from azure.core.messaging import CloudEvent
from azure.eventgrid import EventGridEvent
from click import unstyle
from typer.testing import CliRunner

from scripts.cli_event_grid import (
    DEFAULT_COUNT,
    DEFAULT_DATA,
    DEFAULT_DATA_VERSION,
    DEFAULT_EVENT_TYPE,
    DEFAULT_SOURCE,
    DEFAULT_SUBJECT,
    app,
)

ENDPOINT = "https://example.westus2-1.eventgrid.azure.net/api/events"
COMMANDS = ("publish-event", "publish-events")


@pytest.fixture
def event_grid_clients():
    credential = MagicMock()
    client = MagicMock()
    with (
        patch(
            "template_azure_python.internals.azure._common.DefaultAzureCredential", return_value=credential
        ) as credential_type,
        patch(
            "template_azure_python.internals.azure.event_grid.EventGridPublisherClient", return_value=client
        ) as client_type,
    ):
        yield SimpleNamespace(
            credential=credential,
            credential_type=credential_type,
            client=client,
            client_type=client_type,
        )


def assert_closed(clients: SimpleNamespace) -> None:
    clients.client.close.assert_called_once_with()
    clients.credential.close.assert_called_once_with()


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("schema", ["event-grid", "cloud-event"])
def test_publish_defaults(command: str, schema: str, event_grid_clients: SimpleNamespace):
    result = CliRunner().invoke(app, [command, "--endpoint", ENDPOINT, "--schema", schema])

    assert result.exit_code == 0, result.output
    event_grid_clients.credential_type.assert_called_once_with()
    event_grid_clients.client_type.assert_called_once_with(endpoint=ENDPOINT, credential=event_grid_clients.credential)
    event_grid_clients.client.send.assert_called_once()
    args, kwargs = event_grid_clients.client.send.call_args
    assert not kwargs
    assert len(args) == 1
    if command == "publish-events":
        assert isinstance(args[0], list)
        events = args[0]
        assert len(events) == DEFAULT_COUNT
    else:
        assert not isinstance(args[0], list)
        events = [args[0]]
    for event in events:
        assert event.subject == DEFAULT_SUBJECT
        assert event.data == json.loads(DEFAULT_DATA)
        assert event.id
        if schema == "event-grid":
            assert isinstance(event, EventGridEvent)
            assert event.event_type == DEFAULT_EVENT_TYPE
            assert event.data_version == DEFAULT_DATA_VERSION
        else:
            assert isinstance(event, CloudEvent)
            assert event.type == DEFAULT_EVENT_TYPE
            assert event.source == DEFAULT_SOURCE
            assert event.datacontenttype == "application/json"
    ids = [str(event.id) for event in events]
    assert len(set(ids)) == len(events)
    assert json.loads(result.output) == {"schema": schema, "count": len(events), "ids": ids}
    assert_closed(event_grid_clients)


@pytest.mark.parametrize("command", COMMANDS)
def test_schema_defaults_to_event_grid(command: str, event_grid_clients: SimpleNamespace):
    result = CliRunner().invoke(app, [command, "--endpoint", ENDPOINT])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["schema"] == "event-grid"


@pytest.mark.parametrize("schema", ["event-grid", "cloud-event"])
@pytest.mark.parametrize("count", [1, 4])
def test_custom_options_and_batch_shape(schema: str, count: int, event_grid_clients: SimpleNamespace):
    payload = {"name": "café", "nested": {"count": 2}, "items": [True, None]}
    result = CliRunner().invoke(
        app,
        [
            "publish-events",
            "--endpoint",
            ENDPOINT,
            "--schema",
            schema,
            "--subject",
            "products/42",
            "--source",
            "/inventory",
            "--event-type",
            "Inventory.Updated",
            "--data",
            json.dumps(payload),
            "--data-version",
            "2.0",
            "--count",
            str(count),
        ],
    )

    assert result.exit_code == 0, result.output
    event_grid_clients.client.send.assert_called_once()
    events = event_grid_clients.client.send.call_args.args[0]
    assert isinstance(events, list)
    assert len(events) == count
    for event in events:
        assert event.subject == "products/42"
        assert event.data == payload
        if schema == "cloud-event":
            assert event.source == "/inventory"
            assert event.type == "Inventory.Updated"
        else:
            assert event.event_type == "Inventory.Updated"
            assert event.data_version == "2.0"
    assert_closed(event_grid_clients)


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("explicit_endpoint", [False, True])
def test_endpoint_environment_and_cli_override(
    command: str, explicit_endpoint: bool, event_grid_clients: SimpleNamespace
):
    args = [command]
    if explicit_endpoint:
        args.extend(["--endpoint", ENDPOINT])
    environment_endpoint = "https://environment.eventgrid.azure.net/api/events"
    result = CliRunner().invoke(app, args, env={"AZURE_EVENT_GRID_TOPIC_ENDPOINT": environment_endpoint})

    assert result.exit_code == 0, result.output
    event_grid_clients.client_type.assert_called_once_with(
        endpoint=ENDPOINT if explicit_endpoint else environment_endpoint,
        credential=event_grid_clients.credential,
    )


@pytest.mark.parametrize("command", COMMANDS)
def test_missing_endpoint_before_auth(command: str, event_grid_clients: SimpleNamespace):
    result = CliRunner().invoke(app, [command], env={"AZURE_EVENT_GRID_TOPIC_ENDPOINT": ""})

    assert result.exit_code == 2
    assert "--endpoint" in unstyle(result.output)
    event_grid_clients.credential_type.assert_not_called()
    event_grid_clients.client_type.assert_not_called()


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize(
    "endpoint",
    [
        "http://example.eventgrid.azure.net",
        "not-a-url",
        "https://",
        "https://user@example.eventgrid.azure.net/api/events",
        "https://example.eventgrid.azure.net/api/events?token=value",
        "https://example.eventgrid.azure.net/api/events#fragment",
        "https://[",
        " ",
    ],
)
def test_invalid_endpoint_before_auth(command: str, endpoint: str, event_grid_clients: SimpleNamespace):
    result = CliRunner().invoke(app, [command, "--endpoint", endpoint])

    assert result.exit_code == 2, result.output
    assert "--endpoint" in unstyle(result.output)
    event_grid_clients.credential_type.assert_not_called()
    event_grid_clients.client_type.assert_not_called()


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize(
    "data",
    ["{", "[]", '"text"', "1", "true", "null", " ", '{"value": NaN}', '{"value": Infinity}', '{"value": 1e999}'],
)
def test_invalid_json_before_auth(command: str, data: str, event_grid_clients: SimpleNamespace):
    result = CliRunner().invoke(app, [command, "--endpoint", ENDPOINT, "--data", data])

    assert result.exit_code == 2, result.output
    assert "--data" in unstyle(result.output)
    event_grid_clients.credential_type.assert_not_called()
    event_grid_clients.client_type.assert_not_called()


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("option", ["--subject", "--source", "--event-type", "--data-version"])
def test_blank_names_before_auth(command: str, option: str, event_grid_clients: SimpleNamespace):
    result = CliRunner().invoke(app, [command, "--endpoint", ENDPOINT, option, " "])

    assert result.exit_code == 2, result.output
    assert option in unstyle(result.output)
    event_grid_clients.credential_type.assert_not_called()
    event_grid_clients.client_type.assert_not_called()


@pytest.mark.parametrize(
    "options",
    [["--count", "0"], ["--count", "-1"], ["--count", "text"], ["--schema", "invalid"]],
)
def test_invalid_options_before_auth(options: list[str], event_grid_clients: SimpleNamespace):
    result = CliRunner().invoke(app, ["publish-events", "--endpoint", ENDPOINT, *options])

    assert result.exit_code == 2
    event_grid_clients.credential_type.assert_not_called()
    event_grid_clients.client_type.assert_not_called()


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("option", ["--connection-string", "--key", "--sas-token"])
def test_no_shared_key_options(command: str, option: str, event_grid_clients: SimpleNamespace):
    result = CliRunner().invoke(app, [command, "--endpoint", ENDPOINT, option, "unused"])

    assert result.exit_code == 2
    assert "No such option" in unstyle(result.output)
    event_grid_clients.credential_type.assert_not_called()
    event_grid_clients.client_type.assert_not_called()


@pytest.mark.parametrize("command", COMMANDS)
def test_sdk_failure_closes_resources(command: str, event_grid_clients: SimpleNamespace):
    event_grid_clients.client.send.side_effect = AzureError("publish failed")
    result = CliRunner().invoke(app, [command, "--endpoint", ENDPOINT])

    assert result.exit_code == 1
    assert "publish failed" in result.output
    assert '"ids"' not in result.output
    assert_closed(event_grid_clients)


def test_client_creation_failure_closes_credential(event_grid_clients: SimpleNamespace):
    event_grid_clients.client_type.side_effect = AzureError("client failed")
    result = CliRunner().invoke(app, ["publish-event", "--endpoint", ENDPOINT])

    assert result.exit_code == 1
    assert "client failed" in result.output
    event_grid_clients.credential.close.assert_called_once_with()
    event_grid_clients.client.close.assert_not_called()


def test_credential_failure_is_reported(event_grid_clients: SimpleNamespace):
    event_grid_clients.credential_type.side_effect = AzureError("credential failed")
    result = CliRunner().invoke(app, ["publish-event", "--endpoint", ENDPOINT])

    assert result.exit_code == 1
    assert "credential failed" in result.output
    event_grid_clients.client_type.assert_not_called()


@pytest.mark.parametrize("command", COMMANDS)
def test_client_close_failure_still_closes_credential(command: str, event_grid_clients: SimpleNamespace):
    event_grid_clients.client.close.side_effect = AzureError("close failed")
    result = CliRunner().invoke(app, [command, "--endpoint", ENDPOINT])

    assert result.exit_code == 1
    assert "close failed" in result.output
    assert_closed(event_grid_clients)


@pytest.mark.parametrize("args", [[], ["publish-event"], ["publish-events"]])
def test_help_does_not_authenticate(args: list[str], event_grid_clients: SimpleNamespace):
    result = CliRunner().invoke(app, [*args, "--help"], env={"AZURE_EVENT_GRID_TOPIC_ENDPOINT": ""})

    assert result.exit_code == 0, result.output
    output = unstyle(result.output)
    if args:
        for option in ["--endpoint", "--schema", "--subject", "--source", "--event-type", "--data", "--data-version"]:
            assert option in output
        assert "AZURE_EVENT_GRID_TOPIC_E" in output
        assert "event-grid" in output
        assert "cloud-event" in output
        if args == ["publish-events"]:
            assert "--count" in output
    else:
        assert "publish-event" in output
        assert "publish-events" in output
        assert "AZURE_EVENT_GRID_TOPIC_ENDPOINT" in output
    event_grid_clients.credential_type.assert_not_called()
    event_grid_clients.client_type.assert_not_called()


def test_module_main_preserves_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delitem(sys.modules, "scripts.cli_event_grid", raising=False)
    with patch("dotenv.load_dotenv") as dotenv, patch("typer.Typer.__call__") as invoke:
        runpy.run_module("scripts.cli_event_grid", run_name="__main__")

    dotenv.assert_not_called()
    invoke.assert_called_once_with()
