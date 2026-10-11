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

Switching the API backend does not migrate existing Tasks or change dbt's input.
See [storage and analytics extensions](dbt/backends.md) for the existing Repository pattern
and future Cosmos export / analytical source design.

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

<a id="task-api-startup-troubleshooting"></a>

### Troubleshooting: the API fails to start with Cosmos DB

Follow these steps when the following launch command fails with the log messages below.
`serve-container-apps` runs Uvicorn locally; it does not deploy to Azure Container Apps.

```shell
uv run --locked python -m scripts.template serve-container-apps --repository cosmosdb
```

```text
Task storage lifespan failed (CosmosResourceNotFoundError, status=404)
...
TaskRepositoryError: Task storage is unavailable
ERROR:    Application startup failed. Exiting.
```

This **Cosmos DB 404** means a resource such as the database/container referenced during startup
was not found. It is separate from the HTTP API returning 404 at `/`.
`Task storage is unavailable` alone does not identify the cause; also inspect the preceding
exception name and status. The API reads the database and Task container before starting
and never creates them automatically.

For example, if `.env` sets `AZURE_COSMOS_DB_DATABASE=playground` and
`AZURE_COSMOS_DB_CONTAINER=products`, but the database contains only `products` and `documents`,
the Task API cannot start even if the product CLI works.
When `AZURE_COSMOS_DB_TASK_CONTAINER` is omitted, the API looks for the default `playground/tasks`.
Setting `AZURE_COSMOS_DB_CONTAINER` does not change Task storage.

#### 1. Check the API's effective storage settings

Run from the repository root. This prints only nonsecret storage target fields,
not credentials or other services' settings:

```shell
uv run --locked python -c '
from template_azure_python.settings import get_azure_settings
settings = get_azure_settings().cosmos_db
print(f"endpoint={settings.endpoint}")
print(f"database={settings.database}")
print(f"task_container={settings.task_container}")
'
```

| Task API setting | When omitted |
| --- | --- |
| `AZURE_COSMOS_DB_ENDPOINT` | Required; missing values fail input validation before startup |
| `AZURE_COSMOS_DB_DATABASE` | `cosmicworks` |
| `AZURE_COSMOS_DB_TASK_CONTAINER` | `tasks`; partition key must be `/id` |

OS environment variables override `.env`. If the output differs from `.env`,
check for exported variables with the same names.
Update only the necessary settings; do not overwrite an existing `.env` with `.env.template`.

#### 2. Inspect the account, database, and containers in Azure

Sign in to Azure CLI and replace the values below with your own.
`COSMOS_ACCOUNT` must name the account corresponding to the endpoint in step 1.
Match the database/container to step 1's output; this example inspects `playground/tasks`.
**`az` does not read `.env`**, so supply these shell variables separately.

```shell
az login
SUBSCRIPTION_ID="<subscription-uuid>"
COSMOS_ACCOUNT="<account-name>"
COSMOS_DATABASE="playground"
TASK_CONTAINER="tasks"

az cosmosdb list --subscription "$SUBSCRIPTION_ID" \
  --query "[?name=='$COSMOS_ACCOUNT'].{account:name,resourceGroup:resourceGroup,endpoint:documentEndpoint}" \
  --output table
```

Verify that the returned endpoint refers to the same account as step 1, then use its
`resourceGroup` below. If no account is returned, check the subscription and account name.
Even if `AZURE_RESOURCE_GROUP` is set to a monitoring or another service's group,
**Task management commands need the resource group containing the Cosmos DB account**.

```shell
COSMOS_RESOURCE_GROUP="<cosmos-account-resource-group>"

az cosmosdb sql database show --subscription "$SUBSCRIPTION_ID" \
  --resource-group "$COSMOS_RESOURCE_GROUP" --account-name "$COSMOS_ACCOUNT" \
  --name "$COSMOS_DATABASE" --query "resource.id" --output tsv

az cosmosdb sql container list --subscription "$SUBSCRIPTION_ID" \
  --resource-group "$COSMOS_RESOURCE_GROUP" --account-name "$COSMOS_ACCOUNT" \
  --database-name "$COSMOS_DATABASE" \
  --query "[].{container:resource.id,partition_key:resource.partitionKey.paths}" \
  --output json
```

