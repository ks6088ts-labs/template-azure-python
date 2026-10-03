"""Inspect existing Azure Network Watchers without changing network resources."""

from typing import Annotated

import typer

from scripts._cli import cli_errors, print_json
from template_azure_python.internals.azure import network_watcher

app = typer.Typer(
    add_completion=False,
    help="Read existing Network Watcher metadata using passwordless Azure authentication. Run `az login` first.",
    no_args_is_help=True,
    rich_markup_mode="markdown",
)
ResourceIdOption = Annotated[
    str | None,
    typer.Option(
        "--resource-id",
        help="Full ARM ID; its subscription and group are used unchanged. Reads AZURE_NETWORK_WATCHER_ID when omitted.",
    ),
]
SubscriptionOption = Annotated[
    str | None, typer.Option("--subscription-id", help="Subscription UUID. Reads AZURE_SUBSCRIPTION_ID when omitted.")
]
ResourceGroupOption = Annotated[
    str | None,
    typer.Option(
        "--resource-group",
        help=(
            "Optional group: 1-90 ASCII letters, digits, _, (, ), -, or .; no trailing dot. Reads AZURE_RESOURCE_GROUP."
        ),
    ),
]


@app.command()
def show_watcher(resource_id: ResourceIdOption = None) -> None:
    """Read one watcher. JSON: {id, name, location, provisioning_state}; absent fields are null."""
    with cli_errors():
        print_json(network_watcher.show_watcher(resource_id))


@app.command()
def list_watchers(subscription_id: SubscriptionOption = None, resource_group: ResourceGroupOption = None) -> None:
    """Read metadata. JSON: {watchers: [{id, name, location, provisioning_state}]}; empty list is success."""
    with cli_errors():
        print_json(network_watcher.list_watchers(subscription_id, resource_group))


if __name__ == "__main__":
    app()
