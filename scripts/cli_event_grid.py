"""Publish Azure Event Grid quickstart events using Azure authentication."""

# Usage:
#   cp .env.template .env
#   az login
#   uv run --locked python -m scripts.cli_event_grid --help
#   uv run --locked python -m scripts.cli_event_grid publish-event
#   uv run --locked python -m scripts.cli_event_grid publish-events --schema cloud-event --count 3

from enum import Enum
from typing import Annotated

import typer
from azure.core.messaging import CloudEvent
from azure.eventgrid import EventGridEvent, EventGridPublisherClient
from dotenv import load_dotenv

from scripts._azure_messaging import (
    managed_client,
    print_json,
    validate_endpoint,
    validate_json_object,
    validate_name,
)

DEFAULT_SUBJECT = "Door1"
DEFAULT_SOURCE = "/myresource"
DEFAULT_EVENT_TYPE = "Contoso.Items.ItemReceived"
DEFAULT_DATA = '{"message": "Hello, Event Grid!"}'
DEFAULT_DATA_VERSION = "1.0"
DEFAULT_COUNT = 3


class EventSchema(str, Enum):
    EVENT_GRID = "event-grid"
    CLOUD_EVENT = "cloud-event"


app = typer.Typer(
    add_completion=False,
    help=(
        "Publish Azure Event Grid quickstart events with Azure authentication. "
        "Set AZURE_EVENT_GRID_TOPIC_ENDPOINT in .env and run `az login` before using a command. "
        "The topic must accept the selected event schema."
    ),
    no_args_is_help=True,
    rich_markup_mode="markdown",
)

EndpointOption = Annotated[
    str,
    typer.Option(
        "--endpoint",
        envvar="AZURE_EVENT_GRID_TOPIC_ENDPOINT",
        help="HTTPS Event Grid topic endpoint, optionally including /api/events.",
        metavar="URL",
        show_envvar=True,
    ),
]
SchemaOption = Annotated[
    EventSchema,
    typer.Option("--schema", help="Event schema configured on the topic.", show_default=True),
]
SubjectOption = Annotated[
    str,
    typer.Option("--subject", help="Subject of the event.", show_default=True),
]
SourceOption = Annotated[
    str,
    typer.Option("--source", help="Source URI reference for CloudEvents.", show_default=True),
]
EventTypeOption = Annotated[
    str,
    typer.Option("--event-type", help="Type of the event.", show_default=True),
]
DataOption = Annotated[
    str,
    typer.Option("--data", help="Event payload as a JSON object.", show_default=True),
]
DataVersionOption = Annotated[
    str,
    typer.Option("--data-version", help="Payload version for the Event Grid schema only.", show_default=True),
]
CountOption = Annotated[
    int,
    typer.Option("--count", min=1, help="Number of events to publish in one request.", show_default=True),
]


def _publish(
    endpoint: str,
    schema: EventSchema,
    subject: str,
    source: str,
    event_type: str,
    data: str,
    data_version: str,
    count: int,
    *,
    multiple: bool,
) -> None:
    endpoint = validate_endpoint(endpoint, allow_path=True)
    subject = validate_name(subject, "--subject")
    source = validate_name(source, "--source")
    event_type = validate_name(event_type, "--event-type")
    data_version = validate_name(data_version, "--data-version")
    payload = validate_json_object(data)
    events: list[EventGridEvent | CloudEvent] = []
    for _ in range(count):
        if schema == EventSchema.CLOUD_EVENT:
            events.append(
                CloudEvent(
                    source=source,
                    type=event_type,
                    subject=subject,
                    data=payload,
                    datacontenttype="application/json",
                )
            )
        else:
            events.append(
                EventGridEvent(
                    subject=subject,
                    event_type=event_type,
                    data=payload,
                    data_version=data_version,
                )
            )

    with managed_client(
        "Event Grid",
        lambda credential: EventGridPublisherClient(endpoint=endpoint, credential=credential),
    ) as client:
        client.send(events if multiple else events[0])

    print_json({"schema": schema.value, "count": len(events), "ids": [event.id for event in events]})


@app.command()
def publish_event(
    endpoint: EndpointOption,
    schema: SchemaOption = EventSchema.EVENT_GRID,
    subject: SubjectOption = DEFAULT_SUBJECT,
    source: SourceOption = DEFAULT_SOURCE,
    event_type: EventTypeOption = DEFAULT_EVENT_TYPE,
    data: DataOption = DEFAULT_DATA,
    data_version: DataVersionOption = DEFAULT_DATA_VERSION,
) -> None:
    """Publish one event to an existing topic."""
    _publish(endpoint, schema, subject, source, event_type, data, data_version, 1, multiple=False)


@app.command()
def publish_events(
    endpoint: EndpointOption,
    schema: SchemaOption = EventSchema.EVENT_GRID,
    subject: SubjectOption = DEFAULT_SUBJECT,
    source: SourceOption = DEFAULT_SOURCE,
    event_type: EventTypeOption = DEFAULT_EVENT_TYPE,
    data: DataOption = DEFAULT_DATA,
    data_version: DataVersionOption = DEFAULT_DATA_VERSION,
    count: CountOption = DEFAULT_COUNT,
) -> None:
    """Publish multiple events in a single request."""
    _publish(endpoint, schema, subject, source, event_type, data, data_version, count, multiple=True)


if __name__ == "__main__":
    load_dotenv(override=False)
    app()
