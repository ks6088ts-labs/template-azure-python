import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from azure.core.exceptions import AzureError
from click import unstyle
from typer.testing import CliRunner

from scripts.cli_cosmosdb import (
    DEFAULT_CATEGORY,
    DEFAULT_CONTAINER,
    DEFAULT_DATABASE,
    DEFAULT_ITEM_ID,
    DEFAULT_ITEM_NAME,
    DEFAULT_QUANTITY,
    DEFAULT_SALE,
    app,
)
from template_azure_python.internals.azure.cosmosdb import CATEGORY_QUERY, PARTITION_KEY_PATH

ENDPOINT = "https://example.documents.azure.com:443/"


@pytest.fixture
def cosmos_clients():
    credential = MagicMock()
    client = MagicMock()
    database = MagicMock()
    container = MagicMock()
    partition_key = MagicMock()
    client.create_database_if_not_exists.return_value = database
    database.create_container_if_not_exists.return_value = container

    with (
        patch(
            "template_azure_python.internals.azure.cosmosdb.DefaultAzureCredential", return_value=credential
        ) as credential_type,
        patch("template_azure_python.internals.azure.cosmosdb.CosmosClient", return_value=client) as client_type,
        patch(
            "template_azure_python.internals.azure.cosmosdb.PartitionKey", return_value=partition_key
        ) as partition_key_type,
    ):
        yield SimpleNamespace(
            credential=credential,
            credential_type=credential_type,
            client=client,
            client_type=client_type,
            database=database,
            container=container,
            partition_key=partition_key,
            partition_key_type=partition_key_type,
        )


def assert_default_resources(cosmos_clients: SimpleNamespace) -> None:
    cosmos_clients.credential_type.assert_called_once_with()
    cosmos_clients.client_type.assert_called_once_with(
        url=ENDPOINT,
        credential=cosmos_clients.credential,
    )
    cosmos_clients.client.create_database_if_not_exists.assert_called_once_with(id=DEFAULT_DATABASE)
    cosmos_clients.partition_key_type.assert_called_once_with(path=PARTITION_KEY_PATH)
    cosmos_clients.database.create_container_if_not_exists.assert_called_once_with(
        id=DEFAULT_CONTAINER,
        partition_key=cosmos_clients.partition_key,
    )
    cosmos_clients.client.close.assert_called_once_with()
    cosmos_clients.credential.close.assert_called_once_with()


def test_upsert_item_uses_tutorial_defaults(cosmos_clients: SimpleNamespace):
    expected_item = {
        "id": DEFAULT_ITEM_ID,
        "category": DEFAULT_CATEGORY,
        "name": DEFAULT_ITEM_NAME,
        "quantity": DEFAULT_QUANTITY,
        "sale": DEFAULT_SALE,
    }
    cosmos_clients.container.upsert_item.return_value = expected_item

    result = CliRunner().invoke(app, ["upsert-item", "--endpoint", ENDPOINT])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == expected_item
    assert_default_resources(cosmos_clients)
    cosmos_clients.container.upsert_item.assert_called_once_with(body=expected_item)


