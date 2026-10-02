"""Run Azure Queue Storage quickstart operations with passwordless authentication."""

# Usage:
#   az login
#   uv run --locked python -m scripts.cli_queue_storage --help

from collections.abc import Generator
from contextlib import contextmanager
from itertools import islice
from typing import Annotated

import typer
from azure.storage.queue import QueueClient, QueueMessage
from dotenv import load_dotenv

from scripts._azure_messaging import (
    confirm_delete,
    managed_client,
    print_json,
    validate_endpoint,
    validate_name,
)

DEFAULT_MESSAGE = "First message"

app = typer.Typer(
    add_completion=False,
    help=(
        "Run Azure Queue Storage quickstart operations using DefaultAzureCredential. "
        "Set AZURE_QUEUE_STORAGE_ENDPOINT and AZURE_QUEUE_STORAGE_QUEUE_NAME in .env, then run `az login`."
    ),
    no_args_is_help=True,
    rich_markup_mode="markdown",
)

EndpointOption = Annotated[
    str,
    typer.Option(
        "--endpoint",
        envvar="AZURE_QUEUE_STORAGE_ENDPOINT",
        help="HTTPS Queue Storage account endpoint.",
        show_envvar=True,
    ),
]
QueueOption = Annotated[
    str,
    typer.Option(
        "--queue",
        envvar="AZURE_QUEUE_STORAGE_QUEUE_NAME",
        help="Queue name.",
        show_envvar=True,
    ),
]
MessageOption = Annotated[str, typer.Option("--message", help="Message content.")]
MessageIdOption = Annotated[str, typer.Option("--message-id", help="Message ID returned by the service.")]
PopReceiptOption = Annotated[str, typer.Option("--pop-receipt", help="Latest pop receipt returned by the service.")]
VisibilityOption = Annotated[
    int,
    typer.Option("--visibility-timeout", min=0, max=604800, help="Message invisibility duration in seconds."),
]
ReceiveVisibilityOption = Annotated[
    int,
    typer.Option("--visibility-timeout", min=1, max=604800, help="Message invisibility duration in seconds."),
]
MaxMessagesOption = Annotated[
    int,
    typer.Option("--max-messages", min=1, max=32, help="Maximum total number of messages to retrieve."),
]
YesOption = Annotated[bool, typer.Option("--yes", help="Delete the queue without prompting.")]


@contextmanager
def _queue_client(endpoint: str, queue: str) -> Generator[QueueClient, None, None]:
    endpoint = validate_endpoint(endpoint)
    queue = validate_name(queue, "--queue")
    with managed_client(
        "Azure Queue Storage",
        lambda credential: QueueClient(account_url=endpoint, queue_name=queue, credential=credential),
    ) as client:
        yield client


def _message_json(message: QueueMessage) -> dict[str, object]:
    return {
        field: value
        for field in (
            "content",
            "id",
            "pop_receipt",
            "inserted_on",
            "expires_on",
            "next_visible_on",
            "dequeue_count",
        )
        if (value := getattr(message, field, None)) is not None
    }


@app.command()
def create_queue(endpoint: EndpointOption, queue: QueueOption) -> None:
    """Create a queue."""
    with _queue_client(endpoint, queue) as client:
        client.create_queue()
    print_json({"queue": queue, "created": True})


@app.command()
def send_message(
    endpoint: EndpointOption,
    queue: QueueOption,
    message: MessageOption = DEFAULT_MESSAGE,
    visibility_timeout: VisibilityOption = 0,
) -> None:
    """Send a message and return its ID and pop receipt."""
    with _queue_client(endpoint, queue) as client:
        result = client.send_message(content=message, visibility_timeout=visibility_timeout)
    print_json(_message_json(result))


@app.command()
def peek_messages(
    endpoint: EndpointOption,
    queue: QueueOption,
    max_messages: MaxMessagesOption = 1,
) -> None:
    """Read visible messages without changing visibility or deleting them."""
    with _queue_client(endpoint, queue) as client:
        results = [_message_json(message) for message in client.peek_messages(max_messages=max_messages)]
    print_json(results)


@app.command()
def update_message(
    endpoint: EndpointOption,
    queue: QueueOption,
    message: MessageOption,
    message_id: MessageIdOption,
    pop_receipt: PopReceiptOption,
    visibility_timeout: VisibilityOption = 0,
) -> None:
    """Update content and visibility; use the returned new pop receipt for later operations."""
    message_id = validate_name(message_id, "--message-id")
    pop_receipt = validate_name(pop_receipt, "--pop-receipt")
    with _queue_client(endpoint, queue) as client:
        result = client.update_message(
            message=message_id,
            pop_receipt=pop_receipt,
            content=message,
            visibility_timeout=visibility_timeout,
        )
    print_json(_message_json(result))


@app.command()
def get_queue_length(endpoint: EndpointOption, queue: QueueOption) -> None:
    """Get the approximate message count (not an exact queue length)."""
    with _queue_client(endpoint, queue) as client:
        properties = client.get_queue_properties()
    print_json({"queue": queue, "approximate_message_count": properties.approximate_message_count})


@app.command()
def receive_messages(
    endpoint: EndpointOption,
    queue: QueueOption,
    max_messages: MaxMessagesOption = 1,
    visibility_timeout: ReceiveVisibilityOption = 30,
) -> None:
    """Receive messages without deleting them; return IDs and receipts for explicit deletion."""
    with _queue_client(endpoint, queue) as client:
        messages = client.receive_messages(
            messages_per_page=max_messages,
            max_messages=max_messages,
            visibility_timeout=visibility_timeout,
        )
        results = [_message_json(message) for message in islice(messages, max_messages)]
    print_json(results)


@app.command()
def delete_message(
    endpoint: EndpointOption,
    queue: QueueOption,
    message_id: MessageIdOption,
    pop_receipt: PopReceiptOption,
) -> None:
    """Delete one message using its ID and latest pop receipt."""
    message_id = validate_name(message_id, "--message-id")
    pop_receipt = validate_name(pop_receipt, "--pop-receipt")
    with _queue_client(endpoint, queue) as client:
        client.delete_message(message=message_id, pop_receipt=pop_receipt)
    print_json({"queue": queue, "id": message_id, "deleted": True})


@app.command()
def delete_queue(endpoint: EndpointOption, queue: QueueOption, yes: YesOption = False) -> None:
    """Delete a queue and all messages. Noninteractive callers must supply --yes."""
    endpoint = validate_endpoint(endpoint)
    queue = validate_name(queue, "--queue")
    if not confirm_delete(queue, yes):
        print_json({"queue": queue, "cancelled": True})
        return
    with _queue_client(endpoint, queue) as client:
        client.delete_queue()
    print_json({"queue": queue, "deleted": True})


if __name__ == "__main__":
    load_dotenv(override=False)
    app()
