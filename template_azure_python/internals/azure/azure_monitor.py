import re
from contextlib import closing

import requests
from azure.identity import DefaultAzureCredential
from azure.mgmt.monitor import MonitorManagementClient

from template_azure_python.internals.azure._common import (
    InputError,
    OperationError,
    azure_errors,
    required_value,
    validate_arm_id,
)
from template_azure_python.settings import get_azure_settings

PROMETHEUS_SCOPE = "https://prometheus.monitor.azure.com/.default"
_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_ENDPOINT = re.compile(rf"https://{_LABEL}\.{_LABEL}\.prometheus\.monitor\.azure\.com/?")


def _prometheus_endpoint(value: str | None) -> str:
    # Only the public Azure service origin returned by ARM may receive the token.
    if not isinstance(value, str) or not _ENDPOINT.fullmatch(value):
        raise InputError("ARM returned an invalid HTTPS Azure Prometheus endpoint")
    return value.rstrip("/")


def _resource(resource_id: str | None) -> tuple[str, str, str]:
    resource_id = required_value(resource_id, get_azure_settings().azure_monitor_id, "--resource-id")
    return validate_arm_id(resource_id, "Microsoft.Monitor", "accounts")


def show_workspace(resource_id: str | None) -> dict[str, object]:
    subscription, resource_group, name = _resource(resource_id)
    with azure_errors("Azure Monitor workspace read failed. Check Azure access and resource ID."):
        with closing(DefaultAzureCredential()) as credential:
            with closing(MonitorManagementClient(credential, subscription)) as client:
                workspace = client.azure_monitor_workspaces.get(resource_group, name)
                return {
                    "id": workspace.id,
                    "name": workspace.name,
                    "location": workspace.location,
                    "prometheus_query_endpoint": (
                        workspace.metrics.prometheus_query_endpoint if workspace.metrics else None
                    ),
                }


def query_prometheus(resource_id: str | None, query: str) -> dict[str, object]:
    subscription, resource_group, name = _resource(resource_id)
    if not query.strip() or len(query) > 4096 or any(ord(char) < 32 or ord(char) == 127 for char in query):
        raise InputError("must be nonblank, at most 4096 characters, without control characters", "query")
    with azure_errors("Azure Monitor authentication or workspace read failed. Check Azure access."):
        with closing(DefaultAzureCredential()) as credential:
            with closing(MonitorManagementClient(credential, subscription)) as client:
                workspace = client.azure_monitor_workspaces.get(resource_group, name)
                endpoint = _prometheus_endpoint(
                    workspace.metrics.prometheus_query_endpoint if workspace.metrics else None
                )
            token = credential.get_token(PROMETHEUS_SCOPE)
            try:
                with requests.Session() as session:
                    with session.get(
                        f"{endpoint}/api/v1/query",
                        params={"query": query},
                        headers={"Authorization": "Bearer " + token.token},
                        timeout=30,
                        allow_redirects=False,
                    ) as response:
                        if not 200 <= response.status_code < 300:
                            raise OperationError(f"Prometheus HTTP request failed (status {response.status_code}).")
                        payload = response.json()
                        if not isinstance(payload, dict) or payload.get("status") not in ("success", "error"):
                            raise ValueError("invalid Prometheus response")
                        if payload["status"] == "success":
                            data = payload.get("data")
                            if not isinstance(data, dict) or "resultType" not in data or "result" not in data:
                                raise ValueError("missing Prometheus data")
                        return payload
            except (requests.RequestException, ValueError) as exc:
                raise OperationError("Prometheus request failed or returned invalid JSON data.") from exc
