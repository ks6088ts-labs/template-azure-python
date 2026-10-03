import asyncio
import math
from collections.abc import Callable

from azure.eventhub import EventData, EventHubProducerClient
from azure.eventhub.aio import EventHubConsumerClient, PartitionContext

from template_azure_python.internals.azure._common import (
    InputError,
    async_managed_client,
    managed_client,
    required_value,
    validate_name,
    validate_namespace,
)
from template_azure_python.settings import get_azure_settings


def _resources(namespace: str | None, event_hub: str | None) -> tuple[str, str]:
    settings = get_azure_settings()
    return (
        validate_namespace(
            required_value(namespace, settings.event_hubs.fully_qualified_namespace, "--fully-qualified-namespace")
        ),
        validate_name(required_value(event_hub, settings.event_hubs.name, "--event-hub"), "--event-hub"),
    )


def send_events(namespace: str | None, event_hub: str | None, messages: list[str]) -> dict[str, object]:
    namespace, event_hub = _resources(namespace, event_hub)
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
                raise InputError(f"messages must fit in one Event Hubs batch: {exc}", "--message") from exc
        producer.send_batch(batch)
    return {"sent": len(messages)}


async def _receive_bounded(
    consumer: EventHubConsumerClient,
    max_events: int,
    max_wait_time: float,
    starting_position: str,
    emit: Callable[[dict[str, object]], None],
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
            emit(
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
            on_event=on_event, on_error=on_error, starting_position=starting_position, max_wait_time=max_wait_time
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
        # Cancel outside SDK callbacks so receive can stop and join partition tasks.
        receiving.cancel()
        try:
            await receiving
        except asyncio.CancelledError:
            pass
    if failure is not None:
        raise failure
    return received


async def _receive_events(
    namespace: str,
    event_hub: str,
    consumer_group: str,
    max_events: int,
    max_wait_time: float,
    starting_position: str,
    emit: Callable[[dict[str, object]], None],
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
        return await _receive_bounded(consumer, max_events, max_wait_time, starting_position, emit)


def receive_events(
    namespace: str | None,
    event_hub: str | None,
    consumer_group: str | None,
    max_events: int,
    max_wait_time: float,
    starting_position: str,
    emit: Callable[[dict[str, object]], None],
) -> int:
    namespace, event_hub = _resources(namespace, event_hub)
    consumer_group = validate_name(
        required_value(consumer_group, get_azure_settings().event_hubs.consumer_group, "--consumer-group"),
        "--consumer-group",
    )
    if not math.isfinite(max_wait_time) or max_wait_time <= 0:
        raise InputError("must be a positive, finite number", "--max-wait-time")
    if not starting_position.strip():
        raise InputError("must not be empty", "--starting-position")
    return asyncio.run(
        _receive_events(namespace, event_hub, consumer_group, max_events, max_wait_time, starting_position, emit)
    )
