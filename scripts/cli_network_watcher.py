"""Inspect existing Azure Network Watchers without changing network resources."""

import re
from collections.abc import Generator
from contextlib import closing, contextmanager
from typing import Annotated

import typer
from azure.core.exceptions import AzureError
from azure.identity import DefaultAzureCredential
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.network.models import NetworkWatcher
from dotenv import load_dotenv

from scripts._azure_messaging import print_json
from scripts._azure_observability import validate_arm_id, validate_guid

app = typer.Typer(
    add_completion=False,
    help="Read existing Network Watcher metadata using passwordless Azure authentication. Run `az login` first.",
    no_args_is_help=True,
    rich_markup_mode="markdown",
)

ResourceIdOption = Annotated[
    str,
    typer.Option(
        "--resource-id",
        envvar="AZURE_NETWORK_WATCHER_ID",
        help="Full Microsoft.Network/networkWatchers ARM ID; its subscription and resource group are used unchanged.",
        show_envvar=True,
    ),
]
SubscriptionOption = Annotated[
    str,
    typer.Option("--subscription-id", envvar="AZURE_SUBSCRIPTION_ID", help="Subscription UUID.", show_envvar=True),
]
ResourceGroupOption = Annotated[
    str | None,
    typer.Option(
        "--resource-group",
        envvar="AZURE_RESOURCE_GROUP",
        help="Optional group: 1–90 ASCII letters, digits, _, (, ), -, or .; no trailing dot.",
        show_envvar=True,
    ),
]


def _validate_resource_group(value: str | None) -> str | None:
    if value is not None and (re.fullmatch(r"[A-Za-z0-9_().-]{1,90}", value) is None or value.endswith(".")):
        raise typer.BadParameter("must be a valid resource group name", param_hint="--resource-group")
    return value


@contextmanager
def _network_client(subscription_id: str) -> Generator[NetworkManagementClient, None, None]:
    try:
        with closing(DefaultAzureCredential()) as credential:
            with closing(NetworkManagementClient(credential=credential, subscription_id=subscription_id)) as client:
                yield client
    except AzureError:
        typer.echo(
            "Error: Azure Network Watcher request failed. Check Azure authentication and Reader access.", err=True
        )
        raise typer.Exit(code=1) from None


def _watcher_record(watcher: NetworkWatcher) -> dict[str, object]:
    return {
        "id": watcher.id,
        "name": watcher.name,
        "location": watcher.location,
        "provisioning_state": watcher.provisioning_state,
    }


@app.command()
def show_watcher(resource_id: ResourceIdOption) -> None:
    """Read one watcher. JSON: {id, name, location, provisioning_state}; absent fields are null."""
    subscription_id, resource_group, name = validate_arm_id(resource_id, "Microsoft.Network", "networkWatchers")
    with _network_client(subscription_id) as client:
        record = _watcher_record(
            client.network_watchers.get(resource_group_name=resource_group, network_watcher_name=name)
        )
    print_json(record)


@app.command()
def list_watchers(subscription_id: SubscriptionOption, resource_group: ResourceGroupOption = None) -> None:
    """Read watcher metadata. JSON: {watchers: [{id, name, location, provisioning_state}]}; empty list is success."""
    subscription_id = validate_guid(subscription_id)
    resource_group = _validate_resource_group(resource_group)
    with _network_client(subscription_id) as client:
        watchers = (
            client.network_watchers.list(resource_group_name=resource_group)
            if resource_group is not None
            else client.network_watchers.list_all()
        )
        records = [_watcher_record(watcher) for watcher in watchers]
    print_json({"watchers": records})


if __name__ == "__main__":
    load_dotenv(override=False)
    app()