List containers only after the database check succeeds.
If a check fails, read Azure CLI's error and distinguish sign-in, permission, or target errors
from a missing resource. Do not interpret every failed check as absence and start creating resources.

#### 3. Create the missing Task container in the correct account

After verifying the target, use the existing Task management CLI.
Explicit options below override management settings in `.env`, so they work even when
the account name is unset or the configured resource group belongs to another service.
Creating resources may incur charges.

```shell
uv run --locked python -m scripts.cli_cosmosdb tasks create-container \
  --subscription "$SUBSCRIPTION_ID" --resource-group "$COSMOS_RESOURCE_GROUP" \
  --account-name "$COSMOS_ACCOUNT" \
  --database "$COSMOS_DATABASE" --container "$TASK_CONTAINER"

uv run --locked python -m scripts.cli_cosmosdb tasks show-container \
  --subscription "$SUBSCRIPTION_ID" --resource-group "$COSMOS_RESOURCE_GROUP" \
  --account-name "$COSMOS_ACCOUNT" \
  --database "$COSMOS_DATABASE" --container "$TASK_CONTAINER"
```

When only the missing container is created in an existing database, the result contains
`database_created: false` and `container_created: true`.
Check that `show-container` reports the same `database` / `container` as step 1
and `partition_key: ["/id"]`.
Rerunning against the same target leaves compatible resources unchanged and returns both creation flags as `false`.

There is no need to delete/rename `products` or `documents`, or point the Task API at the
product container with partition key `/category`.
Management fails if an existing container has a different partition key.
Preserve its data, prepare a separate dedicated container, and set
`AZURE_COSMOS_DB_TASK_CONTAINER` to that name.

**Management command options do not carry over to API startup settings.**
Match the endpoint, database, and Task container in environment variables or `.env` as well.
To omit management options in future, also set `AZURE_COSMOS_DB_ACCOUNT_NAME`,
`AZURE_SUBSCRIPTION_ID`, and `AZURE_RESOURCE_GROUP` correctly.
The account name is not inferred from the endpoint.
If other services share the resource group setting, keep the common setting unchanged
and use the explicit management options above.

#### 4. Rerun the launch command and verify the HTTP response

```shell
uv run --locked python -m scripts.template serve-container-apps --repository cosmosdb
```

After `Application startup complete.` appears, check from another terminal:

```shell
curl --fail --silent --show-error --write-out '\nHTTP %{http_code}\n' \
  http://127.0.0.1:8000/tasks
```

HTTP 200 and a JSON array of Tasks confirm success.
A new empty container returns `[]`; a populated container returns its existing Tasks.
Press `Ctrl+C` in the server terminal to stop it after verification.
Functions uses the same storage settings. With `serve-functions --repository cosmosdb`,
change the verification URL to the default port `7071`.

#### If the error differs

| Symptom | What to check next |
| --- | --- |
| `Missing option '--account-name'` / `--subscription` / `--resource-group` | Required management settings are missing. Supply step 3's explicit options; the endpoint alone does not resolve the management target |
| Management CLI exits nonzero | `az login`, subscription, the Cosmos DB resource group, and control-plane RBAC. Use step 2's `az` commands for details; do not treat failure as resource absence |
| API startup logs status 403 | API identity, Cosmos native data-plane RBAC, and the database/container scope. Successful management commands do not prove that the API has data-plane access |
| `Task container must use partition key /id` | The selected container is not suitable for Tasks. Preserve existing data and prepare a dedicated `/id` container with matching settings |
| Cosmos DB 404 persists after creation | Compare step 1's effective target with the creation result again. Check environment overrides and whether management and the API point to different accounts/databases/containers |

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
