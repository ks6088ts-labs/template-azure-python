import json
import runpy
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import requests
from azure.core.exceptions import AzureError
from typer.testing import CliRunner

from scripts.cli_azure_monitor import app
from template_azure_python.internals.azure.azure_monitor import PROMETHEUS_SCOPE
from template_azure_python.settings import AzureSettings

SUBSCRIPTION = "12345678-1234-1234-1234-123456789abc"
RESOURCE_ID = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/monitor-rg/providers/Microsoft.Monitor/accounts/demo"
ENDPOINT = "https://demo-abc.westus2.prometheus.monitor.azure.com"
EMPTY = {"status": "success", "data": {"resultType": "vector", "result": []}}


@pytest.fixture
def clients():
    credential = MagicMock()
    credential.get_token.return_value.token = "sensitive-test-token"
    client = MagicMock()
    client.azure_monitor_workspaces.get.return_value = SimpleNamespace(
        id=RESOURCE_ID, name="demo", location="westus2", metrics=SimpleNamespace(prometheus_query_endpoint=ENDPOINT)
    )
    session = MagicMock()
    response = session.get.return_value.__enter__.return_value
    response.status_code = 200
    response.json.return_value = EMPTY
    with (
        patch(
            "template_azure_python.internals.azure.azure_monitor.DefaultAzureCredential", return_value=credential
        ) as auth,
        patch(
            "template_azure_python.internals.azure.azure_monitor.MonitorManagementClient", return_value=client
        ) as factory,
        patch("template_azure_python.internals.azure.azure_monitor.requests.Session") as http,
    ):
        http.return_value.__enter__.return_value = session
        yield SimpleNamespace(
            credential=credential,
            client=client,
            auth=auth,
            factory=factory,
            http=http,
            session=session,
            response=response,
        )


def test_show_workspace(clients):
    result = CliRunner().invoke(app, ["show-workspace", "--resource-id", RESOURCE_ID])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "id": RESOURCE_ID,
        "name": "demo",
        "location": "westus2",
        "prometheus_query_endpoint": ENDPOINT,
    }
    clients.factory.assert_called_once_with(clients.credential, SUBSCRIPTION)
    clients.client.azure_monitor_workspaces.get.assert_called_once_with("monitor-rg", "demo")
    clients.client.close.assert_called_once_with()
    clients.credential.close.assert_called_once_with()
    clients.http.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [
        EMPTY,
        {
            "status": "success",
            "data": {"resultType": "vector", "result": [{"metric": {"job": "demo"}, "value": [1, "2"]}]},
        },
        {"status": "error", "errorType": "bad_data", "error": "invalid expression"},
    ],
)
def test_prometheus_output_and_request(payload, clients):
    clients.response.json.return_value = payload
    result = CliRunner().invoke(app, ["query-prometheus", "--resource-id", RESOURCE_ID, "--query", "sum(up)"])
    assert result.exit_code == (1 if payload["status"] == "error" else 0), result.output
    assert json.loads(result.output) == payload
    assert "sensitive-test-token" not in result.output
    clients.credential.get_token.assert_called_once_with(PROMETHEUS_SCOPE)
    clients.session.get.assert_called_once_with(
        ENDPOINT + "/api/v1/query",
        params={"query": "sum(up)"},
        headers={"Authorization": "Bearer " + "sensitive-test-token"},
        timeout=30,
        allow_redirects=False,
    )
    clients.client.close.assert_called_once_with()
    clients.credential.close.assert_called_once_with()
    clients.session.get.return_value.__exit__.assert_called_once()
    clients.http.return_value.__exit__.assert_called_once()


