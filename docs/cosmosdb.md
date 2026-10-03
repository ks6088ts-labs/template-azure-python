# Azure Cosmos DB

Store and retrieve sample data in Azure Cosmos DB for NoSQL.
The `scripts.cli_cosmosdb` CLI exposes the operations from the
[Python quickstart](https://learn.microsoft.com/en-us/azure/cosmos-db/quickstart-python).

## 1. Prepare the endpoint and access

Complete the [development and common Azure setup](scripts.md) and prepare a
Cosmos DB for NoSQL account. Set the actual endpoint in `.env`:

```dotenv
AZURE_COSMOS_DB_ENDPOINT=https://<account-name>.documents.azure.com:443/
AZURE_COSMOS_DB_DATABASE=cosmicworks
AZURE_COSMOS_DB_CONTAINER=products
```

Grant the calling identity the Cosmos DB permissions needed to create databases
and containers and to write, read, and query items. Authentication uses `DefaultAzureCredential`.
When using Cosmos DB native data-plane RBAC, ensure the role assignment scope covers
the configured database. For example, an assignment scoped to `/dbs/playground`
requires `AZURE_COSMOS_DB_DATABASE=playground`; otherwise the SDK returns a 403
for `Microsoft.DocumentDB/databaseAccounts/readMetadata`.

**Use test data.** Each command creates the database and container if needed.
`upsert-item` replaces an existing item with the same ID and category.

| Setting | Default |
| --- | --- |
| Database | `cosmicworks` |
| Container | `products` |
| Partition key, which groups data | `/category` |
| Item ID | `aaaaaaaa-0000-1111-2222-bbbbbbbbbbbb` |
| Category | `gear-surf-surfboards` |

## 2. Store an item

Run this from the root of this Python repository:

```shell
uv run --locked python -m scripts.cli_cosmosdb upsert-item
```

The saved surfboard item appears as JSON.
To supply its values explicitly:

```shell
uv run --locked python -m scripts.cli_cosmosdb upsert-item \
  --item-id aaaaaaaa-0000-1111-2222-bbbbbbbbbbbb \
  --category gear-surf-surfboards --name "Yamba Surfboard" \
  --quantity 12 --no-sale
```

## 3. Read the item

```shell
uv run --locked python -m scripts.cli_cosmosdb read-item \
  --item-id aaaaaaaa-0000-1111-2222-bbbbbbbbbbbb \
  --category gear-surf-surfboards
```

This retrieves one item by ID and category, known as a point read.
Check that `id`, `category`, and `name` match the item you saved.

## 4. Query by category

```shell
uv run --locked python -m scripts.cli_cosmosdb query-items \
  --category gear-surf-surfboards
```

The matching items appear as a JSON array.
The query uses parameters and searches only that partition.

## Change settings

| Setting | CLI option |
| --- | --- |
| Account URL | `--endpoint` |
| Database name | `--database` |
| Container name | `--container` |
| Dedicated throughput for a new container | `--throughput` (RU/s) |

Dedicated throughput is not set by default. Omit `--throughput` for serverless
or shared-throughput configurations. This option applies only when creating a new container.

```shell
uv run --locked python -m scripts.cli_cosmosdb --help
uv run --locked python -m scripts.cli_cosmosdb upsert-item --help
```