def test_upsert_item_uses_cli_options_and_throughput(cosmos_clients: SimpleNamespace):
    expected_item = {
        "id": "custom-id",
        "category": "custom-category",
        "name": "Custom product",
        "quantity": 3,
        "sale": True,
    }
    cosmos_clients.container.upsert_item.return_value = expected_item

    result = CliRunner().invoke(
        app,
        [
            "upsert-item",
            "--endpoint",
            ENDPOINT,
            "--database",
            "custom-database",
            "--container",
            "custom-container",
            "--throughput",
            "500",
            "--item-id",
            "custom-id",
            "--category",
            "custom-category",
            "--name",
            "Custom product",
            "--quantity",
            "3",
            "--sale",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == expected_item
    cosmos_clients.client.create_database_if_not_exists.assert_called_once_with(id="custom-database")
    cosmos_clients.database.create_container_if_not_exists.assert_called_once_with(
        id="custom-container",
        partition_key=cosmos_clients.partition_key,
        offer_throughput=500,
    )
    cosmos_clients.container.upsert_item.assert_called_once_with(body=expected_item)


def test_read_item_reads_resource_options_from_environment(cosmos_clients: SimpleNamespace):
    expected_item = {"id": "custom-id", "category": "custom-category"}
    cosmos_clients.container.read_item.return_value = expected_item

    result = CliRunner().invoke(
        app,
        [
            "read-item",
            "--item-id",
            "custom-id",
            "--category",
            "custom-category",
        ],
        env={
            "AZURE_COSMOS_DB_ENDPOINT": ENDPOINT,
            "AZURE_COSMOS_DB_DATABASE": "environment-database",
            "AZURE_COSMOS_DB_CONTAINER": "environment-container",
        },
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == expected_item
    cosmos_clients.client_type.assert_called_once_with(
        url=ENDPOINT,
        credential=cosmos_clients.credential,
    )
    cosmos_clients.client.create_database_if_not_exists.assert_called_once_with(id="environment-database")
    cosmos_clients.database.create_container_if_not_exists.assert_called_once_with(
        id="environment-container",
        partition_key=cosmos_clients.partition_key,
    )
    cosmos_clients.container.read_item.assert_called_once_with(
        item="custom-id",
        partition_key="custom-category",
    )


def test_query_items_uses_parameterized_partition_query(cosmos_clients: SimpleNamespace):
    expected_items = [
        {"id": "item-1", "category": "custom-category"},
        {"id": "item-2", "category": "custom-category"},
    ]
    cosmos_clients.container.query_items.return_value = iter(expected_items)

    result = CliRunner().invoke(
        app,
        [
            "query-items",
            "--endpoint",
            ENDPOINT,
            "--category",
            "custom-category",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == expected_items
    cosmos_clients.container.query_items.assert_called_once_with(
        query=CATEGORY_QUERY,
        parameters=[{"name": "@category", "value": "custom-category"}],
        partition_key="custom-category",
        enable_cross_partition_query=False,
    )


def test_upsert_item_requires_endpoint():
    result = CliRunner().invoke(
        app,
        ["upsert-item"],
        env={"AZURE_COSMOS_DB_ENDPOINT": ""},
    )

    assert result.exit_code == 2
    assert "Missing option '--endpoint'" in unstyle(result.output)


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://example.documents.azure.com:8081/",
        "https://example.documents.azure.com/path",
        "not-a-url",
    ],
)
def test_commands_reject_invalid_endpoint(endpoint: str):
    with (
        patch("template_azure_python.internals.azure.cosmosdb.DefaultAzureCredential") as credential_type,
        patch("template_azure_python.internals.azure.cosmosdb.CosmosClient") as client_type,
    ):
        result = CliRunner().invoke(app, ["query-items", "--endpoint", endpoint])

    assert result.exit_code == 2
    assert "must be an HTTPS Azure Cosmos DB account" in unstyle(result.output)
    credential_type.assert_not_called()
    client_type.assert_not_called()


def test_upsert_item_rejects_invalid_throughput():
    with (
        patch("template_azure_python.internals.azure.cosmosdb.DefaultAzureCredential") as credential_type,
        patch("template_azure_python.internals.azure.cosmosdb.CosmosClient") as client_type,
    ):
        result = CliRunner().invoke(
            app,
            [
                "upsert-item",
                "--endpoint",
                ENDPOINT,
                "--throughput",
                "399",
            ],
        )

    assert result.exit_code == 2
    assert "400" in result.output
    credential_type.assert_not_called()
    client_type.assert_not_called()


def test_query_items_reports_azure_error(cosmos_clients: SimpleNamespace):
    cosmos_clients.container.query_items.side_effect = AzureError("request failed")

    result = CliRunner().invoke(app, ["query-items", "--endpoint", ENDPOINT])

    assert result.exit_code == 1
    assert "Error: Azure Cosmos DB operation failed: request failed" in result.output
    cosmos_clients.client.close.assert_called_once_with()
    cosmos_clients.credential.close.assert_called_once_with()


@pytest.mark.parametrize("command", ["upsert-item", "read-item", "query-items"])
def test_command_help_describes_endpoint_environment_variable(command: str):
    result = CliRunner().invoke(
        app,
        [command, "--help"],
        env={"COLUMNS": "240"},
        terminal_width=240,
    )

    assert result.exit_code == 0, result.output
    assert "AZURE_COSMOS_DB_ENDPOINT" in result.output
    assert "AZURE_COSMOS_DB_DATABASE" in result.output
    assert "AZURE_COSMOS_DB_CONTAINER" in result.output
    assert DEFAULT_DATABASE in result.output
    assert DEFAULT_CONTAINER in result.output
