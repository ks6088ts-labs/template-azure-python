import json
import runpy
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from azure.core.exceptions import AzureError, ClientAuthenticationError, HttpResponseError, ServiceRequestError
from azure.mgmt.network.models import NetworkWatcher
from click import unstyle
from typer.testing import CliRunner

from scripts.cli_network_watcher import app

SUBSCRIPTION = "11111111-2222-3333-4444-555555555555"
OTHER_SUBSCRIPTION = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
RESOURCE_ID = (
    f"/subscriptions/{SUBSCRIPTION}/resourceGroups/NetworkWatcherRG"
    "/providers/Microsoft.Network/networkWatchers/watcher-eastus"
)
RECORD = {"id": RESOURCE_ID, "name": "watcher-eastus", "location": "eastus", "provisioning_state": "Succeeded"}
COMMANDS = ("show-watcher", "list-watchers")


@pytest.fixture
def clients(monkeypatch: pytest.MonkeyPatch):
    for name in ("AZURE_NETWORK_WATCHER_ID", "AZURE_SUBSCRIPTION_ID", "AZURE_RESOURCE_GROUP"):
        monkeypatch.delenv(name, raising=False)
    credential = MagicMock()
    client = MagicMock()
    watcher = NetworkWatcher(
        {
            "id": RESOURCE_ID,
            "name": "watcher-eastus",
            "location": "eastus",
            "properties": {"provisioningState": "Succeeded"},
        }
    )
    client.network_watchers.get.return_value = watcher
    client.network_watchers.list.return_value = [watcher]
    client.network_watchers.list_all.return_value = [watcher]
    with (
        patch(
            "template_azure_python.internals.azure.network_watcher.DefaultAzureCredential", return_value=credential
        ) as credential_type,
        patch(
            "template_azure_python.internals.azure.network_watcher.NetworkManagementClient", return_value=client
        ) as client_type,
    ):
        yield SimpleNamespace(
            credential=credential, client=client, credential_type=credential_type, client_type=client_type
        )


def _args(command: str) -> list[str]:
    return (
        [command, "--resource-id", RESOURCE_ID]
        if command == "show-watcher"
        else [command, "--subscription-id", SUBSCRIPTION]
    )


def _assert_closed(clients: SimpleNamespace) -> None:
    clients.client.close.assert_called_once_with()
    clients.credential.close.assert_called_once_with()


def test_show_preserves_arm_scope(clients: SimpleNamespace):
    result = CliRunner().invoke(
        app,
        _args("show-watcher"),
        env={"AZURE_SUBSCRIPTION_ID": OTHER_SUBSCRIPTION, "AZURE_RESOURCE_GROUP": "application-rg"},
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == RECORD
    clients.client_type.assert_called_once_with(credential=clients.credential, subscription_id=SUBSCRIPTION)
    clients.client.network_watchers.get.assert_called_once_with(
        resource_group_name="NetworkWatcherRG", network_watcher_name="watcher-eastus"
    )
    _assert_closed(clients)


@pytest.mark.parametrize("resource_group", [None, "my-rg"])
def test_list_scope(resource_group: str | None, clients: SimpleNamespace):
    args = _args("list-watchers")
    if resource_group:
        args += ["--resource-group", resource_group]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"watchers": [RECORD]}
    if resource_group:
        clients.client.network_watchers.list.assert_called_once_with(resource_group_name=resource_group)
        clients.client.network_watchers.list_all.assert_not_called()
    else:
        clients.client.network_watchers.list_all.assert_called_once_with()
        clients.client.network_watchers.list.assert_not_called()
    _assert_closed(clients)


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("explicit", [False, True])
def test_environment_precedence(command: str, explicit: bool, clients: SimpleNamespace):
    env_id = RESOURCE_ID.replace(SUBSCRIPTION, OTHER_SUBSCRIPTION).replace("NetworkWatcherRG", "environment-rg")
    args = _args(command) if explicit else [command]
    if command == "list-watchers" and explicit:
        args += ["--resource-group", "cli-rg"]
    result = CliRunner().invoke(
        app,
        args,
        env={
            "AZURE_NETWORK_WATCHER_ID": env_id,
            "AZURE_SUBSCRIPTION_ID": OTHER_SUBSCRIPTION,
            "AZURE_RESOURCE_GROUP": "environment-rg",
        },
    )
    assert result.exit_code == 0, result.output
    clients.client_type.assert_called_once_with(
        credential=clients.credential, subscription_id=SUBSCRIPTION if explicit else OTHER_SUBSCRIPTION
    )
    if command == "show-watcher":
        clients.client.network_watchers.get.assert_called_once_with(
            resource_group_name="NetworkWatcherRG" if explicit else "environment-rg",
            network_watcher_name="watcher-eastus",
        )
    else:
        clients.client.network_watchers.list.assert_called_once_with(
            resource_group_name="cli-rg" if explicit else "environment-rg"
        )


