"""Publish Azure Event Grid quickstart events using Azure authentication."""

from typing import Annotated

import typer

from scripts._cli import cli_errors, print_json
from template_azure_python.internals.azure import event_grid
from template_azure_python.internals.azure.event_grid import EventSchema

DEFAULT_SUBJECT = "Door1"
DEFAULT_SOURCE = "/myresource"
DEFAULT_EVENT_TYPE = "Contoso.Items.ItemReceived"
DEFAULT_DATA = '{"message": "Hello, Event Grid!"}'
DEFAULT_DATA_VERSION = "1.0"
DEFAULT_COUNT = 3

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
    str | None,
    typer.Option(
        "--endpoint",
        help="HTTPS Event Grid topic endpoint. Reads AZURE_EVENT_GRID_TOPIC_ENDPOINT when omitted.",
        metavar="URL",
    ),
]
SchemaOption = Annotated[
    EventSchema, typer.Option("--schema", help="Event schema configured on the topic.", show_default=True)
]
SubjectOption = Annotated[str, typer.Option("--subject", help="Subject of the event.", show_default=True)]
SourceOption = Annotated[str, typer.Option("--source", help="Source URI reference for CloudEvents.", show_default=True)]
EventTypeOption = Annotated[str, typer.Option("--event-type", help="Type of the event.", show_default=True)]
DataOption = Annotated[str, typer.Option("--data", help="Event payload as a JSON object.", show_default=True)]
DataVersionOption = Annotated[
    str, typer.Option("--data-version", help="Payload version for the Event Grid schema only.", show_default=True)
]
CountOption = Annotated[
    int, typer.Option("--count", min=1, help="Number of events to publish in one request.", show_default=True)
]


@app.command()
def publish_event(
    endpoint: EndpointOption = None,
    schema: SchemaOption = EventSchema.EVENT_GRID,
    subject: SubjectOption = DEFAULT_SUBJECT,
    source: SourceOption = DEFAULT_SOURCE,
    event_type: EventTypeOption = DEFAULT_EVENT_TYPE,
    data: DataOption = DEFAULT_DATA,
    data_version: DataVersionOption = DEFAULT_DATA_VERSION,
) -> None:
    """Publish one event to an existing topic."""
    with cli_errors():
        print_json(
            event_grid.publish(endpoint, schema, subject, source, event_type, data, data_version, 1, multiple=False)
        )


@app.command()
def publish_events(
    endpoint: EndpointOption = None,
    schema: SchemaOption = EventSchema.EVENT_GRID,
    subject: SubjectOption = DEFAULT_SUBJECT,
    source: SourceOption = DEFAULT_SOURCE,
    event_type: EventTypeOption = DEFAULT_EVENT_TYPE,
    data: DataOption = DEFAULT_DATA,
    data_version: DataVersionOption = DEFAULT_DATA_VERSION,
    count: CountOption = DEFAULT_COUNT,
) -> None:
    """Publish multiple events in a single request."""
    with cli_errors():
        print_json(
            event_grid.publish(endpoint, schema, subject, source, event_type, data, data_version, count, multiple=True)
        )


if __name__ == "__main__":
    app()
