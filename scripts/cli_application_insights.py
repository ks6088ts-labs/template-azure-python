"""Emit one bounded telemetry run or query an Application Insights resource."""

from typing import Annotated

import typer

from scripts._cli import cli_errors, print_json, print_logs
from template_azure_python.internals.azure import application_insights
from template_azure_python.internals.azure.application_insights import TelemetryTable

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=(
        "Query with AZURE_APPLICATION_INSIGHTS_ID and `az login`. "
        "Emit with APPLICATIONINSIGHTS_CONNECTION_STRING from settings (.env or the environment), never a CLI argument."
    ),
)
ResourceOption = Annotated[
    str | None, typer.Option("--resource-id", help="ARM ID. Reads AZURE_APPLICATION_INSIGHTS_ID when omitted.")
]
HoursOption = Annotated[int, typer.Option("--hours", min=1, max=168)]
LimitOption = Annotated[int, typer.Option("--limit", min=1, max=1000)]
TableOption = Annotated[
    TelemetryTable, typer.Option("--table", help="Workspace table alias mapped to the Application Insights schema.")
]
RunOption = Annotated[str | None, typer.Option("--run-id", help="Filter the generated run UUID.")]
CountOption = Annotated[int, typer.Option("--count", min=1, max=100)]


@app.command()
def query_telemetry(
    resource_id: ResourceOption = None,
    table: TableOption = TelemetryTable.REQUESTS,
    hours: HoursOption = 24,
    limit: LimitOption = 100,
    run_id: RunOption = None,
) -> None:
    """Run a bounded resource-centric query, optionally filtered to an emitted run."""
    with cli_errors(json_error=True):
        print_logs(application_insights.query_telemetry(resource_id, table, hours, limit, run_id))


@app.command()
def emit_telemetry(count: CountOption = 10) -> None:
    """Emit once. Provider flushing does not guarantee acceptance, persistence or ingestion."""
    with cli_errors():
        output = application_insights.emit_telemetry(count)
        print_json(output)
        if "failures" in output:
            raise typer.Exit(1)


if __name__ == "__main__":
    app()
