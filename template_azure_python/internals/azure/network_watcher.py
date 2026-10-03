from collections.abc import Generator
from contextlib import closing, contextmanager

from azure.identity import DefaultAzureCredential
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.network.models import NetworkWatcher

from template_azure_python.internals.azure._common import (
    azure_errors,
    required_value,
    validate_arm_id,
    validate_guid,
    validate_resource_group,
)
from template_azure_python.settings import get_azure_settings


@contextmanager
def _network_client(subscription_id: str) -> Generator[NetworkManagementClient, None, None]:
    with azure_errors("Azure Network Watcher request failed. Check Azure authentication and Reader access."):
        with closing(DefaultAzureCredential()) as credential:
            with closing(NetworkManagementClient(credential=credential, subscription_id=subscription_id)) as client:
                yield client


def _watcher_record(watcher: NetworkWatcher) -> dict[str, object]:
    return {
        "id": watcher.id,
        "name": watcher.name,
        "location": watcher.location,
        "provisioning_state": watcher.provisioning_state,
    }


def show_watcher(resource_id: str | None) -> dict[str, object]:
    resource_id = required_value(resource_id, get_azure_settings().azure_network_watcher_id, "--resource-id")
    subscription, resource_group, name = validate_arm_id(resource_id, "Microsoft.Network", "networkWatchers")
    with _network_client(subscription) as client:
        return _watcher_record(
            client.network_watchers.get(resource_group_name=resource_group, network_watcher_name=name)
        )


def list_watchers(subscription_id: str | None, resource_group: str | None) -> dict[str, object]:
    settings = get_azure_settings()
    subscription_id = validate_guid(
        required_value(subscription_id, settings.azure_subscription_id, "--subscription-id")
    )
    resource_group = validate_resource_group(
        settings.azure_resource_group if resource_group is None else resource_group
    )
    with _network_client(subscription_id) as client:
        watchers = (
            client.network_watchers.list(resource_group_name=resource_group)
            if resource_group is not None
            else client.network_watchers.list_all()
        )
        return {"watchers": [_watcher_record(watcher) for watcher in watchers]}
