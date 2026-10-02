"""Send and receive Azure Event Hubs quickstart events using passwordless authentication."""

import asyncio
import math
from typing import Annotated

import typer
from azure.eventhub import EventData, EventHubProducerClient
from azure.eventhub.aio import EventHubConsumerClient, PartitionContext
from dotenv import load_dotenv

from scripts._azure_messaging import async_managed_client, managed_client, print_json, validate_name, validate_namespace

DEFAULT_MESSAGES = ("First event", "Second event", "Third event")
DEFAULT_CONSUMER_GROUP = "$Default"
DEFAULT_MAX_EVENTS = 100
MAX_EVENTS = 10_000
DEFAULT_MAX_WAIT_TIME = 5.0

app = typer.Typer(
    add_completion=False,
    help="Run the Azure Event Hubs quickstart with passwordless Azure authentication. Run `az login` first.",
    no_args_is_help=True,
    rich_markup_mode="markdown",
)

NamespaceOption = Annotated[
    str,
    typer.Option(
        "--fully-qualified-namespace",
        envvar="AZURE_EVENT_HUBS_FULLY_QUALIFIED_NAMESPACE",
        help="Event Hubs namespace hostname, without a scheme or path.",
        show_envvar=True,
    ),
]
EventHubOption = Annotated[
    str,
    typer.Option("--event-hub", envvar="AZURE_EVENT_HUB_NAME", help="Existing event hub name.", show_envvar=True),
]
ConsumerGroupOption = Annotated[
    str,
    typer.Option(
        "--consumer-group",
        envvar="AZURE_EVENT_HUB_CONSUMER_GROUP",
        help="Existing consumer group. No checkpoints are written.",
        show_envvar=True,
    ),
]
MessageOption = Annotated[
    list[str] | None,
    typer.Option(
        "--message", help="Event body; repeat to send multiple events in one batch. Defaults to three tutorial events."
    ),
]
MaxEventsOption = Annotated[
    int,
    typer.Option("--max-events", min=1, max=MAX_EVENTS, help="Maximum total events across all partitions."),
]
MaxWaitTimeOption = Annotated[
    float,
    typer.Option("--max-wait-time", help="Positive, finite global idle timeout in seconds; resets on each event."),
]
StartingPositionOption = Annotated[
    str,
    typer.Option("--starting-position", help="Starting offset: -1 for the beginning, @latest for new events."),
]


@app.command()
def send_events(
    fully_qualified_namespace: NamespaceOption,
    event_hub: EventHubOption,
    message: MessageOption = None,
) -> None:
    """Send one SDK batch containing the tutorial events or the supplied messages."""
    namespace = validate_namespace(fully_qualified_namespace)
    event_hub = validate_name(event_hub, "--event-hub")
    messages = list(DEFAULT_MESSAGES) if message is None else message
    with managed_client(
        "Azure Event Hubs",
        lambda credential: EventHubProducerClient(
            fully_qualified_namespace=namespace, eventhub_name=event_hub, credential=credential
        ),
    ) as producer:
        batch = producer.create_batch()
        for body in messages:
            try:
                batch.add(EventData(body))
            except ValueError as exc:
                raise typer.BadParameter(
                    f"messages must fit in one Event Hubs batch: {exc}", param_hint="--message"
                ) from exc
        producer.send_batch(batch)
    print_json({"sent": len(messages)})


async def _receive_bounded(
    consumer: EventHubConsumerClient, max_events: int, max_wait_time: float, starting_position: str
) -> int:
    loop = asyncio.get_running_loop()
    changed = asyncio.Event()
    deadline = loop.time() + max_wait_time
    received = 0
    failure: Exception | None = None
    stopped = False

    async def on_error(_partition: PartitionContext | None, error: Exception) -> None:
        nonlocal failure
        if failure is None:
            failure = error
        changed.set()

    async def on_event(partition: PartitionContext, event: EventData | None) -> None:
        nonlocal received, deadline
        if stopped or failure is not None or received >= max_events or loop.time() >= deadline or event is None:
            return
        try:
            print_json(
                {
                    "body": event.body_as_str(),
                    "partition_id": partition.partition_id,
                    "offset": event.offset,
                    "sequence_number": event.sequence_number,
                    "enqueued_time": event.enqueued_time,
                }
            )
        except Exception as exc:
            await on_error(partition, exc)
            return
        received += 1
        deadline = loop.time() + max_wait_time
        changed.set()

    receiving = asyncio.create_task(
        consumer.receive(
            on_event=on_event,
            on_error=on_error,
            starting_position=starting_position,
            max_wait_time=max_wait_time,
        )
    )
    receiving.add_done_callback(lambda _task: changed.set())
    try:
        while received < max_events and failure is None and not receiving.done():
            changed.clear()
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                await asyncio.wait_for(changed.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                break
    finally:
        stopped = True
        # Cancel outside SDK callbacks: receive's finally stops and joins partition tasks.
        # Unlike SDK max_wait_time, this also bounds discovery and zero-partition waits.
        receiving.cancel()
        try:
            await receiving
        except asyncio.CancelledError:
            pass
    if failure is not None:
        raise failure
    return received


async def _receive_events(
    namespace: str, event_hub: str, consumer_group: str, max_events: int, max_wait_time: float, starting_position: str
) -> int:
    async with async_managed_client(
        "Azure Event Hubs",
        lambda credential: EventHubConsumerClient(
            fully_qualified_namespace=namespace,
            eventhub_name=event_hub,
            consumer_group=consumer_group,
            credential=credential,
        ),
    ) as consumer:
        return await _receive_bounded(consumer, max_events, max_wait_time, starting_position)


@app.command()
def receive_events(
    fully_qualified_namespace: NamespaceOption,
    event_hub: EventHubOption,
    consumer_group: ConsumerGroupOption = DEFAULT_CONSUMER_GROUP,
    max_events: MaxEventsOption = DEFAULT_MAX_EVENTS,
    max_wait_time: MaxWaitTimeOption = DEFAULT_MAX_WAIT_TIME,
    starting_position: StartingPositionOption = "-1",
) -> None:
    """Read events non-destructively as JSON lines, followed by a received-count summary."""
    namespace = validate_namespace(fully_qualified_namespace)
    event_hub = validate_name(event_hub, "--event-hub")
    consumer_group = validate_name(consumer_group, "--consumer-group")
    if not math.isfinite(max_wait_time) or max_wait_time <= 0:
        raise typer.BadParameter("must be a positive, finite number", param_hint="--max-wait-time")
    if not starting_position.strip():
        raise typer.BadParameter("must not be empty", param_hint="--starting-position")
    received = asyncio.run(
        _receive_events(namespace, event_hub, consumer_group, max_events, max_wait_time, starting_position)
    )
    print_json({"received": received})


if __name__ == "__main__":
    load_dotenv(override=False)
    app()
