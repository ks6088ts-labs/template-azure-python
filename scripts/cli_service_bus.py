"""Run the Azure Service Bus queue quickstart with passwordless authentication.

Reference: https://learn.microsoft.com/azure/service-bus-messaging/service-bus-python-how-to-use-queues
"""

# Usage:
#   cp .env.template .env
#   az login
#   uv run --locked python -m scripts.cli_service_bus --help
#   uv run --locked python -m scripts.cli_service_bus send-message
#   uv run --locked python -m scripts.cli_service_bus receive-messages

import math
from collections.abc import Generator
from contextlib import closing, contextmanager
from typing import Annotated

import typer
from azure.servicebus import ServiceBusClient, ServiceBusMessage, ServiceBusReceiveMode
from dotenv import load_dotenv

from scripts._azure_messaging import managed_client, print_json, validate_name, validate_namespace

SERVICE = "Azure Service Bus"
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
    str,
    typer.Option(
        "--fully-qualified-namespace",
        envvar="AZURE_SERVICE_BUS_FULLY_QUALIFIED_NAMESPACE",
        help="Service Bus namespace hostname, without a scheme or connection string.",
        show_envvar=True,
    ),
]
QueueOption = Annotated[
    str,
    typer.Option(
        "--queue",
        envvar="AZURE_SERVICE_BUS_QUEUE_NAME",
        help="Name of an existing Service Bus queue.",
        show_envvar=True,
    ),
]
MessageOption = Annotated[str, typer.Option("--message", help="Text body of each message.", show_default=True)]
CountOption = Annotated[int, typer.Option("--count", min=1, help="Number of messages to send.", show_default=True)]
MaxMessagesOption = Annotated[
    int,
    typer.Option("--max-messages", min=1, help="Maximum number of messages to receive.", show_default=True),
]
MaxWaitOption = Annotated[
    float,
    typer.Option("--max-wait-time", help="Positive finite receive wait time in seconds.", show_default=True),
]


@contextmanager
def _queue_client(namespace: str, queue: str) -> Generator[ServiceBusClient, None, None]:
    namespace = validate_namespace(namespace)
    validate_name(queue, "--queue")
    with managed_client(
        SERVICE,
        lambda credential: ServiceBusClient(fully_qualified_namespace=namespace, credential=credential),
    ) as client:
        yield client


@app.command()
def send_message(
    fully_qualified_namespace: NamespaceOption,
    queue: QueueOption,
    message: MessageOption = DEFAULT_MESSAGE,
) -> None:
    """Send one message to the queue."""
    with _queue_client(fully_qualified_namespace, queue) as client:
        with closing(client.get_queue_sender(queue_name=queue)) as sender:
            sender.send_messages(ServiceBusMessage(message))
    print_json({"sent": 1})


@app.command()
def send_message_list(
    fully_qualified_namespace: NamespaceOption,
    queue: QueueOption,
    message: MessageOption = DEFAULT_MESSAGE,
    count: CountOption = DEFAULT_COUNT,
) -> None:
    """Send a list of messages in one SDK call."""
    with _queue_client(fully_qualified_namespace, queue) as client:
        with closing(client.get_queue_sender(queue_name=queue)) as sender:
            sender.send_messages([ServiceBusMessage(message) for _ in range(count)])
    print_json({"sent": count})


@app.command()
def send_message_batch(
    fully_qualified_namespace: NamespaceOption,
    queue: QueueOption,
    message: MessageOption = DEFAULT_MESSAGE,
    count: CountOption = DEFAULT_COUNT,
) -> None:
    """Send one SDK-sized batch; fail without sending if any message cannot fit."""
    with _queue_client(fully_qualified_namespace, queue) as client:
        with closing(client.get_queue_sender(queue_name=queue)) as sender:
            batch = sender.create_message_batch()
            for _ in range(count):
                try:
                    batch.add_message(ServiceBusMessage(message))
                except ValueError as exc:
                    typer.echo(
                        f"Error: {SERVICE} batch overflow; no messages were sent. Reduce --count or --message size.",
                        err=True,
                    )
                    raise typer.Exit(code=1) from exc
            sender.send_messages(batch)
    print_json({"sent": count})


@app.command()
def receive_messages(
    fully_qualified_namespace: NamespaceOption,
    queue: QueueOption,
    max_messages: MaxMessagesOption = DEFAULT_MAX_MESSAGES,
    max_wait_time: MaxWaitOption = DEFAULT_MAX_WAIT_TIME,
) -> None:
    """Receive a bounded set of messages, displaying each before completing it."""
    if not math.isfinite(max_wait_time) or max_wait_time <= 0:
        raise typer.BadParameter("must be positive and finite", param_hint="--max-wait-time")

    received = 0
    with _queue_client(fully_qualified_namespace, queue) as client:
        with closing(
            client.get_queue_receiver(queue_name=queue, receive_mode=ServiceBusReceiveMode.PEEK_LOCK)
        ) as receiver:
            messages = receiver.receive_messages(max_message_count=max_messages, max_wait_time=max_wait_time)
            for message in messages:
                print_json(
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
    print_json({"received": received})


if __name__ == "__main__":
    load_dotenv(override=False)
    app()
