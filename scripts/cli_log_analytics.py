"""Run bounded Log Analytics workspace queries using Azure authentication."""

from contextlib import closing
from datetime import timedelta
from typing import Annotated

import typer
from azure.core.exceptions import AzureError
from azure.identity import DefaultAzureCredential
from azure.monitor.query import LogsQueryClient
from dotenv import load_dotenv

from scripts._azure_messaging import print_json
from scripts._azure_observability import format_logs_result, validate_guid

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Query AzureActivity using AZURE_LOG_ANALYTICS_WORKSPACE_ID (workspace GUID) and `az login`.",
)
WorkspaceOption = Annotated[
    str,
    typer.Option("--workspace-id", envvar="AZURE_LOG_ANALYTICS_WORKSPACE_ID", help="Workspace GUID."),
]
HoursOption = Annotated[int, typer.Option("--hours", min=1, max=168, help="Lookback in hours.")]
LimitOption = Annotated[int, typer.Option("--limit", min=1, max=1000, help="Maximum result rows.")]


def _query(workspace_id: str, hours: int, limit: int, *, summarize: bool) -> None:
    workspace_id = validate_guid(workspace_id)
    query = f"AzureActivity | where TimeGenerated >= ago({hours}h)"
    if summarize:
        query += " | summarize Count=count() by OperationNameValue, ActivityStatusValue | order by Count desc"
    else:
        query += (
            " | project TimeGenerated, OperationNameValue, ActivityStatusValue, ResourceGroup, ResourceId"
            " | order by TimeGenerated desc"
        )
    query += f" | take {limit}"
    try:
        with closing(DefaultAzureCredential()) as credential, closing(LogsQueryClient(credential)) as client:
            result = client.query_workspace(workspace_id, query, timespan=timedelta(hours=hours), server_timeout=30)
            output = format_logs_result(result)
    except AzureError:
        print_json({"error": "Azure Log Analytics query failed."})
        raise typer.Exit(1) from None
    print_json(output)
    if "error" in output:
        raise typer.Exit(1)


@app.command()
def query_logs(workspace_id: WorkspaceOption, hours: HoursOption = 24, limit: LimitOption = 100) -> None:
    """Return recent AzureActivity rows; no arbitrary KQL is accepted."""
    _query(workspace_id, hours, limit, summarize=False)


@app.command()
def summarize_activity(workspace_id: WorkspaceOption, hours: HoursOption = 24, limit: LimitOption = 100) -> None:
    """Count AzureActivity by operation and status within a bounded window."""
    _query(workspace_id, hours, limit, summarize=True)


if __name__ == "__main__":
    load_dotenv(override=False)
    app()
