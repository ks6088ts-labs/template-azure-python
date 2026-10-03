"""Run Azure Queue Storage quickstart operations with passwordless authentication."""

from typing import Annotated

import typer

from scripts._cli import cli_errors, confirm_delete, print_json
from template_azure_python.internals.azure import queue_storage

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
    str | None,
    typer.Option("--endpoint", help="HTTPS account endpoint. Reads AZURE_QUEUE_STORAGE_ENDPOINT when omitted."),
]
QueueOption = Annotated[
    str | None, typer.Option("--queue", help="Queue name. Reads AZURE_QUEUE_STORAGE_QUEUE_NAME when omitted.")
]
MessageOption = Annotated[str, typer.Option("--message", help="Message content.")]
MessageIdOption = Annotated[str, typer.Option("--message-id", help="Message ID returned by the service.")]
PopReceiptOption = Annotated[str, typer.Option("--pop-receipt", help="Latest pop receipt returned by the service.")]
VisibilityOption = Annotated[
    int, typer.Option("--visibility-timeout", min=0, max=604800, help="Message invisibility duration in seconds.")
]
ReceiveVisibilityOption = Annotated[
    int, typer.Option("--visibility-timeout", min=1, max=604800, help="Message invisibility duration in seconds.")
]
MaxMessagesOption = Annotated[
    int, typer.Option("--max-messages", min=1, max=32, help="Maximum total number of messages to retrieve.")
]
YesOption = Annotated[bool, typer.Option("--yes", help="Delete the queue without prompting.")]


@app.command()
def create_queue(endpoint: EndpointOption = None, queue: QueueOption = None) -> None:
    """Create a queue."""
    with cli_errors():
        print_json(queue_storage.create_queue(endpoint, queue))


@app.command()
def send_message(
    endpoint: EndpointOption = None,
    queue: QueueOption = None,
    message: MessageOption = DEFAULT_MESSAGE,
    visibility_timeout: VisibilityOption = 0,
) -> None:
    """Send a message and return its ID and pop receipt."""
    with cli_errors():
        print_json(queue_storage.send_message(endpoint, queue, message, visibility_timeout))


@app.command()
def peek_messages(
    endpoint: EndpointOption = None, queue: QueueOption = None, max_messages: MaxMessagesOption = 1
) -> None:
    """Read visible messages without changing visibility or deleting them."""
    with cli_errors():
        print_json(queue_storage.peek_messages(endpoint, queue, max_messages))


@app.command()
def update_message(
    *,
    endpoint: EndpointOption = None,
    queue: QueueOption = None,
    message: MessageOption,
    message_id: MessageIdOption,
    pop_receipt: PopReceiptOption,
    visibility_timeout: VisibilityOption = 0,
) -> None:
    """Update content and visibility; use the returned new pop receipt for later operations."""
    with cli_errors():
        print_json(queue_storage.update_message(endpoint, queue, message, message_id, pop_receipt, visibility_timeout))


@app.command()
def get_queue_length(endpoint: EndpointOption = None, queue: QueueOption = None) -> None:
    """Get the approximate message count (not an exact queue length)."""
    with cli_errors():
        print_json(queue_storage.get_queue_length(endpoint, queue))


@app.command()
def receive_messages(
    endpoint: EndpointOption = None,
    queue: QueueOption = None,
    max_messages: MaxMessagesOption = 1,
    visibility_timeout: ReceiveVisibilityOption = 30,
) -> None:
    """Receive without deleting; return IDs and receipts for explicit deletion."""
    with cli_errors():
        print_json(queue_storage.receive_messages(endpoint, queue, max_messages, visibility_timeout))


@app.command()
def delete_message(
    *,
    endpoint: EndpointOption = None,
    queue: QueueOption = None,
    message_id: MessageIdOption,
    pop_receipt: PopReceiptOption,
) -> None:
    """Delete one message using its ID and latest pop receipt."""
    with cli_errors():
        print_json(queue_storage.delete_message(endpoint, queue, message_id, pop_receipt))


@app.command()
def delete_queue(endpoint: EndpointOption = None, queue: QueueOption = None, yes: YesOption = False) -> None:
    """Delete a queue and all messages. Noninteractive callers must supply --yes."""
    with cli_errors():
        endpoint, queue = queue_storage.resolve_queue(endpoint, queue)
        if not confirm_delete(queue, yes):
            print_json({"queue": queue, "cancelled": True})
            return
        print_json(queue_storage.delete_queue(endpoint, queue))


if __name__ == "__main__":
    app()
