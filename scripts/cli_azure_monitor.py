"""Read Azure Monitor Workspace metadata and managed Prometheus metrics."""

import re
from contextlib import closing
from typing import Annotated

import requests
import typer
from azure.core.exceptions import AzureError
from azure.identity import DefaultAzureCredential
from azure.mgmt.monitor import MonitorManagementClient
from dotenv import load_dotenv

from scripts._azure_messaging import print_json
from scripts._azure_observability import validate_arm_id

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Read Azure Monitor Workspace (managed Prometheus, not Log Analytics). No collector means empty results.",
)

ResourceIdOption = Annotated[
    str, typer.Option("--resource-id", envvar="AZURE_MONITOR_ID", help="Terraform azure_monitor_id ARM resource ID.")
]
QueryOption = Annotated[str, typer.Option("--query", help="Instant PromQL expression (maximum 4096 characters).")]
PROMETHEUS_SCOPE = "https://prometheus.monitor.azure.com/.default"
_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_ENDPOINT = re.compile(rf"https://{_LABEL}\.{_LABEL}\.prometheus\.monitor\.azure\.com/?")


def _prometheus_endpoint(value: str | None) -> str:
    # Only the public Azure service origin returned by ARM may receive the bearer token.
    if not isinstance(value, str) or not _ENDPOINT.fullmatch(value):
        raise typer.BadParameter("ARM returned an invalid HTTPS Azure Prometheus endpoint")
    return value.rstrip("/")


@app.command()
def show_workspace(resource_id: ResourceIdOption) -> None:
    """Look up workspace metadata using management-plane reader access."""
    subscription, resource_group, name = validate_arm_id(resource_id, "Microsoft.Monitor", "accounts")
    try:
        with closing(DefaultAzureCredential()) as credential:
            with closing(MonitorManagementClient(credential, subscription)) as client:
                workspace = client.azure_monitor_workspaces.get(resource_group, name)
                print_json(
                    {
                        "id": workspace.id,
                        "name": workspace.name,
                        "location": workspace.location,
                        "prometheus_query_endpoint": (
                            workspace.metrics.prometheus_query_endpoint if workspace.metrics else None
                        ),
                    }
                )
    except AzureError as exc:
        typer.echo("Error: Azure Monitor workspace read failed. Check Azure access and resource ID.", err=True)
        raise typer.Exit(1) from exc


@app.command()
def query_prometheus(resource_id: ResourceIdOption, query: QueryOption = "up") -> None:
    """Run one read-only instant query; an empty result is successful."""
    subscription, resource_group, name = validate_arm_id(resource_id, "Microsoft.Monitor", "accounts")
    if not query.strip() or len(query) > 4096 or any(ord(char) < 32 or ord(char) == 127 for char in query):
        raise typer.BadParameter(
            "must be nonblank, at most 4096 characters, without control characters", param_hint="query"
        )
    try:
        with closing(DefaultAzureCredential()) as credential:
            with closing(MonitorManagementClient(credential, subscription)) as client:
                workspace = client.azure_monitor_workspaces.get(resource_group, name)
                endpoint = _prometheus_endpoint(
                    workspace.metrics.prometheus_query_endpoint if workspace.metrics else None
                )
            token = credential.get_token(PROMETHEUS_SCOPE)
            with requests.Session() as session:
                with session.get(
                    f"{endpoint}/api/v1/query",
                    params={"query": query},
                    headers={"Authorization": "Bearer " + token.token},
                    timeout=30,
                    allow_redirects=False,
                ) as response:
                    if not 200 <= response.status_code < 300:
                        typer.echo(f"Error: Prometheus HTTP request failed (status {response.status_code}).", err=True)
                        raise typer.Exit(1)
                    payload = response.json()
                    if not isinstance(payload, dict) or payload.get("status") not in ("success", "error"):
                        raise ValueError("invalid Prometheus response")
                    if payload["status"] == "success":
                        data = payload.get("data")
                        if not isinstance(data, dict) or "resultType" not in data or "result" not in data:
                            raise ValueError("missing Prometheus data")
                    print_json(payload)
                    if payload["status"] == "error":
                        raise typer.Exit(1)
    except AzureError as exc:
        typer.echo("Error: Azure Monitor authentication or workspace read failed. Check Azure access.", err=True)
        raise typer.Exit(1) from exc
    except (requests.RequestException, ValueError) as exc:
        typer.echo("Error: Prometheus request failed or returned invalid JSON data.", err=True)
        raise typer.Exit(1) from exc


if __name__ == "__main__":
    load_dotenv(override=False)
    app()
