from collections.abc import Generator
from contextlib import contextmanager
from itertools import islice

from azure.storage.queue import QueueClient, QueueMessage

from template_azure_python.internals.azure._common import (
    managed_client,
    required_value,
    validate_endpoint,
    validate_name,
)
from template_azure_python.settings import get_azure_settings


def resolve_queue(endpoint: str | None, queue: str | None) -> tuple[str, str]:
    settings = get_azure_settings()
    return (
        validate_endpoint(required_value(endpoint, settings.queue_storage.endpoint, "--endpoint")),
        validate_name(required_value(queue, settings.queue_storage.queue_name, "--queue"), "--queue"),
    )


@contextmanager
def _queue_client(endpoint: str | None, queue: str | None) -> Generator[tuple[str, QueueClient], None, None]:
    endpoint, queue = resolve_queue(endpoint, queue)
    with managed_client(
        "Azure Queue Storage",
        lambda credential: QueueClient(account_url=endpoint, queue_name=queue, credential=credential),
    ) as client:
        yield queue, client


def _message_json(message: QueueMessage) -> dict[str, object]:
    return {
        field: value
        for field in ("content", "id", "pop_receipt", "inserted_on", "expires_on", "next_visible_on", "dequeue_count")
        if (value := getattr(message, field, None)) is not None
    }


def create_queue(endpoint: str | None, queue: str | None) -> dict[str, object]:
    with _queue_client(endpoint, queue) as (name, client):
        client.create_queue()
    return {"queue": name, "created": True}


def send_message(endpoint: str | None, queue: str | None, message: str, visibility_timeout: int) -> dict[str, object]:
    with _queue_client(endpoint, queue) as (_, client):
        return _message_json(client.send_message(content=message, visibility_timeout=visibility_timeout))


def peek_messages(endpoint: str | None, queue: str | None, max_messages: int) -> list[dict[str, object]]:
    with _queue_client(endpoint, queue) as (_, client):
        return [_message_json(message) for message in client.peek_messages(max_messages=max_messages)]


def update_message(
    endpoint: str | None,
    queue: str | None,
    message: str,
    message_id: str,
    pop_receipt: str,
    visibility_timeout: int,
) -> dict[str, object]:
    message_id = validate_name(message_id, "--message-id")
    pop_receipt = validate_name(pop_receipt, "--pop-receipt")
    with _queue_client(endpoint, queue) as (_, client):
        return _message_json(
            client.update_message(
                message=message_id, pop_receipt=pop_receipt, content=message, visibility_timeout=visibility_timeout
            )
        )


def get_queue_length(endpoint: str | None, queue: str | None) -> dict[str, object]:
    with _queue_client(endpoint, queue) as (name, client):
        properties = client.get_queue_properties()
    return {"queue": name, "approximate_message_count": properties.approximate_message_count}


def receive_messages(
    endpoint: str | None, queue: str | None, max_messages: int, visibility_timeout: int
) -> dict[str, object]:
    with _queue_client(endpoint, queue) as (_, client):
        messages = client.receive_messages(
            messages_per_page=max_messages, max_messages=max_messages, visibility_timeout=visibility_timeout
        )
        results = [_message_json(message) for message in islice(messages, max_messages)]
    return {"received": len(results), "messages": results}


def delete_message(endpoint: str | None, queue: str | None, message_id: str, pop_receipt: str) -> dict[str, object]:
    message_id = validate_name(message_id, "--message-id")
    pop_receipt = validate_name(pop_receipt, "--pop-receipt")
    with _queue_client(endpoint, queue) as (name, client):
        client.delete_message(message=message_id, pop_receipt=pop_receipt)
    return {"queue": name, "id": message_id, "deleted": True}


def delete_queue(endpoint: str | None, queue: str | None) -> dict[str, object]:
    with _queue_client(endpoint, queue) as (name, client):
        client.delete_queue()
    return {"queue": name, "deleted": True}
