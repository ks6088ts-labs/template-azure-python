import json
import runpy
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from azure.core.exceptions import AzureError, ClientAuthenticationError, HttpResponseError, ServiceRequestError
from azure.mgmt.monitor.models import EventData
from click import unstyle
from typer.testing import CliRunner

from scripts.cli_activity_log import app

SUBSCRIPTION = "11111111-2222-3333-4444-555555555555"
OTHER_SUBSCRIPTION = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
COMMANDS = ("list-events", "summarize-events")
NOW = datetime(2026, 10, 2, 3, 0, tzinfo=timezone.utc)


def _event(status: str = "Succeeded", operation: str = "Microsoft.Compute/virtualMachines/write") -> EventData:
    return EventData.deserialize(
        {
            "eventDataId": "event-1",
            "eventTimestamp": "2026-10-02T02:00:00Z",
            "resourceId": (
                f"/subscriptions/{SUBSCRIPTION}/resourceGroups/my-rg/providers/Microsoft.Compute/virtualMachines/vm"
            ),
            "resourceGroupName": "my-rg",
            "operationName": {"value": operation},
            "status": {"value": status},
            "level": "Informational",
        }
    )


@pytest.fixture
def clients(monkeypatch: pytest.MonkeyPatch):
    for name in ("AZURE_SUBSCRIPTION_ID", "AZURE_RESOURCE_GROUP"):
        monkeypatch.delenv(name, raising=False)
    credential = MagicMock()
    client = MagicMock()
    client.activity_logs.list.return_value = [_event()]
    with (
        patch("scripts.cli_activity_log.DefaultAzureCredential", return_value=credential) as credential_type,
        patch("scripts.cli_activity_log.MonitorManagementClient", return_value=client) as client_type,
        patch("scripts.cli_activity_log.datetime") as clock,
    ):
        clock.now.return_value = NOW
        yield SimpleNamespace(
            credential=credential, client=client, credential_type=credential_type, client_type=client_type, clock=clock
        )


def _args(command: str) -> list[str]:
    return [command, "--subscription-id", SUBSCRIPTION]


def _assert_closed(clients: SimpleNamespace) -> None:
    clients.client.close.assert_called_once_with()
    clients.credential.close.assert_called_once_with()


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("hours", [None, 1, 168])
@pytest.mark.parametrize("resource_group", [None, "my-rg"])
def test_utc_filter_and_metadata(command: str, hours: int | None, resource_group: str | None, clients: SimpleNamespace):
    args = _args(command)
    if hours is not None:
        args += ["--hours", str(hours)]
    if resource_group is not None:
        args += ["--resource-group", resource_group]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    start = (NOW - timedelta(hours=24 if hours is None else hours)).isoformat().replace("+00:00", "Z")
    end = "2026-10-02T03:00:00Z"
    expected_filter = f"eventTimestamp ge '{start}' and eventTimestamp le '{end}'"
    if resource_group:
        expected_filter += " and resourceGroupName eq 'my-rg'"
    clients.client.activity_logs.list.assert_called_once_with(filter=expected_filter)
    clients.clock.now.assert_called_once_with(timezone.utc)
    clients.client_type.assert_called_once_with(credential=clients.credential, subscription_id=SUBSCRIPTION)
    output = json.loads(result.output)
    assert {key: output[key] for key in ("start_time", "end_time", "limit", "sample_count")} == {
        "start_time": start,
        "end_time": end,
        "limit": 100,
        "sample_count": 1,
    }
    if command == "list-events":
        assert set(output) == {"start_time", "end_time", "limit", "sample_count", "events"}
        assert output["events"] == [
            {
                "event_data_id": "event-1",
                "event_timestamp": "2026-10-02T02:00:00+00:00",
                "resource_id": _event().resource_id,
                "resource_group_name": "my-rg",
                "operation_name": "Microsoft.Compute/virtualMachines/write",
                "status": "Succeeded",
                "level": "Informational",
            }
        ]
    else:
        assert set(output) == {"start_time", "end_time", "limit", "sample_count", "by_status", "by_operation"}
        assert output["by_status"] == {"Succeeded": 1}
        assert output["by_operation"] == {"Microsoft.Compute/virtualMachines/write": 1}
    _assert_closed(clients)


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("limit", [1, 3, 1000])
def test_iteration_stops_at_limit(command: str, limit: int, clients: SimpleNamespace):
    consumed = []

    def records():
        for index in range(limit):
            consumed.append(index)
            yield _event("Failed" if index % 2 else "Succeeded")
        pytest.fail("Iterator consumed past the requested limit")

    clients.client.activity_logs.list.return_value = records()
    result = CliRunner().invoke(app, [*_args(command), "--limit", str(limit)])
    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["sample_count"] == limit
    assert output["limit"] == limit
    assert len(consumed) == limit
    if command == "summarize-events":
        assert sum(output["by_status"].values()) == limit
    else:
        assert len(output["events"]) == limit
    _assert_closed(clients)


@pytest.mark.parametrize("command", COMMANDS)
def test_default_limit_is_bounded(command: str, clients: SimpleNamespace):
    def records():
        for _ in range(100):
            yield _event()
        pytest.fail("Default limit must stop at 100")

    clients.client.activity_logs.list.return_value = records()
    result = CliRunner().invoke(app, _args(command))
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["sample_count"] == 100


@pytest.mark.parametrize("command", COMMANDS)
def test_empty_success(command: str, clients: SimpleNamespace):
    clients.client.activity_logs.list.return_value = []
    result = CliRunner().invoke(app, _args(command))
    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["sample_count"] == 0
    if command == "list-events":
        assert output["events"] == []
    else:
        assert output["by_status"] == {}
        assert output["by_operation"] == {}
    _assert_closed(clients)


