import json
import runpy
import sys
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from azure.core.exceptions import AzureError
from azure.monitor.query import LogsQueryPartialResult, LogsQueryResult, LogsTable
from typer.testing import CliRunner

from scripts.cli_log_analytics import app

GUID = "01234567-89ab-cdef-0123-456789abcdef"
COMMANDS = ("query-logs", "summarize-activity")


@pytest.fixture
def clients():
    credential, client = MagicMock(), MagicMock()
    client.query_workspace.return_value = LogsQueryResult()
    with (
        patch(
            "template_azure_python.internals.azure.log_analytics.DefaultAzureCredential", return_value=credential
        ) as auth,
        patch("template_azure_python.internals.azure.log_analytics.LogsQueryClient", return_value=client) as factory,
    ):
        yield SimpleNamespace(credential=credential, client=client, auth=auth, factory=factory)


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("options", [[], ["--hours", "1", "--limit", "1"], ["--hours", "168", "--limit", "1000"]])
def test_queries(command: str, options: list[str], clients: SimpleNamespace):
    result = CliRunner().invoke(app, [command, "--workspace-id", GUID, *options])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"tables": []}
    hours, limit = (int(options[1]), int(options[3])) if options else (24, 100)
    args, kwargs = clients.client.query_workspace.call_args
    assert args[0] == GUID
    assert args[1].startswith(f"AzureActivity | where TimeGenerated >= ago({hours}h)")
    assert args[1].endswith(f" | take {limit}")
    assert ("summarize Count=count()" in args[1]) == (command == "summarize-activity")
    assert kwargs == {"timespan": timedelta(hours=hours), "server_timeout": 30}
    clients.auth.assert_called_once_with()
    clients.factory.assert_called_once_with(clients.credential)
    clients.client.close.assert_called_once_with()
    clients.credential.close.assert_called_once_with()


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("explicit", [False, True])
def test_environment_override(command: str, explicit: bool, clients: SimpleNamespace):
    other = "ffffffff-ffff-ffff-ffff-ffffffffffff"
    args = [command, "--workspace-id", GUID] if explicit else [command]
    result = CliRunner().invoke(app, args, env={"AZURE_LOG_ANALYTICS_WORKSPACE_ID": other})
    assert result.exit_code == 0
    assert clients.client.query_workspace.call_args.args[0] == (GUID if explicit else other)


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize(
    "options",
    [
        ["--hours", "0"],
        ["--hours", "169"],
        ["--limit", "0"],
        ["--limit", "1001"],
        ["--hours", "wrong"],
        ["--workspace-id", "secret"],
        ["--query", "arbitrary"],
    ],
)
def test_validation_before_auth(command: str, options: list[str], clients: SimpleNamespace):
    result = CliRunner().invoke(app, [command, "--workspace-id", GUID, *options])
    assert result.exit_code == 2
    if "secret" in options:
        assert "secret" not in result.output
    clients.auth.assert_not_called()


@pytest.mark.parametrize("command", COMMANDS)
def test_missing_workspace(command: str, clients: SimpleNamespace):
    result = CliRunner().invoke(app, [command], env={"AZURE_LOG_ANALYTICS_WORKSPACE_ID": ""})
    assert result.exit_code == 2
    clients.auth.assert_not_called()


@pytest.mark.parametrize("command", COMMANDS)
def test_partial_results(command: str, clients: SimpleNamespace):
    clients.client.query_workspace.return_value = LogsQueryPartialResult(
        partial_data=[LogsTable(name="result", columns=["Count"], columns_types=["long"], rows=[[3]])],
        partial_error={"message": "secret"},
    )
    result = CliRunner().invoke(app, [command, "--workspace-id", GUID])
    assert result.exit_code == 1
    assert "secret" not in result.output
    assert json.loads(result.output)["tables"][0]["rows"] == [[3]]
    assert json.loads(result.output)["error"]
    clients.client.close.assert_called_once()
    clients.credential.close.assert_called_once()


@pytest.mark.parametrize("stage", ["auth", "factory", "query", "client_close", "credential_close"])
def test_azure_failures_are_sanitized_and_closed(stage: str, clients: SimpleNamespace):
    target = {
        "auth": clients.auth,
        "factory": clients.factory,
        "query": clients.client.query_workspace,
        "client_close": clients.client.close,
        "credential_close": clients.credential.close,
    }[stage]
    target.side_effect = AzureError("secret connection_string=do-not-print")
    result = CliRunner().invoke(app, ["query-logs", "--workspace-id", GUID])
    assert result.exit_code == 1
    assert json.loads(result.output) == {"error": "Azure Log Analytics query failed."}
    assert clients.credential.close.call_count == (stage != "auth")
    assert clients.client.close.call_count == (stage not in ("auth", "factory"))


@pytest.mark.parametrize("args", [[], ["query-logs"], ["summarize-activity"]])
def test_help(args: list[str], clients: SimpleNamespace):
    result = CliRunner().invoke(app, [*args, "--help"])
    assert result.exit_code == 0
    clients.auth.assert_not_called()


def test_main(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delitem(sys.modules, "scripts.cli_log_analytics", raising=False)
    with patch("dotenv.load_dotenv") as dotenv, patch("typer.Typer.__call__") as invoke:
        runpy.run_module("scripts.cli_log_analytics", run_name="__main__")
    dotenv.assert_not_called()
    invoke.assert_called_once_with()
