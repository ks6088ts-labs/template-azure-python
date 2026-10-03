"""Send and receive Azure Event Hubs quickstart events using passwordless authentication."""

from typing import Annotated

import typer

from scripts._cli import cli_errors, print_json
from template_azure_python.internals.azure import event_hubs

DEFAULT_MESSAGES = ("First event", "Second event", "Third event")
DEFAULT_CONSUMER_GROUP = "$Default"
DEFAULT_MAX_EVENTS = 100
MAX_EVENTS = 10_000
DEFAULT_MAX_WAIT_TIME = 15.0

app = typer.Typer(
    add_completion=False,
    help="Run the Azure Event Hubs quickstart with passwordless Azure authentication. Run `az login` first.",
    no_args_is_help=True,
    rich_markup_mode="markdown",
)

NamespaceOption = Annotated[
    str | None,
    typer.Option(
        "--fully-qualified-namespace",
        help="Namespace hostname. Reads AZURE_EVENT_HUBS_FULLY_QUALIFIED_NAMESPACE when omitted.",
    ),
]
EventHubOption = Annotated[
    str | None, typer.Option("--event-hub", help="Existing event hub. Reads AZURE_EVENT_HUB_NAME when omitted.")
]
ConsumerGroupOption = Annotated[
    str | None,
    typer.Option(
        "--consumer-group",
        help="Reads AZURE_EVENT_HUB_CONSUMER_GROUP when omitted. No checkpoints are written.",
        show_default=DEFAULT_CONSUMER_GROUP,
    ),
]
MessageOption = Annotated[
    list[str] | None,
    typer.Option("--message", help="Event body; repeat for a batch. Defaults to three tutorial events."),
]
MaxEventsOption = Annotated[
    int, typer.Option("--max-events", min=1, max=MAX_EVENTS, help="Maximum total events across all partitions.")
]
MaxWaitTimeOption = Annotated[
    float, typer.Option("--max-wait-time", help="Positive finite global idle timeout; resets on each event.")
]
StartingPositionOption = Annotated[
    str, typer.Option("--starting-position", help="Starting offset: -1 for the beginning, @latest for new events.")
]


@app.command()
def send_events(
    fully_qualified_namespace: NamespaceOption = None, event_hub: EventHubOption = None, message: MessageOption = None
) -> None:
    """Send one SDK batch containing the tutorial events or the supplied messages."""
    with cli_errors():
        print_json(
            event_hubs.send_events(
                fully_qualified_namespace, event_hub, list(DEFAULT_MESSAGES) if message is None else message
            )
        )


@app.command()
def receive_events(
    fully_qualified_namespace: NamespaceOption = None,
    event_hub: EventHubOption = None,
    consumer_group: ConsumerGroupOption = None,
    max_events: MaxEventsOption = DEFAULT_MAX_EVENTS,
    max_wait_time: MaxWaitTimeOption = DEFAULT_MAX_WAIT_TIME,
    starting_position: StartingPositionOption = "-1",
) -> None:
    """Read events non-destructively as JSON lines, followed by a received-count summary."""
    with cli_errors():
        received = event_hubs.receive_events(
            fully_qualified_namespace,
            event_hub,
            consumer_group,
            max_events,
            max_wait_time,
            starting_position,
            print_json,
        )
        print_json({"received": received})


if __name__ == "__main__":
    app()