@pytest.mark.parametrize("command", ["show-workspace", "query-prometheus"])
@pytest.mark.parametrize("override", [False, True])
def test_environment_and_override(command, override, clients):
    environment_id = RESOURCE_ID.replace("/demo", "/environment")
    args = [command, "--resource-id", RESOURCE_ID] if override else [command]
    result = CliRunner().invoke(app, args, env={"AZURE_MONITOR_ID": environment_id})
    assert result.exit_code == 0, result.output
    clients.client.azure_monitor_workspaces.get.assert_called_once_with(
        "monitor-rg", "demo" if override else "environment"
    )


@pytest.mark.parametrize("command", ["show-workspace", "query-prometheus"])
@pytest.mark.parametrize(
    "value",
    [
        "not-an-id",
        RESOURCE_ID + "/extra",
        RESOURCE_ID.replace("Microsoft.Monitor", "Microsoft.OperationalInsights"),
        RESOURCE_ID.replace(SUBSCRIPTION, "invalid"),
        RESOURCE_ID.replace("monitor-rg", "bad?group"),
        RESOURCE_ID + "?token=sensitive-test-token",
        RESOURCE_ID + "\n",
        RESOURCE_ID.replace("/demo", "/.."),
        RESOURCE_ID.replace("/demo", "/%2fother"),
    ],
)
def test_invalid_id_before_auth(command, value, clients):
    result = CliRunner().invoke(app, [command, "--resource-id", value])
    assert result.exit_code == 2, result.output
    clients.auth.assert_not_called()
    clients.http.assert_not_called()
    assert "sensitive-test-token" not in result.output


@pytest.mark.parametrize("query", ["", " ", "a" * 4097, "up\n", "up\x7f"])
def test_invalid_query_before_auth(query, clients):
    result = CliRunner().invoke(app, ["query-prometheus", "--resource-id", RESOURCE_ID, "--query", query])
    assert result.exit_code == 2, result.output
    clients.auth.assert_not_called()


@pytest.mark.parametrize(
    "endpoint",
    [
        None,
        "http://demo.westus2.prometheus.monitor.azure.com",
        "https://evil.example",
        "https://demo.westus2.prometheus.monitor.azure.com.evil.example",
        "https://demo.westus2.prometheus.monitor.azure.com@evil.example",
        ENDPOINT + "?token=sensitive-test-token",
        ENDPOINT + "#fragment",
        ENDPOINT + "/api/v1/query",
        ENDPOINT + ":80",
        ENDPOINT + "\\@evil.example",
        ENDPOINT + "\n",
        ENDPOINT.replace("demo-abc", "-bad"),
        "https://127.0.0.1",
    ],
)
def test_invalid_endpoint_before_prometheus_token(endpoint, clients):
    clients.client.azure_monitor_workspaces.get.return_value.metrics.prometheus_query_endpoint = endpoint
    result = CliRunner().invoke(app, ["query-prometheus", "--resource-id", RESOURCE_ID])
    assert result.exit_code == 2, result.output
    clients.credential.get_token.assert_not_called()
    clients.http.assert_not_called()
    clients.client.close.assert_called_once_with()
    clients.credential.close.assert_called_once_with()
    assert "sensitive-test-token" not in result.output


def test_trailing_slash_and_default_query(clients):
    clients.client.azure_monitor_workspaces.get.return_value.metrics.prometheus_query_endpoint = ENDPOINT + "/"
    result = CliRunner().invoke(app, ["query-prometheus", "--resource-id", RESOURCE_ID])
    assert result.exit_code == 0, result.output
    assert clients.session.get.call_args.args == (ENDPOINT + "/api/v1/query",)
    assert clients.session.get.call_args.kwargs["params"] == {"query": "up"}


@pytest.mark.parametrize("status", [301, 302, 307, 308, 400, 401, 403, 429, 500])
def test_http_failure_and_redirect_rejection(status, clients):
    clients.response.status_code = status
    result = CliRunner().invoke(app, ["query-prometheus", "--resource-id", RESOURCE_ID])
    assert result.exit_code == 1, result.output
    assert f"status {status}" in result.output
    clients.response.json.assert_not_called()
    assert "sensitive-test-token" not in result.output


