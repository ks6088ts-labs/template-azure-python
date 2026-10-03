from collections.abc import Generator
from contextlib import closing, contextmanager
from urllib.parse import urlparse

from azure.cosmos import ContainerProxy, CosmosClient, PartitionKey
from azure.identity import DefaultAzureCredential

from template_azure_python.internals.azure._common import InputError, azure_errors, required_value
from template_azure_python.settings import get_azure_settings

PARTITION_KEY_PATH = "/category"
CATEGORY_QUERY = "SELECT * FROM products p WHERE p.category = @category"


def _validate_endpoint(endpoint: str) -> str:
    try:
        parsed = urlparse(endpoint)
        hostname = parsed.hostname
    except ValueError as exc:
        raise InputError("must be an HTTPS Azure Cosmos DB account endpoint", "--endpoint") from exc
    if (
        parsed.scheme != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise InputError(
            "must be an HTTPS Azure Cosmos DB account endpoint without credentials, a path, query, or fragment",
            "--endpoint",
        )
    return endpoint


@contextmanager
def _container_client(
    endpoint: str | None, database_id: str | None, container_id: str | None, throughput: int | None
) -> Generator[ContainerProxy, None, None]:
    settings = get_azure_settings()
    endpoint = _validate_endpoint(required_value(endpoint, settings.azure_cosmos_db_endpoint, "--endpoint"))
    database_id = required_value(database_id, settings.azure_cosmos_db_database, "--database")
    container_id = required_value(container_id, settings.azure_cosmos_db_container, "--container")
    with azure_errors("Azure Cosmos DB operation failed", include_details=True):
        with closing(DefaultAzureCredential()) as credential:
            with closing(CosmosClient(url=endpoint, credential=credential)) as client:
                database = client.create_database_if_not_exists(id=database_id)
                partition_key = PartitionKey(path=PARTITION_KEY_PATH)
                if throughput is None:
                    container = database.create_container_if_not_exists(id=container_id, partition_key=partition_key)
                else:
                    container = database.create_container_if_not_exists(
                        id=container_id, partition_key=partition_key, offer_throughput=throughput
                    )
                yield container


def upsert_item(
    endpoint: str | None, database: str | None, container: str | None, throughput: int | None, item: dict[str, object]
) -> dict[str, object]:
    with _container_client(endpoint, database, container, throughput) as client:
        return client.upsert_item(body=item)


def read_item(
    endpoint: str | None,
    database: str | None,
    container: str | None,
    throughput: int | None,
    item_id: str,
    category: str,
) -> dict[str, object]:
    with _container_client(endpoint, database, container, throughput) as client:
        return client.read_item(item=item_id, partition_key=category)


def query_items(
    endpoint: str | None, database: str | None, container: str | None, throughput: int | None, category: str
) -> list[dict[str, object]]:
    with _container_client(endpoint, database, container, throughput) as client:
        return list(
            client.query_items(
                query=CATEGORY_QUERY,
                parameters=[{"name": "@category", "value": category}],
                partition_key=category,
                enable_cross_partition_query=False,
            )
        )
