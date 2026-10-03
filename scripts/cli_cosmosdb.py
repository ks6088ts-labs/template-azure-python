"""Run the Azure Cosmos DB for NoSQL Python SDK quickstart from the command line."""

from typing import Annotated

import typer

from scripts._cli import cli_errors, print_json
from template_azure_python.internals.azure import cosmosdb

DEFAULT_DATABASE = "cosmicworks"
DEFAULT_CONTAINER = "products"
DEFAULT_ITEM_ID = "aaaaaaaa-0000-1111-2222-bbbbbbbbbbbb"
DEFAULT_CATEGORY = "gear-surf-surfboards"
DEFAULT_ITEM_NAME = "Yamba Surfboard"
DEFAULT_QUANTITY = 12
DEFAULT_SALE = False

app = typer.Typer(
    add_completion=False,
    help=(
        "Run the Azure Cosmos DB for NoSQL Python SDK quickstart with Azure authentication. "
        "Set AZURE_COSMOS_DB_ENDPOINT in .env and run `az login` before using a command."
    ),
    no_args_is_help=True,
    rich_markup_mode="markdown",
)

EndpointOption = Annotated[
    str | None,
    typer.Option(
        "--endpoint",
        help="HTTPS Azure Cosmos DB for NoSQL account endpoint. Reads AZURE_COSMOS_DB_ENDPOINT when omitted.",
        metavar="URL",
    ),
]
DatabaseOption = Annotated[
    str | None,
    typer.Option(
        "--database",
        help="Database to create if needed and use. Reads AZURE_COSMOS_DB_DATABASE when omitted.",
        show_default=DEFAULT_DATABASE,
    ),
]
ContainerOption = Annotated[
    str | None,
    typer.Option(
        "--container",
        help="Container to create if needed and use. Reads AZURE_COSMOS_DB_CONTAINER when omitted.",
        show_default=DEFAULT_CONTAINER,
    ),
]
ThroughputOption = Annotated[
    int | None,
    typer.Option(
        "--throughput",
        min=400,
        help="Dedicated RU/s used only when creating the container. Omit for serverless or shared throughput.",
        metavar="RU/S",
    ),
]
ItemIdOption = Annotated[str, typer.Option("--item-id", help="Unique item identifier.", show_default=True)]
CategoryOption = Annotated[
    str, typer.Option("--category", help="Category value used as the logical partition key.", show_default=True)
]
NameOption = Annotated[str, typer.Option("--name", help="Product name stored in the item.", show_default=True)]
QuantityOption = Annotated[
    int, typer.Option("--quantity", min=0, help="Product quantity stored in the item.", show_default=True)
]
SaleOption = Annotated[
    bool, typer.Option("--sale/--no-sale", help="Whether the product is on sale.", show_default=True)
]


@app.command()
def upsert_item(
    endpoint: EndpointOption = None,
    database: DatabaseOption = None,
    container: ContainerOption = None,
    throughput: ThroughputOption = None,
    item_id: ItemIdOption = DEFAULT_ITEM_ID,
    category: CategoryOption = DEFAULT_CATEGORY,
    name: NameOption = DEFAULT_ITEM_NAME,
    quantity: QuantityOption = DEFAULT_QUANTITY,
    sale: SaleOption = DEFAULT_SALE,
) -> None:
    """Create the tutorial item, or replace it when the same ID already exists."""
    item: dict[str, object] = {"id": item_id, "category": category, "name": name, "quantity": quantity, "sale": sale}
    with cli_errors():
        print_json(cosmosdb.upsert_item(endpoint, database, container, throughput, item), indent=2)


@app.command()
def read_item(
    endpoint: EndpointOption = None,
    database: DatabaseOption = None,
    container: ContainerOption = None,
    throughput: ThroughputOption = None,
    item_id: ItemIdOption = DEFAULT_ITEM_ID,
    category: CategoryOption = DEFAULT_CATEGORY,
) -> None:
    """Read one item efficiently using its ID and partition key."""
    with cli_errors():
        print_json(cosmosdb.read_item(endpoint, database, container, throughput, item_id, category), indent=2)


@app.command()
def query_items(
    endpoint: EndpointOption = None,
    database: DatabaseOption = None,
    container: ContainerOption = None,
    throughput: ThroughputOption = None,
    category: CategoryOption = DEFAULT_CATEGORY,
) -> None:
    """Query items in one category with a parameterized, partition-scoped query."""
    with cli_errors():
        print_json(cosmosdb.query_items(endpoint, database, container, throughput, category), indent=2)


if __name__ == "__main__":
    app()
