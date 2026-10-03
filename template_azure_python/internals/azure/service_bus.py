import math
from collections.abc import Callable, Generator
from contextlib import closing, contextmanager

from azure.servicebus import ServiceBusClient, ServiceBusMessage, ServiceBusReceiveMode

from template_azure_python.internals.azure._common import (
    InputError,
    OperationError,
    managed_client,
    required_value,
    validate_name,
    validate_namespace,
)
from template_azure_python.settings import get_azure_settings

SERVICE = "Azure Service Bus"


@contextmanager
def _queue_client(namespace: str | None, queue: str | None) -> Generator[tuple[str, ServiceBusClient], None, None]:
    settings = get_azure_settings()
    namespace = validate_namespace(
        required_value(namespace, settings.azure_service_bus_fully_qualified_namespace, "--fully-qualified-namespace")
    )
    queue = validate_name(required_value(queue, settings.azure_service_bus_queue_name, "--queue"), "--queue")
    with managed_client(
        SERVICE, lambda credential: ServiceBusClient(fully_qualified_namespace=namespace, credential=credential)
    ) as client:
        yield queue, client


def send_message(namespace: str | None, queue: str | None, message: str) -> dict[str, object]:
    with _queue_client(namespace, queue) as (name, client):
        with closing(client.get_queue_sender(queue_name=name)) as sender:
            sender.send_messages(ServiceBusMessage(message))
    return {"sent": 1}


def send_message_list(namespace: str | None, queue: str | None, message: str, count: int) -> dict[str, object]:
    with _queue_client(namespace, queue) as (name, client):
        with closing(client.get_queue_sender(queue_name=name)) as sender:
            sender.send_messages([ServiceBusMessage(message) for _ in range(count)])
    return {"sent": count}


def send_message_batch(namespace: str | None, queue: str | None, message: str, count: int) -> dict[str, object]:
    with _queue_client(namespace, queue) as (name, client):
        with closing(client.get_queue_sender(queue_name=name)) as sender:
            batch = sender.create_message_batch()
            for _ in range(count):
                try:
                    batch.add_message(ServiceBusMessage(message))
                except ValueError as exc:
                    raise OperationError(
                        f"{SERVICE} batch overflow; no messages were sent. Reduce --count or --message size."
                    ) from exc
            sender.send_messages(batch)
    return {"sent": count}


def receive_messages(
    namespace: str | None,
    queue: str | None,
    max_messages: int,
    max_wait_time: float,
    emit: Callable[[dict[str, object]], None],
) -> int:
    if not math.isfinite(max_wait_time) or max_wait_time <= 0:
        raise InputError("must be positive and finite", "--max-wait-time")
    received = 0
    with _queue_client(namespace, queue) as (name, client):
        with closing(
            client.get_queue_receiver(queue_name=name, receive_mode=ServiceBusReceiveMode.PEEK_LOCK)
        ) as receiver:
            messages = receiver.receive_messages(max_message_count=max_messages, max_wait_time=max_wait_time)
            for message in messages:
                emit(
                    {
                        "body": str(message),
                        "message_id": message.message_id,
                        "correlation_id": message.correlation_id,
                        "content_type": message.content_type,
                        "sequence_number": message.sequence_number,
                        "enqueued_time_utc": message.enqueued_time_utc,
                        "delivery_count": message.delivery_count,
                        "lock_token": message.lock_token,
                    }
                )
                receiver.complete_message(message)
                received += 1
    return received