@pytest.mark.parametrize(
    "payload", [None, [], {}, {"status": "unknown"}, {"status": "success"}, {"status": "success", "data": {}}]
)
def test_invalid_response(payload, clients):
    clients.response.json.return_value = payload
    result = CliRunner().invoke(app, ["query-prometheus", "--resource-id", RESOURCE_ID])
    assert result.exit_code == 1, result.output
    assert "invalid JSON data" in result.output


@pytest.mark.parametrize("error", [requests.Timeout("sensitive-test-token"), ValueError("sensitive-test-token")])
def test_request_errors_are_sanitized(error, clients):
    clients.session.get.side_effect = error
    result = CliRunner().invoke(app, ["query-prometheus", "--resource-id", RESOURCE_ID])
    assert result.exit_code == 1, result.output
    assert "sensitive-test-token" not in result.output
    clients.credential.close.assert_called_once_with()


@pytest.mark.parametrize("command", ["show-workspace", "query-prometheus"])
@pytest.mark.parametrize("failure", ["auth", "factory", "get", "close", "token"])
def test_azure_failures_are_sanitized(command, failure, clients):
    if failure == "token" and command == "show-workspace":
        return
    target = {
        "auth": clients.auth,
        "factory": clients.factory,
        "get": clients.client.azure_monitor_workspaces.get,
        "close": clients.client.close,
        "token": clients.credential.get_token,
    }[failure]
    target.side_effect = AzureError("sensitive-test-token")
    result = CliRunner().invoke(app, [command, "--resource-id", RESOURCE_ID])
    assert result.exit_code == 1, result.output
    assert "Error:" in result.output
    assert "sensitive-test-token" not in result.output
    if failure != "auth":
        clients.credential.close.assert_called_once_with()


@pytest.mark.parametrize("command", [[], ["show-workspace"], ["query-prometheus"]])
def test_help_without_auth(command, clients):
    result = CliRunner().invoke(app, [*command, "--help"])
    assert result.exit_code == 0, result.output
    clients.auth.assert_not_called()


def test_module_entrypoint_does_not_load_dotenv(monkeypatch):
    monkeypatch.delitem(sys.modules, "scripts.cli_azure_monitor", raising=False)
    with patch("dotenv.load_dotenv") as dotenv, patch("typer.Typer.__call__") as invoke:
        runpy.run_module("scripts.cli_azure_monitor", run_name="__main__")
    dotenv.assert_not_called()
    invoke.assert_called_once_with()


@pytest.mark.parametrize("override", [False, True])
def test_dotenv_values_and_cli_override(tmp_path, monkeypatch, override):
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(f"AZURE_MONITOR_ID={RESOURCE_ID}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    config = AzureSettings.model_config.copy()
    config["env_file"] = ".env"
    monkeypatch.setattr(AzureSettings, "model_config", config)
    monkeypatch.delenv("AZURE_MONITOR_ID", raising=False)
    monkeypatch.delitem(sys.modules, "scripts.cli_azure_monitor", raising=False)
    args = ["cli_azure_monitor", "show-workspace"]
    if override:
        args += ["--resource-id", RESOURCE_ID.replace("/demo", "/override")]
    monkeypatch.setattr(sys, "argv", args)
    with (
        patch.dict("os.environ", {}),
        patch("template_azure_python.internals.azure.azure_monitor.DefaultAzureCredential"),
        patch("template_azure_python.internals.azure.azure_monitor.MonitorManagementClient") as factory,
        patch("scripts._cli.print_json"),
        pytest.raises(SystemExit) as exit_info,
    ):
        runpy.run_module("scripts.cli_azure_monitor", run_name="__main__")
    assert exit_info.value.code == 0
    factory.return_value.azure_monitor_workspaces.get.assert_called_once_with(
        "monitor-rg", "override" if override else "demo"
    )
