# Scripts and development

## Prerequisites

- [Python 3.10+](https://www.python.org/downloads/) (CI tests 3.10 through 3.14)
- [uv 0.12.19](https://docs.astral.sh/uv/getting-started/installation/)
- [GNU Make](https://www.gnu.org/software/make/)
- [actionlint](https://github.com/rhysd/actionlint) for local lint and CI checks
  (CI uses v1.7.12)
- [Docker](https://docs.docker.com/get-docker/) for Docker targets
- [Azure Functions Core Tools v4](https://learn.microsoft.com/azure/azure-functions/functions-run-local)
  for running Functions locally
- `curl` for HTTP checks
- [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) for the
  Azure SDK samples and publishing to existing Azure resources

## Make targets

Run these commands from the repository root:

```shell
# list available targets
make

# install all development dependencies and Git hooks
make install-deps-dev

# check all configured hooks
make hooks-check

# run tests
make test

# run the complete CI test suite
make ci-test

# build the English and Japanese documentation
make ci-test-docs

# launch JupyterLab
make jupyterlab
```

`make install-deps-dev` installs all development groups and installs the
[prek](https://prek.j178.dev/) Git hook, replacing a previously installed
pre-commit hook. CI uses a smaller dependency set without JupyterLab; the
notebook group remains available through `make jupyterlab`.

`make lint` also runs an offline [zizmor](https://zizmor.sh/) check that blocks
high-severity GitHub Actions configuration findings. Run
`uv run --locked zizmor --offline .` to review lower-severity findings as well.

## Application CLI

The `scripts.template` module provides the application development commands.
List all commands and options with:

```shell
uv run --locked python -m scripts.template --help
```

### Basic command

Load settings from `.env` when present and run the sample command:

```shell
uv run --locked python -m scripts.template hello
uv run --locked python -m scripts.template --verbose hello --name Azure
```

### FastAPI on Azure Container Apps or local Uvicorn

The same FastAPI app in `template_azure_python/api.py` is used by both hosts.
Start it with Uvicorn locally:

```shell
uv run --locked python -m scripts.template serve-container-apps
```

It listens on `http://127.0.0.1:8000` by default. Use `--host` and `--port` to
change the listening address:

```shell
uv run --locked python -m scripts.template serve-container-apps --host 0.0.0.0 --port 8080
```

Check the default server from another terminal:

```shell
curl http://127.0.0.1:8000/
# {"Hello":"World"}
curl -I http://127.0.0.1:8000/docs
```

Interactive API documentation is available at
`http://127.0.0.1:8000/docs`.

### FastAPI on Azure Functions

The root-level `function_app.py` wraps the same FastAPI app with Azure
Functions' `AsgiFunctionApp`, following the
[Azure FastAPI sample](https://github.com/Azure-Samples/fastapi-on-azure-functions).
`host.json` removes the default `/api` route prefix, so URLs are identical
across hosts. The HTTP trigger is anonymous, as in the sample; add access
controls before exposing sensitive routes.

From the repository root, create the ignored local settings file once:

```shell
cp local.settings.json.example local.settings.json
```

The example leaves `AzureWebJobsStorage` empty for this HTTP-only app. Other
triggers require a valid storage connection. Core Tools may log a storage
health warning with the empty value even while these HTTP routes work. To
satisfy the health check, run Azurite and set `AzureWebJobsStorage` to
`UseDevelopmentStorage=true` in `local.settings.json`.

Install Core Tools v4 and start the local Functions host:

```shell
uv run --locked python -m scripts.template serve-functions
# Use a different local port:
uv run --locked python -m scripts.template serve-functions --port 7072
```

From another terminal, verify both the API and its documentation:

```shell
curl http://127.0.0.1:7071/
# {"Hello":"World"}
curl -I http://127.0.0.1:7071/docs
```

The CLI starts Core Tools only for local development. In Azure, the Functions
runtime discovers `function_app.py` directly; it does not run this CLI. The
private `local.settings.json` and `.env` are excluded from Functions publishing
and Docker builds.

## Microsoft Foundry CLI

The `scripts.cli_foundry` module runs the Microsoft Foundry Python SDK
quickstart. Copy the environment template, set `FOUNDRY_PROJECT_ENDPOINT` to
the HTTPS project URL containing `/api/projects/`, and authenticate:

```shell
cp .env.template .env
az login
uv run --locked python -m scripts.cli_foundry --help
```

### Required Foundry RBAC

The project endpoint uses Microsoft Entra ID authentication through
`DefaultAzureCredential`. Before running the commands, assign the
[Foundry User role](https://learn.microsoft.com/azure/foundry/concepts/rbac-foundry)
on the Foundry account to both:

- the user or service principal that runs the CLI; and
- the Foundry project's managed identity.

`Foundry User` was previously named `Azure AI User`, so the old name might
still appear while the rename rolls out. Azure `Owner` and `Contributor` roles
do not replace this role: they grant management-plane access but not all
project data-plane permissions. Projects created in the Foundry portal can
receive the assignments automatically when the creator is allowed to assign
roles. Projects created another way might require the assignments below.

The caller must have permission to create role assignments. Replace the
placeholder values, then grant access at the Foundry account scope:

```shell
SUBSCRIPTION_ID="$(az account show --query id --output tsv)"
RESOURCE_GROUP="<foundry-resource-group>"
FOUNDRY_ACCOUNT="<foundry-account-name>"
FOUNDRY_PROJECT="<foundry-project-name>"

FOUNDRY_SCOPE="/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.CognitiveServices/accounts/${FOUNDRY_ACCOUNT}"
PROJECT_SCOPE="${FOUNDRY_SCOPE}/projects/${FOUNDRY_PROJECT}"

USER_OBJECT_ID="$(az ad signed-in-user show --query id --output tsv)"
PROJECT_PRINCIPAL_ID="$(az resource show \
  --ids "${PROJECT_SCOPE}" \
  --query identity.principalId \
  --output tsv)"

az role assignment create \
  --assignee-object-id "${USER_OBJECT_ID}" \
  --assignee-principal-type User \
  --role "Foundry User" \
  --scope "${FOUNDRY_SCOPE}"

az role assignment create \
  --assignee-object-id "${PROJECT_PRINCIPAL_ID}" \
  --assignee-principal-type ServicePrincipal \
  --role "Foundry User" \
  --scope "${FOUNDRY_SCOPE}"
```

If `PROJECT_PRINCIPAL_ID` is empty, configure a managed identity for the
project before continuing. Verify that both assignments are visible:

```shell
az role assignment list \
  --scope "${FOUNDRY_SCOPE}" \
  --include-inherited \
  --query "[?roleDefinitionName=='Foundry User' && (principalId=='${USER_OBJECT_ID}' || principalId=='${PROJECT_PRINCIPAL_ID}')].{principalType:principalType,role:roleDefinitionName,scope:scope}" \
  --output table
```

### Troubleshoot `PermissionDeniedError: 403`

A missing project data-plane role can make a command end with an error like
this, sometimes without a response body:

```text
PermissionDeniedError: Error code: 403
```

Use the following checks before changing code:

1. Confirm that Azure CLI is using the expected subscription, tenant, and
   identity:

   ```shell
   az account show \
     --query "{subscription:name,tenantId:tenantId,user:user.name}" \
     --output table
   ```

2. Confirm that `FOUNDRY_PROJECT_ENDPOINT` is the project URL, in the form
   `https://<account>.services.ai.azure.com/api/projects/<project>`.
3. Confirm that the deployment exists, is ready, and supports the Responses
   API:

   ```shell
   az cognitiveservices account deployment show \
     --resource-group "${RESOURCE_GROUP}" \
     --name "${FOUNDRY_ACCOUNT}" \
     --deployment-name "gpt-5-mini" \
     --query "{state:properties.provisioningState,responses:properties.capabilities.responses,model:properties.model.name,version:properties.model.version}" \
     --output table
   ```

4. Run the role-assignment query above. If either the calling identity or the
   project managed identity is absent, create the missing `Foundry User`
   assignment.
5. Allow several minutes for RBAC propagation, then retry:

   ```shell
   uv run --locked python -m scripts.cli_foundry chat-model
   ```

If the deployment is ready and both role assignments are present but the
request still returns 403, inspect the Foundry account's firewall, virtual
network, and private endpoint configuration. See Microsoft's
[HTTP error troubleshooting guide](https://learn.microsoft.com/azure/foundry/openai/how-to/troubleshoot-errors)
for network denial and resource suspension checks. Do not replace the project
endpoint with a resource-level OpenAI endpoint for `create-agent` or
`chat-agent`; that bypasses project-scoped capabilities instead of correcting
the project access configuration.

Send one prompt directly to a model:

```shell
uv run --locked python -m scripts.cli_foundry chat-model
uv run --locked python -m scripts.cli_foundry chat-model \
  --model gpt-5-mini \
  --prompt "What is the size of France in square miles?"
```

Create a prompt agent or a new version of an existing named agent:

```shell
uv run --locked python -m scripts.cli_foundry create-agent
uv run --locked python -m scripts.cli_foundry create-agent \
  --agent-name MyAgent \
  --model gpt-5-mini \
  --instructions "You are a helpful assistant."
```

Create or version an agent and run a two-turn conversation:

```shell
uv run --locked python -m scripts.cli_foundry chat-agent
uv run --locked python -m scripts.cli_foundry chat-agent \
  --agent-name MyAgent \
  --prompt "What is the size of France in square miles?" \
  --follow-up-prompt "And what is the capital city?"
```

Use `--endpoint` to override `FOUNDRY_PROJECT_ENDPOINT`. Run each command with
`--help` for all options and defaults.

## Azure Cosmos DB CLI

The `scripts.cli_cosmosdb` module collects the Python SDK operations from the
[Azure Cosmos DB for NoSQL Python quickstart](https://learn.microsoft.com/en-us/azure/cosmos-db/quickstart-python)
as separate commands. Copy the environment template, set the account endpoint,
and authenticate with Microsoft Entra ID:

```shell
cp .env.template .env
az login
uv run --locked python -m scripts.cli_cosmosdb --help
```

`DefaultAzureCredential` uses the signed-in Azure CLI identity locally. Grant
that identity the least-privileged Azure Cosmos DB data-plane permissions needed
to create databases and containers and to write, read, and query items.

The CLI defaults to the quickstart's `cosmicworks` database, `products`
container, and `/category` partition key. Each command creates the database and
container when needed. Dedicated throughput is omitted by default for
serverless and shared-throughput configurations; use `--throughput` to set RU/s
when a new container requires dedicated throughput.

Create the tutorial item, or replace the item with the same ID:

```shell
uv run --locked python -m scripts.cli_cosmosdb upsert-item
uv run --locked python -m scripts.cli_cosmosdb upsert-item \
  --item-id aaaaaaaa-0000-1111-2222-bbbbbbbbbbbb \
  --category gear-surf-surfboards \
  --name "Yamba Surfboard" \
  --quantity 12 \
  --no-sale
```

Perform a point read using the item ID and partition key:

```shell
uv run --locked python -m scripts.cli_cosmosdb read-item
uv run --locked python -m scripts.cli_cosmosdb read-item \
  --item-id aaaaaaaa-0000-1111-2222-bbbbbbbbbbbb \
  --category gear-surf-surfboards
```

Run the quickstart's parameterized, partition-scoped category query:

```shell
uv run --locked python -m scripts.cli_cosmosdb query-items
uv run --locked python -m scripts.cli_cosmosdb query-items \
  --category gear-surf-surfboards
```

Use `--endpoint`, `--database`, and `--container` to override the environment
values `AZURE_COSMOS_DB_ENDPOINT`, `AZURE_COSMOS_DB_DATABASE`, and
`AZURE_COSMOS_DB_CONTAINER`. Run each command with `--help` for all options.

## Azure messaging CLIs

The Event Grid, Event Hubs, Service Bus, and Queue Storage CLIs read service
configuration from `.env` and authenticate with `DefaultAzureCredential`.
They do not accept connection strings or shared keys. Run commands from the
repository root and sign in with `az login` for local use.

Four independent modules exercise the passwordless examples in these articles:

- [Event Grid Python SDK](https://learn.microsoft.com/en-us/python/api/overview/azure/eventgrid-readme?view=azure-python)
- [Event Hubs Python quickstart](https://learn.microsoft.com/en-us/azure/event-hubs/event-hubs-python-get-started-send?tabs=passwordless%2Croles-azure-portal)
- [Service Bus Queue Python quickstart](https://learn.microsoft.com/en-us/azure/service-bus-messaging/service-bus-python-how-to-use-queues?tabs=passwordless)
- [Queue Storage Python quickstart](https://learn.microsoft.com/en-us/azure/storage/queues/storage-quickstart-queues-python?tabs=passwordless%2Croles-azure-portal%2Cenvironment-variable-windows%2Csign-in-azure-cli)

### Terraform outputs and authentication

Use resources already deployed by
[`ks6088ts/template-terraform`, `infra/scenarios/azure_messaging`](https://github.com/ks6088ts/template-terraform/tree/main/infra/scenarios/azure_messaging).
Services are opt-in and disabled by default; enable the services you want to
exercise using that repository's instructions. No Terraform changes are required
in this Python repository. From your Terraform checkout, read the outputs:

```shell
terraform -chdir=infra/scenarios/azure_messaging output
# For a single value without quotes:
terraform -chdir=infra/scenarios/azure_messaging output -raw event_grid_topic_endpoint
```

In this Python repository, copy the template once (do not overwrite an existing
`.env`), replace the placeholders with the corresponding outputs, and sign in:

```shell
cp .env.template .env
az login
uv run --locked python -m scripts.cli_event_grid --help
uv run --locked python -m scripts.cli_event_hubs --help
uv run --locked python -m scripts.cli_service_bus --help
uv run --locked python -m scripts.cli_queue_storage --help
```

| Terraform output | `.env` variable | CLI override |
| --- | --- | --- |
| `event_grid_topic_endpoint` | `AZURE_EVENT_GRID_TOPIC_ENDPOINT` | `--endpoint` |
| `event_hubs_namespace_fqdn` | `AZURE_EVENT_HUBS_FULLY_QUALIFIED_NAMESPACE` | `--fully-qualified-namespace` |
| `event_hub_name` | `AZURE_EVENT_HUB_NAME` | `--event-hub` |
| `event_hub_consumer_group_name` | `AZURE_EVENT_HUB_CONSUMER_GROUP` | `--consumer-group` |
| `service_bus_namespace_fqdn` | `AZURE_SERVICE_BUS_FULLY_QUALIFIED_NAMESPACE` | `--fully-qualified-namespace` |
| `service_bus_queue_name` | `AZURE_SERVICE_BUS_QUEUE_NAME` | `--queue` |
| `queue_storage_endpoint` | `AZURE_QUEUE_STORAGE_ENDPOINT` | `--endpoint` |
| `queue_storage_queue_name` | `AZURE_QUEUE_STORAGE_QUEUE_NAME` | `--queue` |

Disabled services have null/absent outputs; do not use these as configuration.
Namespace values are hostnames such as `<namespace>.servicebus.windows.net`,
without a scheme or path. Endpoints are HTTPS URLs; use the Queue endpoint,
not the Blob or DFS endpoint. The built-in consumer group is literally
`$Default`; quote it as `'$Default'` in shell commands.

All four CLIs use **only `DefaultAzureCredential`**: locally it can use
developer credentials such as `az login`; in Azure it can use the hosting
resource's managed identity. Configure the intended identity and grant it the
roles below; an Azure managed identity does not inherit your local user's
permissions. Other configured credentials in the default chain may take
precedence over Azure CLI credentials. No connection-string, account-key, or
SAS options are provided. The Terraform scenario disables shared-key/local
data-plane authentication.

### Recover configuration from Azure

If `terraform output` reports `Required plugins are not installed`, initialize
the scenario from the Terraform checkout before reading its outputs:

```shell
terraform -chdir=infra/scenarios/azure_messaging init
```

Alternatively, retrieve the non-secret settings from Azure directly. Sign in,
select the intended subscription, and replace these resource-name placeholders:

```shell
RESOURCE_GROUP="<messaging-resource-group>"
EVENT_HUBS_NAMESPACE="<event-hubs-namespace>"
EVENT_HUB="<event-hub-name>"
SERVICE_BUS_NAMESPACE="<service-bus-namespace>"
STORAGE_ACCOUNT="<queue-storage-account>"

az eventgrid topic list --resource-group "$RESOURCE_GROUP" \
  --query '[].{name:name,endpoint:endpoint,inputSchema:inputSchema}' --output table
az eventhubs namespace show --resource-group "$RESOURCE_GROUP" \
  --name "$EVENT_HUBS_NAMESPACE" --query serviceBusEndpoint --output tsv
az eventhubs eventhub list --resource-group "$RESOURCE_GROUP" \
  --namespace-name "$EVENT_HUBS_NAMESPACE" --query '[].name' --output tsv
az eventhubs eventhub consumer-group list --resource-group "$RESOURCE_GROUP" \
  --namespace-name "$EVENT_HUBS_NAMESPACE" --eventhub-name "$EVENT_HUB" \
  --query '[].name' --output tsv
az servicebus namespace show --resource-group "$RESOURCE_GROUP" \
  --name "$SERVICE_BUS_NAMESPACE" --query serviceBusEndpoint --output tsv
az servicebus queue list --resource-group "$RESOURCE_GROUP" \
  --namespace-name "$SERVICE_BUS_NAMESPACE" --query '[].name' --output tsv
az storage account show --resource-group "$RESOURCE_GROUP" \
  --name "$STORAGE_ACCOUNT" --query primaryEndpoints.queue --output tsv
az storage queue list --account-name "$STORAGE_ACCOUNT" --auth-mode login \
  --query '[].name' --output tsv
```

Use only the hostname from each namespace's `serviceBusEndpoint`: for example,
`https://example.servicebus.windows.net:443/` becomes
`example.servicebus.windows.net`. Keep the full HTTPS URL for Event Grid and
Queue Storage. Update the variables in the mapping above without removing
unrelated `.env` values. Keep `.env` local and Git-ignored; no account keys or
SAS tokens are needed. Storage queue listing requires its data-plane role.
Neither reading configuration nor testing the CLIs requires `terraform apply`.

### Required messaging RBAC

For each enabled service, the scenario assigns these roles to its
`operator_principal_id` output: the Terraform operator by default, or the
principal explicitly selected with the same input variable.

| Service | Assigned data-plane roles | Assignment scope (Terraform output) |
| --- | --- | --- |
| Event Grid | `EventGrid Data Sender` | Custom Topic (`event_grid_topic_id`) |
| Event Hubs | `Azure Event Hubs Data Sender`, `Azure Event Hubs Data Receiver` | Namespace (`event_hubs_namespace_id`) |
| Service Bus | `Azure Service Bus Data Sender`, `Azure Service Bus Data Receiver` | Namespace (`service_bus_namespace_id`) |
| Queue Storage | `Storage Queue Data Contributor` | Storage account (`queue_storage_account_id`) |

Verify that the calling identity matches the authorized principal. To inspect
assignments, substitute the appropriate resource ID and principal object ID
from the Terraform outputs (or your Azure-hosted managed identity's object ID):

```shell
az account show --query "{subscription:name,tenantId:tenantId,user:user.name}" --output table
MESSAGING_SCOPE="<resource-ID-from-the-scope-column>"
PRINCIPAL_ID="<calling-principal-object-ID>"
az role assignment list \
  --scope "$MESSAGING_SCOPE" --include-inherited \
  --query "[?principalId=='${PRINCIPAL_ID}'].{role:roleDefinitionName,scope:scope}" \
  --output table
```

If the runtime identity differs from the scenario operator, an authorized
administrator must assign the required roles to that identity. Management-plane
`Owner`/`Contributor` access alone does not replace data-plane roles. Allow
several minutes for role propagation; for authorization failures also check
the selected tenant, endpoint, and resource network restrictions.

### Article-to-command coverage

| Article feature | Module | Command / adaptation |
| --- | --- | --- |
| Event Grid: Send a Cloud Event | `scripts.cli_event_grid` | `publish-event`; select the topic's input schema |
| Event Grid: Send Multiple Events | `scripts.cli_event_grid` | `publish-events`; one send with an event list |
| Event Grid: Namespace receive/process | — | Excluded: no Namespace, namespace topic, or pull subscription |
| Event Hubs: Send events | `scripts.cli_event_hubs` | `send-events`; one SDK batch |
| Event Hubs: Receive events | `scripts.cli_event_hubs` | `receive-events`; bounded, without Blob checkpoints |
| Service Bus: Send single message | `scripts.cli_service_bus` | `send-message` |
| Service Bus: Send a list | `scripts.cli_service_bus` | `send-message-list`; one send with a list |
| Service Bus: Send a batch | `scripts.cli_service_bus` | `send-message-batch`; explicit SDK batch |
| Service Bus: Receive/complete | `scripts.cli_service_bus` | `receive-messages`; complete after display |
| Queue Storage: Create queue | `scripts.cli_queue_storage` | `create-queue` |
| Queue Storage: Add message | `scripts.cli_queue_storage` | `send-message` |
| Queue Storage: Peek messages | `scripts.cli_queue_storage` | `peek-messages` |
| Queue Storage: Update message | `scripts.cli_queue_storage` | `update-message` |
| Queue Storage: Get queue length | `scripts.cli_queue_storage` | `get-queue-length`; approximate count |
| Queue Storage: Receive messages | `scripts.cli_queue_storage` | `receive-messages`; does not delete |
| Queue Storage: Delete message | `scripts.cli_queue_storage` | `delete-message`; ID and pop receipt |
| Queue Storage: Delete queue | `scripts.cli_queue_storage` | `delete-queue`; confirmation or explicit `--yes` |

### Event Grid Basic Custom Topic

Publish one event or multiple events (three by default) using the default payload and
`--schema event-grid`, which matches Terraform's default `EventGridSchema`:

```shell
uv run --locked python -m scripts.cli_event_grid publish-event
uv run --locked python -m scripts.cli_event_grid publish-events
uv run --locked python -m scripts.cli_event_grid publish-events \
  --subject "samples/orders" --event-type "Sample.OrderCreated" \
  --data '{"orderId":42,"status":"created"}' --data-version "1.0" --count 2
```

The Terraform default topic accepts only `EventGridSchema`. Against that topic,
the following command fails with `BadRequest` because a CloudEvent contains
properties such as `source` that are not valid in an Event Grid event:

```shell
uv run --locked python -m scripts.cli_event_grid publish-events \
  --schema cloud-event --count 3
```

Omit `--schema`, or explicitly use `--schema event-grid`, for the default
deployment. To publish CloudEvents, first set
`event_grid_input_schema = "CloudEventSchemaV1_0"` in the Terraform scenario
and apply that configuration to the topic. The publisher cannot select or
convert the input schema for an already deployed topic.

`--data` must be a JSON object, not an array or scalar. For a topic deployed
with `event_grid_input_schema = "CloudEventSchemaV1_0"`, explicitly select
`--schema cloud-event`; `--source` supplies the CloudEvent source:

```shell
uv run --locked python -m scripts.cli_event_grid publish-event \
  --endpoint "https://<topic>.<region>-1.eventgrid.azure.net/api/events" \
  --schema cloud-event --source "/samples/orders" \
  --subject "orders/42" --event-type "Sample.OrderCreated" \
  --data '{"orderId":42}'
```

`--data-version` is Event Grid schema metadata, not a CloudEvent version
selector. `publish-events --count` sends the entire event list in one call.
Publishing prints one JSON object with `schema`, `count`, and `ids` fields.
The CLI does not support `CustomEventSchema` or Namespace consumer operations
(receive, acknowledge, release, reject, renew lock). This scenario creates a
Basic Custom Topic, not an Event Grid Namespace, and no event subscriptions:
successful publishing does not by itself establish downstream delivery.

### Event Hubs

Send the three quickstart events by default, or supply repeatable `--message`
options to build one batch. Sending prints `{"sent": N}`:

```shell
uv run --locked python -m scripts.cli_event_hubs send-events
uv run --locked python -m scripts.cli_event_hubs send-events \
  --fully-qualified-namespace "<namespace>.servicebus.windows.net" \
  --event-hub events --message "First event" --message '{"orderId":42}'
uv run --locked python -m scripts.cli_event_hubs receive-events
uv run --locked python -m scripts.cli_event_hubs receive-events \
  --consumer-group '$Default' --starting-position '-1' \
  --max-events 3 --max-wait-time 10
```

The receiver defaults to at most 100 events and a 15-second idle timeout.
`--max-events` accepts 1–10,000.
It stops at `--max-events` or after `--max-wait-time` seconds of
global inactivity across partitions, and displays payload and
partition/sequence metadata as JSON lines followed by a received-count summary.
Event objects contain `body`, `partition_id`, `offset`, `sequence_number`,
and `enqueued_time`; the final object is `{"received": N}`, including zero.
Any real event resets the idle timeout; reception also times out when no
callbacks arrive or no partitions are discovered. An idle partition does not
stop reception while other partitions remain active. `--starting-position` defaults to `-1`
(beginning of retained events), and `--consumer-group` defaults to `$Default`.
Receiving is non-destructive and saves **no checkpoints**: another run with
the same starting position can reread retained events. The article's Blob
checkpoint store is intentionally excluded because the scenario provisions
neither a Blob container nor `Storage Blob Data Contributor`.

The initial timeout also includes authentication, connection, and partition
discovery. A short timeout can return `{"received": 0}` before receiving any
retained events. Retry with `--max-wait-time 30 --starting-position '-1'` and
check the namespace, event hub, consumer group, and receiver RBAC. `@latest`
does not read events already present when the receiver connects. Exported
environment variables override `.env`; explicit CLI options override both.

### Service Bus Queue

The three send commands demonstrate distinct SDK send shapes. Use `--message`
to change the body and `--count` to change list/batch sizes (default: three).
Receive defaults to at most ten messages and a 5-second wait:

```shell
uv run --locked python -m scripts.cli_service_bus send-message
uv run --locked python -m scripts.cli_service_bus send-message-list
uv run --locked python -m scripts.cli_service_bus send-message-batch
uv run --locked python -m scripts.cli_service_bus send-message --message "Hello queue"
uv run --locked python -m scripts.cli_service_bus send-message-list --message "Order" --count 2
uv run --locked python -m scripts.cli_service_bus send-message-batch --message "Order" --count 2
uv run --locked python -m scripts.cli_service_bus receive-messages
uv run --locked python -m scripts.cli_service_bus receive-messages \
  --fully-qualified-namespace "<namespace>.servicebus.windows.net" \
  --queue queue --max-messages 5 --max-wait-time 10
```

`send-message-list` passes the list to `send_messages` once.
`send-message-batch` adds messages to a `ServiceBusMessageBatch` and explicitly
reports capacity overflow rather than silently dropping messages. Reduce
`--count` or message size if the batch is too large. Receiving is bounded by
the requested count/wait. Send commands print `{"sent": N}`; receive prints
one JSON object per message with `body`, `message_id`, and metadata, followed
by `{"received": N}`. Each object occupies one line, not an indented block.
Each successfully displayed message is **completed**, removing it from the queue. This differs
from Event Hubs and Queue Storage receive behavior. Only Queues are supported,
even though the scenario also deploys a Topic and Subscription.

### Queue Storage lifecycle (scratch queue)

Use a unique scratch queue for these examples. `--queue` overrides the
Terraform-managed queue in `.env`, including for deletion. Queue names must
be valid Azure Storage queue names (lowercase letters, numbers, and hyphens).
With the endpoint configured in `.env`, try the default message and limits:

```shell
SCRATCH_QUEUE="messaging-cli-scratch-$(date +%s)"
uv run --locked python -m scripts.cli_queue_storage create-queue --queue "$SCRATCH_QUEUE"
uv run --locked python -m scripts.cli_queue_storage send-message --queue "$SCRATCH_QUEUE"
uv run --locked python -m scripts.cli_queue_storage peek-messages --queue "$SCRATCH_QUEUE"
uv run --locked python -m scripts.cli_queue_storage get-queue-length --queue "$SCRATCH_QUEUE"
uv run --locked python -m scripts.cli_queue_storage receive-messages --queue "$SCRATCH_QUEUE"
```

Customize the body, visibility timeout (seconds), and retrieval limit.
Peek/receive default to one message; receive hides it for 30 seconds by
default. Send/update default to a visibility timeout of zero.
Keep the visibility timeout below the message's remaining lifetime
(the default message lifetime is seven days).
`--max-messages` for peek/receive must be between **1 and 32**:

```shell
uv run --locked python -m scripts.cli_queue_storage send-message \
  --queue "$SCRATCH_QUEUE" --message "Please update me" --visibility-timeout 0
uv run --locked python -m scripts.cli_queue_storage peek-messages \
  --queue "$SCRATCH_QUEUE" --max-messages 2
uv run --locked python -m scripts.cli_queue_storage receive-messages \
  --queue "$SCRATCH_QUEUE" --max-messages 2 --visibility-timeout 120
```

Send, receive, and update return JSON containing `id` and `pop_receipt`
needed for subsequent operations. Send/update output one metadata object;
receive outputs one aggregate object, `{"received": N, "messages": [...]}`,
with metadata for each message. An empty receive returns
`{"received": 0, "messages": []}`. Each result is complete on a single line
for JSONL processing. Peek returns an array of message metadata without pop
receipts. It does not change visibility or consume
a message. Receive hides messages for the visibility timeout but **does not
delete them**; they become visible again if not deleted. The queue length is
an approximate service count, not a count of currently visible messages.

Copy an ID and its matching pop receipt from the latest receive output, then
update before the visibility timeout expires:

```shell
MESSAGE_ID="<message-ID-from-receive>"
POP_RECEIPT="<matching-pop-receipt-from-receive>"
uv run --locked python -m scripts.cli_queue_storage update-message \
  --queue "$SCRATCH_QUEUE" --message-id "$MESSAGE_ID" --pop-receipt "$POP_RECEIPT" \
  --message "Updated content" --visibility-timeout 120
```

Update returns a **new pop receipt**. Replace the old value with that receipt;
future receives also change the receipt. Always use the latest receipt for
the same message when updating or deleting:

```shell
POP_RECEIPT="<new-pop-receipt-from-update>"
uv run --locked python -m scripts.cli_queue_storage delete-message \
  --queue "$SCRATCH_QUEUE" --message-id "$MESSAGE_ID" --pop-receipt "$POP_RECEIPT"
# Delete only the scratch queue; prompts for confirmation:
uv run --locked python -m scripts.cli_queue_storage delete-queue --queue "$SCRATCH_QUEUE"
# Alternative for noninteractive cleanup (explicit opt-in):
uv run --locked python -m scripts.cli_queue_storage delete-queue --queue "$SCRATCH_QUEUE" --yes
```

Declining deletion cancels without calling Azure. Noninteractive queue
deletion requires `--yes`. Deleting a queue removes all remaining messages;
never substitute the Terraform-managed queue for the scratch queue in these
cleanup commands. Use `--endpoint` to override the Queue service endpoint and
each command's `--help` to inspect all options and defaults.

### Troubleshooting

| Symptom | What to check |
| --- | --- |
| Missing `--endpoint`, `--fully-qualified-namespace`, or queue options | Populate the corresponding `.env` variables; do not replace an existing file with the template. |
| Updated `.env` values are not used | Exported shell variables take precedence because `load_dotenv(override=False)` preserves them; explicit CLI options override both. Remove stale exports or pass the desired option. |
| `terraform output` reports `Required plugins are not installed` | Run `terraform init` in the Terraform scenario, or [retrieve configuration directly from Azure](#recover-configuration-from-azure). Reading existing resources does not require `terraform apply`. |
| Unauthorized or forbidden errors | Check the identity selected by `DefaultAzureCredential`, tenant, and [data-plane RBAC](#required-messaging-rbac). `Owner`/`Contributor` alone is not sufficient; also check network restrictions. |
| Event Hubs returns `{"received": 0}` despite retained events | The default 15-second timeout includes initial authentication, connection, and partition discovery. Try `--max-wait-time 30 --starting-position '-1'`; `@latest` only reads new events. |
| Event Grid rejects the event schema | Match `--schema` to the topic's `inputSchema`: `event-grid` for `EventGridSchema`, `cloud-event` for `CloudEventSchemaV1_0`. |
| Queue Storage update/delete fails | Use the latest `pop_receipt` returned by receive or update; either operation invalidates the previous receipt. |

Use dedicated scratch queues for lifecycle checks. Service Bus receive completes
and deletes messages; Queue Storage queue deletion removes all messages. Never
use an existing application queue for destructive smoke tests.

## Azure observability CLIs

These short exercises use existing resources from
[`ks6088ts/template-terraform`, `infra/scenarios/azure_observability`](https://github.com/ks6088ts/template-terraform/tree/main/infra/scenarios/azure_observability).
All scenario features are **off by default**. Enable only the resources needed
in that repository before continuing: `features.azure_monitor`,
`features.log_analytics`, `features.application_insights`, and/or
`features.network_watcher`. Application Insights also requires Log Analytics.
`features.activity_log` configures diagnostic export and also requires
`features.log_analytics`; it does not enable the live Activity Log API.
Azure Monitor Workspace is the **managed Prometheus** workspace,
not Log Analytics. The scenario does not deploy a Prometheus collector, so an
empty `up` result is expected unless a separate collector already sends data.
Network Watcher can belong to a different resource group. Subscription Activity
Log exists independently of these workspaces.

### Configure IDs and read access

Read nonsecret outputs from your Terraform checkout:

```shell
terraform -chdir=infra/scenarios/azure_observability output
# Single value without quotes:
terraform -chdir=infra/scenarios/azure_observability output -raw azure_monitor_id
```

In this Python repository, copy the template only if `.env` does not already
exist, fill in the IDs below, and authenticate:

```shell
test -f .env || cp .env.template .env
az login
az account show --query '{subscription:id,tenant:tenantId}' --output table
```

| Terraform output / source | Resource / value | `.env` variable | CLI override |
| --- | --- | --- | --- |
| `azure_monitor_id` | Azure Monitor Workspace ARM ID (`Microsoft.Monitor/accounts`) | `AZURE_MONITOR_ID` | `--resource-id` |
| `log_analytics_workspace_id` | Log Analytics workspace/customer **GUID**, not `log_analytics_id` (ARM ID) | `AZURE_LOG_ANALYTICS_WORKSPACE_ID` | `--workspace-id` |
| `application_insights_id` | Application Insights ARM ID (`Microsoft.Insights/components`) | `AZURE_APPLICATION_INSIGHTS_ID` | `--resource-id` |
| `network_watcher_id` | Network Watcher ARM ID (`Microsoft.Network/networkWatchers`) | `AZURE_NETWORK_WATCHER_ID` | `--resource-id` |
| `az account show --query id --output tsv` | Subscription GUID; no scenario output | `AZURE_SUBSCRIPTION_ID` | `--subscription-id` |
| `resource_group_name`, or the existing watcher's actual group | Optional group filter; leave empty for subscription-wide reads | `AZURE_RESOURCE_GROUP` | `--resource-group` |

An ARM ID starts with `/subscriptions/<id>/resourceGroups/<group>/providers/`;
a workspace GUID has the form `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`. Disabled
features have null/absent outputs: skip their exercises rather than copying
`null`. Nonsecret CLI options override environment/`.env` values; run any
command with `--help`. Reads use `DefaultAzureCredential`, including `az login`
locally; other configured credentials can take precedence.

Have an administrator authorize the actual calling identity:

| Operation | Required access and scope |
| --- | --- |
| Workspace metadata / watcher metadata | Management-plane `Reader` on the corresponding resource; watcher listing needs access at the selected resource-group/subscription scope |
| PromQL query | `Monitoring Data Reader` on the **Azure Monitor Workspace** |
| Log Analytics workspace queries | `Log Analytics Reader` on the Log Analytics workspace |
| Application Insights resource-centric queries | `Reader` on the Application Insights component when the workspace access mode allows resource permissions; otherwise grant query access such as `Log Analytics Reader` on the backing workspace |
| Subscription Activity Log | `Reader` at subscription scope, including Activity Log read access |

PromQL's `Monitoring Data Reader` is not the general-purpose `Monitoring Reader`
role. See [Prometheus API access](https://learn.microsoft.com/azure/azure-monitor/metrics/prometheus-api-promql),
[Log Analytics access](https://learn.microsoft.com/azure/azure-monitor/logs/manage-access),
and [Activity Log](https://learn.microsoft.com/azure/azure-monitor/platform/activity-log).
The read-only watcher commands follow the
[Network Watcher overview](https://learn.microsoft.com/azure/network-watcher/network-watcher-overview);
they do not start packet captures or connectivity tests.
For 403 responses, check the identity/tenant, resource scope, role propagation,
and network restrictions. These CLIs do not assign roles, deploy collectors, or
write diagnostic settings.

### Read all five targets

Run only the commands for available, authorized targets. The `AzureActivity`
exercises require both `features.activity_log` and `features.log_analytics`
to export into the selected workspace. The live Activity Log API needs no
scenario feature flag.

```shell
# Managed Prometheus: inspect the workspace, then run an instant query.
uv run --locked python -m scripts.cli_azure_monitor show-workspace
uv run --locked python -m scripts.cli_azure_monitor query-prometheus --query 'up'

# Log Analytics: fixed AzureActivity KQL, not arbitrary query input.
uv run --locked python -m scripts.cli_log_analytics query-logs --hours 24 --limit 100
uv run --locked python -m scripts.cli_log_analytics summarize-activity --hours 24 --limit 100

# Workspace-based Application Insights; no connection string is needed to read.
uv run --locked python -m scripts.cli_application_insights query-telemetry \
  --table AppRequests --hours 24 --limit 100

# Discover across the subscription before assuming the scenario's resource group.
uv run --locked python -m scripts.cli_network_watcher list-watchers
uv run --locked python -m scripts.cli_network_watcher show-watcher

# Subscription control-plane history, not a Log Analytics query.
uv run --locked python -m scripts.cli_activity_log list-events --hours 24 --limit 100
uv run --locked python -m scripts.cli_activity_log summarize-events --hours 24 --limit 100
```

`list-watchers`, `list-events`, and `summarize-events` accept
`--resource-group "<group>"` (or `AZURE_RESOURCE_GROUP`) to narrow their scope.
Leave that environment variable empty for subscription-wide discovery.
For example, an explicit ID
overrides the configured watcher:

```shell
uv run --locked python -m scripts.cli_network_watcher show-watcher \
  --resource-id "/subscriptions/<subscription-id>/resourceGroups/<watcher-group>/providers/Microsoft.Network/networkWatchers/<watcher-name>"
```

Log and telemetry queries and Activity Log commands accept `--hours 1..168`
(default `24`) and `--limit 1..1000` (default `100`). `query-logs` and
`query-telemetry` limit returned rows. Log Analytics `summarize-activity`
aggregates **all matching rows in the time window**, then limits the returned
groups. In contrast, live Activity Log `summarize-events` counts only a sample
of up to `--limit` events, not all subscription events in that window.
None of these results is an unrestricted lifetime total.
Log Analytics `AzureActivity` contains only
Activity Log events **separately exported by a subscription diagnostic setting**.
It is not the live Activity Log API. Without export, the table may be missing
or empty while `list-events` succeeds. A quiet subscription can also have no
events. The scenario's `activity_log_id` identifies an export diagnostic
setting, not a subscription ID or query workspace. See
[Activity Log export](https://learn.microsoft.com/azure/azure-monitor/platform/activity-log#export-activity-log).

### Emit and find Application Insights telemetry

Only this exercise sends data and can incur ingestion charges. The scenario
does **not** output an Application Insights connection string. Copy it privately
from the resource's Azure portal **Overview** page into the local, Git-ignored
`.env` as `APPLICATIONINSIGHTS_CONNECTION_STRING`. Alternatively, set that
environment variable using your local secret-management process. Keep the
template value empty; never paste the value into source, shell command
arguments/history, screenshots, logs, or shared output. There is no
connection-string CLI flag. See
[connection strings](https://learn.microsoft.com/azure/azure-monitor/app/connection-strings)
and the [Python OpenTelemetry quickstart](https://learn.microsoft.com/azure/azure-monitor/app/opentelemetry-enable?tabs=python).

```shell
uv run --locked python -m scripts.cli_application_insights emit-telemetry --count 10
```

`--count` accepts `1..100` (default `10`). The command emits sample server
spans, correlated logs, and metric increments, flushes the providers, and
reports a unique `run_id`. `flushed` means provider flushing completed, **not**
that Azure accepted or ingested the telemetry: background HTTP failures can
still occur. Provider false returns/exceptions and observed SDK warnings are
reported. Allow ingestion time, then locate that run in
recent requests and filter each signal using the printed UUID:

```shell
uv run --locked python -m scripts.cli_application_insights query-telemetry \
  --table AppRequests --hours 1 --limit 100
RUN_ID="<run_id-UUID-printed-by-emit-telemetry>"
uv run --locked python -m scripts.cli_application_insights query-telemetry \
  --table AppRequests --run-id "$RUN_ID" --hours 1 --limit 100
uv run --locked python -m scripts.cli_application_insights query-telemetry \
  --table AppTraces --run-id "$RUN_ID" --hours 1 --limit 100
uv run --locked python -m scripts.cli_application_insights query-telemetry \
  --table AppMetrics --run-id "$RUN_ID" --hours 1 --limit 100
```

Queries allow `AppRequests`, `AppTraces`, `AppMetrics`, and `AppDependencies`;
the CLI maps these aliases to the resource-centric API's `requests`, `traces`,
`customMetrics`, and `dependencies`. JSON columns retain the API schema:
time is `timestamp`, the run ID is in `customDimensions.run_id`, and the
metric aggregate is `valueSum`.
The last table is supported for existing dependency telemetry, but this emitter
does not create dependency spans. `--run-id` is optional but must be a UUID
when provided. Metrics are aggregated: compare counter values/aggregates,
not metric row counts, with emitted increments. The scenario's Application
Insights sampling defaults to **25%**; Azure Monitor OpenTelemetry distro
client-side sampling is configured separately (this emitter explicitly uses
`always_on`). Sampled span/log rows and
bounded query results need not equal `--count`. If no run appears, wait
and retry within the time window, then check sampling, the destination and
query workspace, RBAC, and ingestion/network failures rather than generating
unbounded traffic. See [sampling](https://learn.microsoft.com/azure/azure-monitor/app/opentelemetry-sampling)
and [ingestion latency](https://learn.microsoft.com/azure/azure-monitor/logs/data-ingestion-time).
Remove the local connection string when finished; deleting local settings does
not stop Azure resource charges.

### Troubleshoot observability CLIs

- For `Missing option`, configure the IDs in the table above or pass explicit
  CLI options. `az login` does not populate resource IDs or
  `AZURE_SUBSCRIPTION_ID` in `.env`. Do not overwrite an existing `.env` with
  the template. A configured `AZURE_RESOURCE_GROUP` restricts watcher lists
  and Activity Log reads to that group.
  An `.env` created from an older template does not automatically receive new
  variables. Add missing variables to the existing `.env` and set their actual
  IDs. For example, setting
  `AZURE_MONITOR_ID=/subscriptions/<subscription-id>/resourceGroups/<group>/providers/Microsoft.Monitor/accounts/<workspace-name>`
  lets you run `show-workspace` without an option. CLI options and environment
  variables set only inside an execution process do not persist settings for
  later terminals. After configuration, run the documented commands unchanged
  in a normal terminal to verify the setup.
- If an Application Insights query fails, distinguish the resource-centric
  API schema from the workspace API schema. `query_resource` uses
  `requests | where timestamp >= ago(1h)` and `customDimensions["run_id"]`.
  `AppRequests`, `TimeGenerated`, and `Properties` belong to the workspace
  schema. Update older CLI versions that fail to resolve `AppRequests`.
  See the [Application Insights query schema](https://learn.microsoft.com/azure/azure-monitor/app/data-model-complete).
- Prometheus `status: success` with an empty `result` is normal without a
  collector. Distinguish empty Log Analytics rows from query errors caused
  by missing tables. `AzureActivity` needs diagnostic export and ingestion time.
- Empty rows immediately after emission do not establish failure. Wait and
  query again with the same `run_id`; verify arrival in `AppRequests`,
  `AppTraces`, and `AppMetrics`. Arrival can take several minutes or longer,
  and the signals need not appear simultaneously. For the `quickstart.events` metric, compare
  the sum of `valueSum` for that run with the emitted `--count`.
  `flushed: true` alone does not verify ingestion. For SDK warnings, HTTP
  failures, or 403 responses, check the destination, read permissions, and
  network restrictions.

## Docker development

```shell
# build the Docker image
make docker-build

# run FastAPI on http://127.0.0.1:8000/ (Ctrl+C to stop)
make docker-run

# verify the image startup and HTTP routes, then stop it
make docker-smoke-test

# run CI tests in a Docker container
make ci-test-docker
```

The Dockerfile defaults to `serve-container-apps` on `0.0.0.0:8000`, ready for
Container Apps ingress targeting port 8000. To use Compose, create `.env` from
`.env.template` if it does not already exist, then run:

```shell
docker compose up --build
```

Compose uses the same FastAPI startup as the image instead of overriding it
with a file server.

The Docker CI target lints, builds, scans, and makes HTTP requests against the
running image. The Trivy scan currently reports vulnerabilities without
failing the build; review its findings before enabling a blocking severity
threshold.

## Documentation development

The documentation uses Material for MkDocs with `mkdocs-static-i18n` to publish
English and Japanese pages.

```shell
# build both languages
make ci-test-docs

# serve the site locally with live reload
make docs-serve
```

A switch to Zensical requires equivalent multilingual output; unsupported
MkDocs plugins are not run by Zensical.
