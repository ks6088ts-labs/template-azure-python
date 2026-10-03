"""Read bounded samples from the live Azure Activity Log management API."""

from typing import Annotated

import typer

from scripts._cli import cli_errors, print_json
from template_azure_python.internals.azure import activity_log

app = typer.Typer(
    add_completion=False,
    help=(
        "Read the live Azure Activity Log using passwordless authentication (`az login`). "
        "This management API does not query Activity Log exports in Log Analytics. "
        "Results and summaries describe only a bounded sample, not all matching events."
    ),
    no_args_is_help=True,
    rich_markup_mode="markdown",
)
SubscriptionOption = Annotated[
    str | None, typer.Option("--subscription-id", help="Subscription UUID. Reads AZURE_SUBSCRIPTION_ID when omitted.")
]
ResourceGroupOption = Annotated[
    str | None,
    typer.Option(
        "--resource-group",
        help=(
            "Optional group: 1-90 ASCII letters, digits, _, (, ), -, or .; no trailing dot. Reads AZURE_RESOURCE_GROUP."
        ),
    ),
]
HoursOption = Annotated[int, typer.Option("--hours", min=1, max=168, help="UTC lookback in hours.")]
LimitOption = Annotated[
    int,
    typer.Option("--limit", min=1, max=1000, help="Maximum events consumed from the SDK iterator, not a total count."),
]


@app.command()
def list_events(
    subscription_id: SubscriptionOption = None,
    resource_group: ResourceGroupOption = None,
    hours: HoursOption = 24,
    limit: LimitOption = 100,
) -> None:
    """JSON: {start_time, end_time, limit, sample_count, events}.

    UTC times delimit the request. Each event has event_data_id, event_timestamp,
    resource_id, resource_group_name, operation_name, status, level; absent fields
    are null. Empty events is success. Only the first limit events are consumed.
    """
    with cli_errors():
        print_json(activity_log.list_events(subscription_id, resource_group, hours, limit))


@app.command()
def summarize_events(
    subscription_id: SubscriptionOption = None,
    resource_group: ResourceGroupOption = None,
    hours: HoursOption = 24,
    limit: LimitOption = 100,
) -> None:
    """JSON: {start_time, end_time, limit, sample_count, by_status, by_operation}.

    Counts cover only the bounded sample, NOT the full population. Group maps
    contain string keys and integer counts; missing values use "(unknown)".
    An empty sample returns empty maps. UTC times delimit the request.
    """
    with cli_errors():
        print_json(activity_log.summarize_events(subscription_id, resource_group, hours, limit))


if __name__ == "__main__":
    app()