@pytest.mark.parametrize("command", COMMANDS)
def test_missing_fields(command: str, clients: SimpleNamespace):
    clients.client.activity_logs.list.return_value = [EventData()]
    result = CliRunner().invoke(app, _args(command))
    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    if command == "list-events":
        assert output["events"] == [
            dict.fromkeys(
                [
                    "event_data_id",
                    "event_timestamp",
                    "resource_id",
                    "resource_group_name",
                    "operation_name",
                    "status",
                    "level",
                ]
            )
        ]
    else:
        assert output["by_status"] == {"(unknown)": 1}
        assert output["by_operation"] == {"(unknown)": 1}


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("explicit", [False, True])
def test_environment_precedence(command: str, explicit: bool, clients: SimpleNamespace):
    args = [*_args(command), "--resource-group", "cli-rg"] if explicit else [command]
    result = CliRunner().invoke(
        app, args, env={"AZURE_SUBSCRIPTION_ID": OTHER_SUBSCRIPTION, "AZURE_RESOURCE_GROUP": "environment-rg"}
    )
    assert result.exit_code == 0, result.output
    clients.client_type.assert_called_once_with(
        credential=clients.credential, subscription_id=SUBSCRIPTION if explicit else OTHER_SUBSCRIPTION
    )
    group = "cli-rg" if explicit else "environment-rg"
    assert clients.client.activity_logs.list.call_args.kwargs["filter"].endswith(f"resourceGroupName eq '{group}'")


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize(
    "option,value",
    [
        ("--subscription-id", "invalid"),
        ("--subscription-id", SUBSCRIPTION.replace("-", "")),
        ("--subscription-id", "{" + SUBSCRIPTION + "}"),
        ("--resource-group", "bad' or '1' eq '1"),
        ("--resource-group", "bad/group"),
        ("--resource-group", "bad\nname"),
        ("--resource-group", " "),
        ("--resource-group", ""),
        ("--resource-group", "ends."),
        ("--resource-group", "x" * 91),
        ("--hours", "0"),
        ("--hours", "169"),
        ("--hours", "1.5"),
        ("--limit", "0"),
        ("--limit", "1001"),
        ("--limit", "-1"),
    ],
)
def test_invalid_input_before_auth(command: str, option: str, value: str, clients: SimpleNamespace):
    args = [command] if option == "--subscription-id" else _args(command)
    result = CliRunner().invoke(app, [*args, option, value])
    assert result.exit_code == 2, result.output
    clients.credential_type.assert_not_called()
    clients.client_type.assert_not_called()


@pytest.mark.parametrize("command", COMMANDS)
def test_missing_subscription_before_auth(command: str, clients: SimpleNamespace):
    result = CliRunner().invoke(app, [command])
    assert result.exit_code == 2
    clients.credential_type.assert_not_called()


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("error_type", [AzureError, ClientAuthenticationError, HttpResponseError, ServiceRequestError])
def test_azure_errors_sanitized(command: str, error_type: type[AzureError], clients: SimpleNamespace):
    clients.client.activity_logs.list.side_effect = error_type("unsafe-token-secret")
    result = CliRunner().invoke(app, _args(command))
    assert result.exit_code == 1
    assert "unsafe-token-secret" not in result.output
    assert "Error: Azure Activity Log request failed" in result.output
    _assert_closed(clients)


@pytest.mark.parametrize("command", COMMANDS)
def test_iteration_failure_has_no_partial_json(command: str, clients: SimpleNamespace):
    def records():
        yield _event()
        raise AzureError("unsafe-token-secret")

    clients.client.activity_logs.list.return_value = records()
    result = CliRunner().invoke(app, _args(command))
    assert result.exit_code == 1
    assert "unsafe-token-secret" not in result.output
    assert '"sample_count"' not in result.output
    _assert_closed(clients)


@pytest.mark.parametrize("stage", ["credential", "client", "client_close", "credential_close"])
def test_construction_and_cleanup_failure(stage: str, clients: SimpleNamespace):
    target = {
        "credential": clients.credential_type,
        "client": clients.client_type,
        "client_close": clients.client.close,
        "credential_close": clients.credential.close,
    }[stage]
    target.side_effect = AzureError("unsafe-token-secret")
    result = CliRunner().invoke(app, _args("list-events"))
    assert result.exit_code == 1
    assert "unsafe-token-secret" not in result.output
    if stage != "credential":
        clients.credential.close.assert_called_once_with()
    if stage.endswith("_close"):
        clients.client.close.assert_called_once_with()


@pytest.mark.parametrize("args", [[], ["list-events"], ["summarize-events"]])
def test_help(args: list[str], clients: SimpleNamespace):
    result = CliRunner().invoke(app, [*args, "--help"])
    assert result.exit_code == 0, result.output
    output = unstyle(result.output)
    if args:
        assert "JSON" in output
        assert "--hours" in output
        assert "--limit" in output
        assert "sample" in output
    else:
        assert "Log Analytics" in output
        assert "live Azure Activity Log" in output
    clients.credential_type.assert_not_called()


def test_main_loads_dotenv_without_override(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delitem(sys.modules, "scripts.cli_activity_log", raising=False)
    with patch("dotenv.load_dotenv") as dotenv, patch("typer.Typer.__call__") as invoke:
        runpy.run_module("scripts.cli_activity_log", run_name="__main__")
    dotenv.assert_called_once_with(override=False)
    invoke.assert_called_once_with()