@pytest.mark.parametrize(
    "value",
    [
        "",
        " ",
        "not-an-id",
        RESOURCE_ID + "/extra",
        RESOURCE_ID + "?secret=unsafe",
        RESOURCE_ID.replace("Microsoft.Network", "Microsoft.Compute"),
        RESOURCE_ID.replace("networkWatchers", "virtualNetworks"),
        RESOURCE_ID.replace(SUBSCRIPTION, SUBSCRIPTION.replace("-", "")),
        RESOURCE_ID.replace("NetworkWatcherRG", "../other"),
    ],
)
def test_invalid_id_before_auth(value: str, clients: SimpleNamespace):
    result = CliRunner().invoke(app, ["show-watcher", "--resource-id", value])
    assert result.exit_code == 2, result.output
    clients.credential_type.assert_not_called()
    clients.client_type.assert_not_called()


@pytest.mark.parametrize(
    "args",
    [
        ["list-watchers", "--subscription-id", "not-a-uuid"],
        ["list-watchers", "--subscription-id", SUBSCRIPTION.replace("-", "")],
        ["list-watchers", "--subscription-id", SUBSCRIPTION, "--resource-group", "bad/group"],
        ["list-watchers", "--subscription-id", SUBSCRIPTION, "--resource-group", "bad'group"],
        ["list-watchers", "--subscription-id", SUBSCRIPTION, "--resource-group", "ends."],
        ["show-watcher"],
        ["list-watchers"],
    ],
)
def test_invalid_list_options_before_auth(args: list[str], clients: SimpleNamespace):
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 2, result.output
    clients.credential_type.assert_not_called()


def test_empty_list(clients: SimpleNamespace):
    clients.client.network_watchers.list_all.return_value = []
    result = CliRunner().invoke(app, _args("list-watchers"))
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"watchers": []}
    _assert_closed(clients)


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("error_type", [AzureError, ClientAuthenticationError, HttpResponseError, ServiceRequestError])
def test_errors_sanitized(command: str, error_type: type[AzureError], clients: SimpleNamespace):
    operation = (
        clients.client.network_watchers.get if command == "show-watcher" else clients.client.network_watchers.list_all
    )
    operation.side_effect = error_type("unsafe-token-secret")
    result = CliRunner().invoke(app, _args(command))
    assert result.exit_code == 1
    assert "unsafe-token-secret" not in result.output
    assert "Error: Azure Network Watcher request failed" in result.output
    _assert_closed(clients)


def test_iteration_failure(clients: SimpleNamespace):
    def records():
        yield NetworkWatcher()
        raise AzureError("unsafe-token-secret")

    clients.client.network_watchers.list_all.return_value = records()
    result = CliRunner().invoke(app, _args("list-watchers"))
    assert result.exit_code == 1
    assert "unsafe-token-secret" not in result.output
    assert '"watchers"' not in result.output
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
    result = CliRunner().invoke(app, _args("show-watcher"))
    assert result.exit_code == 1
    assert "unsafe-token-secret" not in result.output
    if stage != "credential":
        clients.credential.close.assert_called_once_with()
    if stage.endswith("_close"):
        clients.client.close.assert_called_once_with()


@pytest.mark.parametrize("args", [[], ["show-watcher"], ["list-watchers"]])
def test_help(args: list[str], clients: SimpleNamespace):
    result = CliRunner().invoke(app, [*args, "--help"])
    assert result.exit_code == 0, result.output
    output = unstyle(result.output)
    assert ("JSON" if args else "show-watcher") in output
    clients.credential_type.assert_not_called()


def test_main_loads_dotenv_without_override(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delitem(sys.modules, "scripts.cli_network_watcher", raising=False)
    with patch("dotenv.load_dotenv") as dotenv, patch("typer.Typer.__call__") as invoke:
        runpy.run_module("scripts.cli_network_watcher", run_name="__main__")
    dotenv.assert_not_called()
    invoke.assert_called_once_with()
