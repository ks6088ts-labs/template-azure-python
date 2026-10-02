"""Read bounded samples from the live Azure Activity Log management API."""

import re
from collections import Counter
from contextlib import closing
from datetime import datetime, timedelta, timezone
from itertools import islice
from typing import Annotated

import typer
from azure.core.exceptions import AzureError
from azure.identity import DefaultAzureCredential
from azure.mgmt.monitor import MonitorManagementClient
from azure.mgmt.monitor.models import EventData
from dotenv import load_dotenv

from scripts._azure_messaging import print_json
from scripts._azure_observability import validate_guid

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
HoursOption = Annotated[int, typer.Option("--hours", min=1, max=168, help="UTC lookback in hours.")]
LimitOption = Annotated[
    int,
    typer.Option("--limit", min=1, max=1000, help="Maximum events consumed from the SDK iterator, not a total count."),
]


def _event_record(event: EventData) -> dict[str, object]:
    return {
        "event_data_id": event.event_data_id,
        "event_timestamp": event.event_timestamp,
        "resource_id": event.resource_id,
        "resource_group_name": event.resource_group_name,
        "operation_name": event.operation_name.value if event.operation_name is not None else None,
        "status": event.status.value if event.status is not None else None,
        "level": event.level,
    }


def _read_events(
    subscription_id: str, resource_group: str | None, hours: int, limit: int
) -> tuple[list[dict[str, object]], dict[str, object]]:
    subscription_id = validate_guid(subscription_id)
    if resource_group is not None and (
        re.fullmatch(r"[A-Za-z0-9_().-]{1,90}", resource_group) is None or resource_group.endswith(".")
    ):
        raise typer.BadParameter("must be a valid resource group name", param_hint="--resource-group")
    if not 1 <= hours <= 168:
        raise typer.BadParameter("must be between 1 and 168", param_hint="--hours")
    if not 1 <= limit <= 1000:
        raise typer.BadParameter("must be between 1 and 1000", param_hint="--limit")
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=hours)
    start = start_time.isoformat().replace("+00:00", "Z")
    end = end_time.isoformat().replace("+00:00", "Z")
    filter_expression = f"eventTimestamp ge '{start}' and eventTimestamp le '{end}'"
    if resource_group is not None:
        filter_expression += f" and resourceGroupName eq '{resource_group}'"
    try:
        with closing(DefaultAzureCredential()) as credential:
            with closing(MonitorManagementClient(credential=credential, subscription_id=subscription_id)) as client:
                events = [
                    _event_record(event) for event in islice(client.activity_logs.list(filter=filter_expression), limit)
                ]
    except AzureError:
        typer.echo("Error: Azure Activity Log request failed. Check Azure authentication and Reader access.", err=True)
        raise typer.Exit(code=1) from None
    return events, {"start_time": start, "end_time": end, "limit": limit, "sample_count": len(events)}


@app.command()
def list_events(
    subscription_id: SubscriptionOption,
    resource_group: ResourceGroupOption = None,
    hours: HoursOption = 24,
    limit: LimitOption = 100,
) -> None:
    """JSON: {start_time, end_time, limit, sample_count, events}.

    UTC times delimit the request. Each event has event_data_id, event_timestamp,
    resource_id, resource_group_name, operation_name, status, level; absent fields
    are null. Empty events is success. Only the first limit events are consumed.
    """
    events, metadata = _read_events(subscription_id, resource_group, hours, limit)
    print_json({**metadata, "events": events})


@app.command()
def summarize_events(
    subscription_id: SubscriptionOption,
    resource_group: ResourceGroupOption = None,
    hours: HoursOption = 24,
    limit: LimitOption = 100,
) -> None:
    """JSON: {start_time, end_time, limit, sample_count, by_status, by_operation}.

    Counts cover only the bounded sample, NOT the full population. Group maps
    contain string keys and integer counts; missing values use "(unknown)".
    An empty sample returns empty maps. UTC times delimit the request.
    """
    events, metadata = _read_events(subscription_id, resource_group, hours, limit)
    print_json(
        {
            **metadata,
            "by_status": dict(Counter(str(event["status"] or "(unknown)") for event in events)),
            "by_operation": dict(Counter(str(event["operation_name"] or "(unknown)") for event in events)),
        }
    )


if __name__ == "__main__":
    load_dotenv(override=False)
    app()
