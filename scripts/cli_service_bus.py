"""Run the Azure Service Bus queue quickstart with passwordless authentication."""

from typing import Annotated

import typer

from scripts._cli import cli_errors, print_json
from template_azure_python.internals.azure import service_bus

DEFAULT_MESSAGE = "Single Message"
DEFAULT_COUNT = 3
DEFAULT_MAX_MESSAGES = 10
DEFAULT_MAX_WAIT_TIME = 5.0

app = typer.Typer(
    add_completion=False,
    help=(
        "Run the Azure Service Bus queue quickstart with DefaultAzureCredential. "
        "Set AZURE_SERVICE_BUS_FULLY_QUALIFIED_NAMESPACE and AZURE_SERVICE_BUS_QUEUE_NAME "
        "in .env and run `az login` before using a command."
    ),
    no_args_is_help=True,
    rich_markup_mode="markdown",
)

NamespaceOption = Annotated[
    str | None,
    typer.Option(
        "--fully-qualified-namespace",
        help="Namespace hostname. Reads AZURE_SERVICE_BUS_FULLY_QUALIFIED_NAMESPACE when omitted.",
    ),
]
QueueOption = Annotated[
    str | None, typer.Option("--queue", help="Existing queue. Reads AZURE_SERVICE_BUS_QUEUE_NAME when omitted.")
]
MessageOption = Annotated[str, typer.Option("--message", help="Text body of each message.", show_default=True)]
CountOption = Annotated[int, typer.Option("--count", min=1, help="Number of messages to send.", show_default=True)]
MaxMessagesOption = Annotated[
    int, typer.Option("--max-messages", min=1, help="Maximum number of messages to receive.", show_default=True)
]
MaxWaitOption = Annotated[
    float, typer.Option("--max-wait-time", help="Positive finite receive wait time in seconds.", show_default=True)
]


@app.command()
def send_message(
    fully_qualified_namespace: NamespaceOption = None,
    queue: QueueOption = None,
    message: MessageOption = DEFAULT_MESSAGE,
) -> None:
    """Send one message to the queue."""
    with cli_errors():
        print_json(service_bus.send_message(fully_qualified_namespace, queue, message))


@app.command()
def send_message_list(
    fully_qualified_namespace: NamespaceOption = None,
    queue: QueueOption = None,
    message: MessageOption = DEFAULT_MESSAGE,
    count: CountOption = DEFAULT_COUNT,
) -> None:
    """Send a list of messages in one SDK call."""
    with cli_errors():
        print_json(service_bus.send_message_list(fully_qualified_namespace, queue, message, count))


@app.command()
def send_message_batch(
    fully_qualified_namespace: NamespaceOption = None,
    queue: QueueOption = None,
    message: MessageOption = DEFAULT_MESSAGE,
    count: CountOption = DEFAULT_COUNT,
) -> None:
    """Send one SDK-sized batch; fail without sending if any message cannot fit."""
    with cli_errors():
        print_json(service_bus.send_message_batch(fully_qualified_namespace, queue, message, count))


@app.command()
def receive_messages(
    fully_qualified_namespace: NamespaceOption = None,
    queue: QueueOption = None,
    max_messages: MaxMessagesOption = DEFAULT_MAX_MESSAGES,
    max_wait_time: MaxWaitOption = DEFAULT_MAX_WAIT_TIME,
) -> None:
    """Receive a bounded set of messages, displaying each before completing it."""
    with cli_errors():
        received = service_bus.receive_messages(
            fully_qualified_namespace, queue, max_messages, max_wait_time, print_json
        )
        print_json({"received": received})


if __name__ == "__main__":
    app()
