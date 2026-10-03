"""Read Azure Monitor Workspace metadata and managed Prometheus metrics."""

from typing import Annotated

import typer

from scripts._cli import cli_errors, print_json
from template_azure_python.internals.azure import azure_monitor

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Read Azure Monitor Workspace (managed Prometheus, not Log Analytics). No collector means empty results.",
)
ResourceIdOption = Annotated[
    str | None,
    typer.Option("--resource-id", help="ARM resource ID. Reads AZURE_MONITOR_ID when omitted."),
]
QueryOption = Annotated[str, typer.Option("--query", help="Instant PromQL expression (maximum 4096 characters).")]


@app.command()
def show_workspace(resource_id: ResourceIdOption = None) -> None:
    """Look up workspace metadata using management-plane reader access."""
    with cli_errors():
        print_json(azure_monitor.show_workspace(resource_id))


@app.command()
def query_prometheus(resource_id: ResourceIdOption = None, query: QueryOption = "up") -> None:
    """Run one read-only instant query; an empty result is successful."""
    with cli_errors():
        output = azure_monitor.query_prometheus(resource_id, query)
        print_json(output)
        if output["status"] == "error":
            raise typer.Exit(1)


if __name__ == "__main__":
    app()
