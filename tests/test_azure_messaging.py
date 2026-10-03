import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
import typer
from azure.core.exceptions import AzureError

from scripts import _cli as cli
from template_azure_python.internals.azure import _common as messaging


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://example.com",
        "https://",
        "https://" + "user@example.com",
        "https://example.com?sig=example",
        "https://example.com?",
        "https://example.com#fragment",
        "https://example.com:invalid",
        "https://example.com:80",
        "https://example.com/queue",
        "https://bad host.example.com",
        "https://example.com\n",
        "https://example.com/\x00",
        "https://example.com\\other",
        "https://[bad",
        "https://-invalid.example.com",
    ],
)
def test_invalid_endpoint(endpoint):
    with pytest.raises(messaging.InputError):
        messaging.validate_endpoint(endpoint)


def test_valid_endpoints():
    assert messaging.validate_endpoint("https://account.queue.core.windows.net:443/")
    assert messaging.validate_endpoint("https://topic.eventgrid.azure.net/api/events", allow_path=True)


@pytest.mark.parametrize(
    "namespace",
    ["", "   ", "namespace", "sb://example.com", "example.com/", "example.com:443", "user@example.com", "bad_.com"],
)
def test_invalid_namespace(namespace):
    with pytest.raises(messaging.InputError):
        messaging.validate_namespace(namespace)


def test_valid_namespace():
    assert messaging.validate_namespace("example.servicebus.windows.net") == "example.servicebus.windows.net"


@pytest.mark.parametrize("value", ["", "  ", "\t"])
def test_invalid_name(value):
    with pytest.raises(messaging.InputError):
        messaging.validate_name(value, "--queue")


@pytest.mark.parametrize("value", ["{", "[]", "null", "1", '{"value": NaN}', '{"value": Infinity}', '{"value": 1e999}'])
def test_invalid_json(value):
    with pytest.raises(messaging.InputError):
        messaging.validate_json_object(value)


def test_json_object_and_output(capsys):
    value = messaging.validate_json_object('{"message": "こんにちは"}')
    value["time"] = datetime(2026, 1, 1, tzinfo=timezone.utc)
    value["id"] = UUID(int=0)
    cli.print_json(value)
    result = json.loads(capsys.readouterr().out)
    assert result == {
        "message": "こんにちは",
        "time": "2026-01-01T00:00:00+00:00",
        "id": "00000000-0000-0000-0000-000000000000",
    }


@pytest.mark.parametrize("failure", ["none", "credential", "factory", "operation", "close"])
def test_managed_client_closes_resources(monkeypatch, capsys, failure):
    credential = MagicMock()
    credential_factory = MagicMock(return_value=credential)
    monkeypatch.setattr(messaging, "DefaultAzureCredential", credential_factory)
    client = MagicMock()
    factory = MagicMock(return_value=client)
    if failure == "credential":
        credential_factory.side_effect = AzureError("credential failed")
    if failure == "factory":
        factory.side_effect = AzureError("client failed")
    if failure == "close":
        client.close.side_effect = AzureError("close failed")

    def operate():
        with messaging.managed_client("Test service", factory) as actual:
            assert actual is client
            if failure == "operation":
                raise AzureError("operation failed")

    if failure == "none":
        operate()
    else:
        with pytest.raises(messaging.OperationError) as error:
            operate()
        assert "Test service operation failed" in str(error.value)
        assert not capsys.readouterr().err
    if failure != "credential":
        credential.close.assert_called_once()
        factory.assert_called_once_with(credential)
    if failure not in ("credential", "factory"):
        client.close.assert_called_once()


def test_noninteractive_delete_requires_yes(monkeypatch):
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    with pytest.raises(typer.BadParameter):
        cli.confirm_delete("scratch-queue", False)
    assert cli.confirm_delete("scratch-queue", True)


@pytest.mark.parametrize("failure", ["none", "credential", "factory", "operation", "close"])
def test_async_managed_client_closes_resources(monkeypatch, capsys, failure):
    credential = MagicMock(close=AsyncMock())
    credential_factory = MagicMock(return_value=credential)
    monkeypatch.setattr(messaging, "AsyncDefaultAzureCredential", credential_factory)
    client = MagicMock(close=AsyncMock())
    factory = MagicMock(return_value=client)
    if failure == "credential":
        credential_factory.side_effect = AzureError("credential failed")
    if failure == "factory":
        factory.side_effect = AzureError("client failed")
    if failure == "close":
        client.close.side_effect = AzureError("close failed")

    async def operate():
        async with messaging.async_managed_client("Test service", factory) as actual:
            assert actual is client
            if failure == "operation":
                raise AzureError("operation failed")

    if failure == "none":
        asyncio.run(operate())
    else:
        with pytest.raises(messaging.OperationError) as error:
            asyncio.run(operate())
        assert "Test service operation failed" in str(error.value)
        assert not capsys.readouterr().err
    if failure != "credential":
        credential.close.assert_awaited_once()
        factory.assert_called_once_with(credential)
    if failure not in ("credential", "factory"):
        client.close.assert_awaited_once()


@pytest.mark.parametrize("answer", [True, False])
def test_interactive_delete(monkeypatch, answer):
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    confirm = MagicMock(return_value=answer)
    monkeypatch.setattr(cli.typer, "confirm", confirm)
    assert cli.confirm_delete("scratch-queue", False) is answer
    confirm.assert_called_once_with("Delete queue 'scratch-queue'? This cannot be undone.", default=False, err=True)
