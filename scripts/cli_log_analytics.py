"""Run bounded Log Analytics workspace queries using Azure authentication."""

from typing import Annotated

import typer

from scripts._cli import cli_errors, print_logs
from template_azure_python.internals.azure import log_analytics

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Query AzureActivity using AZURE_LOG_ANALYTICS_WORKSPACE_ID (workspace GUID) and `az login`.",
)
WorkspaceOption = Annotated[
    str | None,
    typer.Option("--workspace-id", help="Workspace GUID. Reads AZURE_LOG_ANALYTICS_WORKSPACE_ID when omitted."),
]
HoursOption = Annotated[int, typer.Option("--hours", min=1, max=168, help="Lookback in hours.")]
LimitOption = Annotated[int, typer.Option("--limit", min=1, max=1000, help="Maximum result rows.")]


@app.command()
def query_logs(workspace_id: WorkspaceOption = None, hours: HoursOption = 24, limit: LimitOption = 100) -> None:
    """Return recent AzureActivity rows; no arbitrary KQL is accepted."""
    with cli_errors(json_error=True):
        print_logs(log_analytics.query_logs(workspace_id, hours, limit))


@app.command()
def summarize_activity(workspace_id: WorkspaceOption = None, hours: HoursOption = 24, limit: LimitOption = 100) -> None:
    """Count AzureActivity by operation and status within a bounded window."""
    with cli_errors(json_error=True):
        print_logs(log_analytics.query_logs(workspace_id, hours, limit, summarize=True))


if __name__ == "__main__":
    app()
