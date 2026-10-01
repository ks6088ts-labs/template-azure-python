"""Run the Azure Cosmos DB for NoSQL Python SDK quickstart from the command line."""

# Usage:
#   cp .env.template .env
#   az login
#   uv run --locked python -m scripts.cli_cosmosdb --help
#   uv run --locked python -m scripts.cli_cosmosdb upsert-item
#   uv run --locked python -m scripts.cli_cosmosdb read-item
#   uv run --locked python -m scripts.cli_cosmosdb query-items

import json
from collections.abc import Generator
from contextlib import closing, contextmanager
from typing import Annotated
from urllib.parse import urlparse

import typer
from azure.core.exceptions import AzureError
from azure.cosmos import ContainerProxy, CosmosClient, PartitionKey
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

DEFAULT_DATABASE = "cosmicworks"
DEFAULT_CONTAINER = "products"
DEFAULT_ITEM_ID = "aaaaaaaa-0000-1111-2222-bbbbbbbbbbbb"
DEFAULT_CATEGORY = "gear-surf-surfboards"
DEFAULT_ITEM_NAME = "Yamba Surfboard"
DEFAULT_QUANTITY = 12
DEFAULT_SALE = False
PARTITION_KEY_PATH = "/category"
CATEGORY_QUERY = "SELECT * FROM products p WHERE p.category = @category"

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
    str,
    typer.Option(
        "--endpoint",
        envvar="AZURE_COSMOS_DB_ENDPOINT",
        help="HTTPS Azure Cosmos DB for NoSQL account endpoint. Reads AZURE_COSMOS_DB_ENDPOINT when omitted.",
        metavar="URL",
        show_envvar=True,
    ),
]
DatabaseOption = Annotated[
    str,
    typer.Option(
        "--database",
        envvar="AZURE_COSMOS_DB_DATABASE",
        help="Database to create if needed and use. Reads AZURE_COSMOS_DB_DATABASE when omitted.",
        show_default=True,
        show_envvar=True,
    ),
]
ContainerOption = Annotated[
    str,
    typer.Option(
        "--container",
        envvar="AZURE_COSMOS_DB_CONTAINER",
        help="Container to create if needed and use. Reads AZURE_COSMOS_DB_CONTAINER when omitted.",
        show_default=True,
        show_envvar=True,
    ),
]
ThroughputOption = Annotated[
    int | None,
    typer.Option(
        "--throughput",
        min=400,
        help=(
            "Dedicated RU/s used only when creating the container. "
            "Omit for serverless or shared-throughput configurations."
        ),
        metavar="RU/S",
    ),
]
ItemIdOption = Annotated[
    str,
    typer.Option(
        "--item-id",
        help="Unique item identifier.",
        show_default=True,
    ),
]
CategoryOption = Annotated[
    str,
    typer.Option(
        "--category",
        help="Category value used as the logical partition key.",
        show_default=True,
    ),
]
NameOption = Annotated[
    str,
    typer.Option(
        "--name",
        help="Product name stored in the item.",
        show_default=True,
    ),
]
QuantityOption = Annotated[
    int,
    typer.Option(
        "--quantity",
        min=0,
        help="Product quantity stored in the item.",
        show_default=True,
    ),
]
SaleOption = Annotated[
    bool,
    typer.Option(
        "--sale/--no-sale",
        help="Whether the product is on sale.",
        show_default=True,
    ),
]


def _validate_endpoint(endpoint: str) -> str:
    try:
        parsed_endpoint = urlparse(endpoint)
        hostname = parsed_endpoint.hostname
    except ValueError as exc:
        raise typer.BadParameter(
            "must be an HTTPS Azure Cosmos DB account endpoint",
            param_hint="--endpoint",
        ) from exc

    if (
        parsed_endpoint.scheme != "https"
        or not hostname
        or parsed_endpoint.username is not None
        or parsed_endpoint.password is not None
        or parsed_endpoint.path not in ("", "/")
        or parsed_endpoint.query
        or parsed_endpoint.fragment
    ):
        raise typer.BadParameter(
            "must be an HTTPS Azure Cosmos DB account endpoint without credentials, a path, query, or fragment",
            param_hint="--endpoint",
        )

    return endpoint


@contextmanager
def _container_client(
    endpoint: str,
    database_id: str,
    container_id: str,
    throughput: int | None,
) -> Generator[ContainerProxy, None, None]:
    endpoint = _validate_endpoint(endpoint)

    with closing(DefaultAzureCredential()) as credential:
        with closing(CosmosClient(url=endpoint, credential=credential)) as client:
            database = client.create_database_if_not_exists(id=database_id)
            partition_key = PartitionKey(path=PARTITION_KEY_PATH)
            if throughput is None:
                container = database.create_container_if_not_exists(
                    id=container_id,
                    partition_key=partition_key,
                )
            else:
                container = database.create_container_if_not_exists(
                    id=container_id,
                    partition_key=partition_key,
                    offer_throughput=throughput,
                )
            yield container


@contextmanager
def _report_azure_errors() -> Generator[None, None, None]:
    try:
        yield
    except AzureError as exc:
        typer.echo(f"Error: Azure Cosmos DB operation failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc


def _print_json(value: object) -> None:
    typer.echo(json.dumps(value, indent=2, ensure_ascii=False))


@app.command()
def upsert_item(
    endpoint: EndpointOption,
    database: DatabaseOption = DEFAULT_DATABASE,
    container: ContainerOption = DEFAULT_CONTAINER,
    throughput: ThroughputOption = None,
    item_id: ItemIdOption = DEFAULT_ITEM_ID,
    category: CategoryOption = DEFAULT_CATEGORY,
    name: NameOption = DEFAULT_ITEM_NAME,
    quantity: QuantityOption = DEFAULT_QUANTITY,
    sale: SaleOption = DEFAULT_SALE,
) -> None:
    """Create the tutorial item, or replace it when the same ID already exists."""
    item: dict[str, object] = {
        "id": item_id,
        "category": category,
        "name": name,
        "quantity": quantity,
        "sale": sale,
    }

    with _report_azure_errors():
        with _container_client(endpoint, database, container, throughput) as client:
            result = client.upsert_item(body=item)

    _print_json(result)


@app.command()
def read_item(
    endpoint: EndpointOption,
    database: DatabaseOption = DEFAULT_DATABASE,
    container: ContainerOption = DEFAULT_CONTAINER,
    throughput: ThroughputOption = None,
    item_id: ItemIdOption = DEFAULT_ITEM_ID,
    category: CategoryOption = DEFAULT_CATEGORY,
) -> None:
    """Read one item efficiently using its ID and partition key."""
    with _report_azure_errors():
        with _container_client(endpoint, database, container, throughput) as client:
            result = client.read_item(
                item=item_id,
                partition_key=category,
            )

    _print_json(result)


@app.command()
def query_items(
    endpoint: EndpointOption,
    database: DatabaseOption = DEFAULT_DATABASE,
    container: ContainerOption = DEFAULT_CONTAINER,
    throughput: ThroughputOption = None,
    category: CategoryOption = DEFAULT_CATEGORY,
) -> None:
    """Query items in one category with a parameterized, partition-scoped query."""
    with _report_azure_errors():
        with _container_client(endpoint, database, container, throughput) as client:
            results = list(
                client.query_items(
                    query=CATEGORY_QUERY,
                    parameters=[{"name": "@category", "value": category}],
                    partition_key=category,
                    enable_cross_partition_query=False,
                )
            )

    _print_json(results)


if __name__ == "__main__":
    load_dotenv(override=False)
    app()
