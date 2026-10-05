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

## Task API persistence and container management

Separate from the product CLI above, the Task API uses the async SDK and a **dedicated `/id` container**.
The API never creates databases/containers. Prepare them with the management CLI before startup.
Select an existing account and resource group. Management calls Azure CLI Core `az cosmosdb sql`,
so install Azure CLI and sign in with `az login` or another supported CLI login.
No additional management SDK is required.

### Settings and permissions

Add nonsecret settings to `.env`:

```dotenv
TASK_REPOSITORY=in-memory
AZURE_COSMOS_DB_ENDPOINT=https://<account-name>.documents.azure.com:443/
AZURE_COSMOS_DB_DATABASE=cosmicworks
AZURE_COSMOS_DB_TASK_CONTAINER=tasks
AZURE_COSMOS_DB_ACCOUNT_NAME=<account-name>
AZURE_SUBSCRIPTION_ID=<subscription-uuid>
AZURE_RESOURCE_GROUP=<resource-group-name>
```

- **Management CLI identity**: Azure control-plane RBAC to manage databases/containers in the selected
  account, for example Cosmos DB Operator. Cosmos data-plane roles alone cannot create/delete these resources.
  Entra data SDK management operations fail with 403 / substatus 5300.
- **API identity**: `DefaultAzureCredential` and Cosmos native data-plane RBAC permitting metadata reads,
  Task CRUD, and queries at the selected database/container, for example Cosmos DB Built-in Data Contributor.
  The API needs no management privileges.
- Always specify a subscription with `--subscription` or `AZURE_SUBSCRIPTION_ID`.
  The wrapper does not silently fall back to the CLI's default subscription.
- The product setting `AZURE_COSMOS_DB_CONTAINER=products` is not used for Task storage/management.
  Verify that the account name and endpoint refer to the same account.

### Create and inspect

```shell
uv run --locked python -m scripts.cli_cosmosdb tasks create-container
uv run --locked python -m scripts.cli_cosmosdb tasks show-container
```

Only missing resources are created, with partition key `/id`.
Reruns leave compatible containers unchanged and return `false` for
`database_created` / `container_created`. A different partition key fails without deleting,
recreating, or migrating the container.
`show-container` returns safe management metadata such as the resource ID and partition key, not Task data.

Override settings with `--subscription`, `--resource-group`, `--account-name`, `--database`, and `--container`.
Use `create-container --throughput 400` only to request dedicated RU/s on a new container.
Omitting throughput passes no throughput argument to az, supporting serverless/shared database throughput.
Existing container throughput is never changed. Creating resources may incur charges.

### Start and verify the API

```shell
uv run --locked python -m scripts.template serve-container-apps --repository cosmosdb
# For Functions:
# uv run --locked python -m scripts.template serve-functions --repository cosmosdb
```

Create a Task in another terminal, stop/restart the API with the same storage settings, and verify it persists:

```shell
curl --fail -H 'Content-Type: application/json' \
  -d '{"title":"Persist this Task"}' http://127.0.0.1:8000/tasks
curl --fail http://127.0.0.1:8000/tasks
```

Set `TASK_REPOSITORY=cosmosdb` to omit the launch option.
Explicit CLI selection overrides environment/dotenv; the default is `in-memory`.
Startup checks connectivity, container existence, and partitioning and fails visibly on errors.
Runtime storage failures return HTTP 503 with `{"detail":"Task storage is unavailable"}` and produce logs.
Lists read all cross-partition pages, consuming RUs/memory. Pagination and ETag concurrency protection
are not implemented; updates are last-writer-wins. HTTP authentication is not added.

### Delete after stopping

**All Tasks in the container are deleted.** Stop the API and check the displayed target:

```shell
uv run --locked python -m scripts.cli_cosmosdb tasks delete-container
# Explicit approval for noninteractive use such as CI:
uv run --locked python -m scripts.cli_cosmosdb tasks delete-container --yes
```

Declining returns `cancelled: true`; confirmed completed deletion returns `deleted: true`.
The database and account are never deleted. Missing resources, insufficient permissions,
missing sign-in/az, timeouts, and invalid JSON are explicit failures.
Input errors exit 2; operation failures exit 1.
Deletion also checks `/id` and refuses other partition keys such as the product container's `/category`.
If database creation succeeds but container creation fails, partial completion is reported and the database
is retained. Inspect resources with `show-container`/Azure portal, resolve the cause, and rerun.
No schema/container/throughput migrations, database deletion, or account creation are provided.

See Microsoft's [nondata operation restrictions with Entra ID](https://learn.microsoft.com/azure/cosmos-db/troubleshoot-forbidden#nondata-operations-arent-allowed)
for the reason management uses the control plane.
