# Messaging

Send and receive events or messages with four Azure services.
**Run only the sections for the services you want to use.**

| Service | What this sample does | Receive behavior |
| --- | --- | --- |
| Event Grid | Publish to a Basic Custom Topic | No receive command |
| Event Hubs | Send and receive events | Does not delete events or save the read position |
| Service Bus | Send and receive Queue messages | **Deletes messages after displaying them** |
| Queue Storage | Create, retrieve, update, and delete queues and messages | Hides messages temporarily; deletion is separate |

Use test queues for Service Bus receive and Queue Storage deletion.
Trying these operations on an existing application's queue can lose messages.

## 1. Set the endpoints

Complete the [development and common Azure setup](scripts.md) and prepare the
resources you need. If you use the
[`azure_messaging` Terraform scenario](https://github.com/ks6088ts/template-terraform/tree/main/infra/scenarios/azure_messaging),
all services are off by default. Enable the ones you need using that repository's
instructions. No Terraform changes are needed in this Python repository.

Read settings from your Terraform checkout:

```shell
terraform -chdir=infra/scenarios/azure_messaging output
terraform -chdir=infra/scenarios/azure_messaging output -raw event_grid_topic_endpoint
```

Set the outputs for your chosen services in this Python repository's `.env`.
Do not copy `null` or absent outputs for disabled services.

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

- Set namespaces to **hostnames only**, such as `<namespace>.servicebus.windows.net`.
- Use HTTPS URLs for Event Grid and Queue Storage. Use the Queue URL, not Blob or DFS.
- `$Default` is a literal name. Quote it as `'$Default'` in shell commands.
- Authentication uses only `DefaultAzureCredential`, not connection strings,
  shared keys, or SAS. The Terraform scenario also disables shared-key data access.

## 2. Check access

The scenario grants these roles to `operator_principal_id`, which defaults to
the Terraform operator. If a different identity runs the CLI, ask an administrator
to grant it the required roles.

| Service | Required roles | Scope (Terraform output) |
| --- | --- | --- |
| Event Grid | `EventGrid Data Sender` | Topic (`event_grid_topic_id`) |
| Event Hubs | `Azure Event Hubs Data Sender`, `Azure Event Hubs Data Receiver` | Namespace (`event_hubs_namespace_id`) |
| Service Bus | `Azure Service Bus Data Sender`, `Azure Service Bus Data Receiver` | Namespace (`service_bus_namespace_id`) |
| Queue Storage | `Storage Queue Data Contributor` | Storage account (`queue_storage_account_id`) |

`Owner` / `Contributor` alone does not provide these data permissions.
Replace the placeholders and check assignments for the calling identity:

```shell
az account show --query "{subscription:name,tenantId:tenantId,user:user.name}" --output table
MESSAGING_SCOPE="<resource-ID-from-the-table>"
PRINCIPAL_ID="<calling-principal-object-ID>"
az role assignment list \
  --scope "$MESSAGING_SCOPE" --include-inherited \
  --query "[?principalId=='${PRINCIPAL_ID}'].{role:roleDefinitionName,scope:scope}" \
  --output table
```

For an Azure-hosted app, check its managed identity.
Allow several minutes for new assignments to take effect.

## 3. Run your service's commands

Run the CLIs below from the root of this Python repository.
Add `--help` to any command to see all options and defaults.

### Event Grid: publish events

```shell
uv run --locked python -m scripts.cli_event_grid publish-event
uv run --locked python -m scripts.cli_event_grid publish-events --count 3
```

These publish a single event or an event list in one send call.
The result is one JSON line containing `schema`, `count`, and `ids`.
Publishing does not create a destination; the scenario creates no event subscriptions.

#### Match the input schema

| Topic `inputSchema` | CLI setting |
| --- | --- |
| `EventGridSchema` (Terraform default) | Omit the option, or use `--schema event-grid` |
| `CloudEventSchemaV1_0` | `--schema cloud-event` |

A mismatch causes `BadRequest`. The CLI cannot change the topic's schema.
For CloudEvents, first apply `event_grid_input_schema = "CloudEventSchemaV1_0"`
in the scenario. Then run this against that topic:

```shell
uv run --locked python -m scripts.cli_event_grid publish-event \
  --schema cloud-event --source "/samples/orders" \
  --subject "orders/42" --event-type "Sample.OrderCreated" --data '{"orderId":42}'
```

`--data` must be a JSON object. `--data-version` is Event Grid schema metadata,
not a CloudEvent version setting. `CustomEventSchema` and Namespace receive,
acknowledgment, and lock operations are not supported.

### Event Hubs: send and receive events

```shell
uv run --locked python -m scripts.cli_event_hubs send-events
uv run --locked python -m scripts.cli_event_hubs receive-events \
  --consumer-group '$Default' --starting-position '-1' \
  --max-events 3 --max-wait-time 30
```

The default send puts three events into one SDK batch.
To change the bodies, use options such as `--message "First event" --message '{"orderId":42}'`.
Sending prints `{"sent": N}`; receiving prints event JSON followed by `{"received": N}`.

| Receive option | Default and meaning |
| --- | --- |
| `--max-events` | 100; accepts 1 to 10,000 |
| `--max-wait-time` | 15 seconds; maximum inactivity across all partitions |
| `--starting-position` | `-1`, the start of retained events. `@latest` reads only new events after connection |
| `--consumer-group` | `$Default` |

Receiving stops at the count limit or inactivity timeout. Each event resets the
timeout; an idle partition does not stop other active partitions.
The initial wait includes authentication, connection, and partition discovery.

Event JSON contains `body`, `partition_id`, `offset`, `sequence_number`, and
`enqueued_time`. An empty receive still ends with `{"received": 0}`.
Receiving is non-destructive but **does not save checkpoints**, so a later run
may read the same events. The Blob checkpoint store is excluded because the
scenario provides neither a Blob container nor `Storage Blob Data Contributor`.

### Service Bus: send and receive Queue messages

**Received messages are completed and removed from the queue after display.**
Check that `.env` points to a test queue.

```shell
uv run --locked python -m scripts.cli_service_bus send-message
uv run --locked python -m scripts.cli_service_bus send-message-list
uv run --locked python -m scripts.cli_service_bus send-message-batch
uv run --locked python -m scripts.cli_service_bus receive-messages \
  --max-messages 10 --max-wait-time 5
```

| Send command | Behavior |
| --- | --- |
| `send-message` | Send one message |
| `send-message-list` | Send a list in one call; three messages by default |
| `send-message-batch` | Send an SDK batch; three messages by default |

Use `--message` for the body and `--count` for list / batch size.
A batch exceeding capacity fails explicitly; reduce the count or message size.
Sending prints `{"sent": N}`. Receiving prints each message's `body`, `message_id`,
and metadata, then `{"received": N}`, with one object per line.
Receive defaults to ten messages and a 5-second wait.
The scenario's Topic / Subscription is not supported by this Queue-only CLI.

### Queue Storage: try the lifecycle with a test queue

Create a unique queue and pass `--queue` for every operation.
**Do not substitute the Terraform-managed queue.**
Use lowercase letters, numbers, and hyphens in the queue name.

#### 1. Create, send, and retrieve

```shell
SCRATCH_QUEUE="messaging-cli-scratch-$(date +%s)"
uv run --locked python -m scripts.cli_queue_storage create-queue --queue "$SCRATCH_QUEUE"
uv run --locked python -m scripts.cli_queue_storage send-message \
  --queue "$SCRATCH_QUEUE" --message "Please update me"
uv run --locked python -m scripts.cli_queue_storage peek-messages --queue "$SCRATCH_QUEUE"
uv run --locked python -m scripts.cli_queue_storage get-queue-length --queue "$SCRATCH_QUEUE"
uv run --locked python -m scripts.cli_queue_storage receive-messages \
  --queue "$SCRATCH_QUEUE" --max-messages 1 --visibility-timeout 120
```

Peek only displays messages. Receive hides them for 120 seconds in this example;
it does not delete them. Receive returns `{"received": N, "messages": [...]}`,
or `{"received": 0, "messages": []}` when empty.
Queue length is approximate and is not a count of only visible messages.

#### 2. Update the message

Copy `id` and `pop_receipt` from **the same message** in the receive output.
Run this before the visibility timeout expires:

```shell
MESSAGE_ID="<message-ID-from-receive>"
POP_RECEIPT="<matching-pop-receipt-from-receive>"
uv run --locked python -m scripts.cli_queue_storage update-message \
  --queue "$SCRATCH_QUEUE" --message-id "$MESSAGE_ID" --pop-receipt "$POP_RECEIPT" \
  --message "Updated content" --visibility-timeout 120
```

Update returns a new `pop_receipt`; receiving again also changes it.
Always use the latest receipt for updates and deletion.

#### 3. Delete the message and test queue

Use the receipt from the update, delete the message, and confirm queue deletion.
**Deleting a queue also deletes all remaining messages.**

```shell
POP_RECEIPT="<new-pop-receipt-from-update>"
uv run --locked python -m scripts.cli_queue_storage delete-message \
  --queue "$SCRATCH_QUEUE" --message-id "$MESSAGE_ID" --pop-receipt "$POP_RECEIPT"
uv run --locked python -m scripts.cli_queue_storage delete-queue --queue "$SCRATCH_QUEUE"
```

Declining confirmation cancels without calling Azure.
For noninteractive use, explicitly pass `delete-queue --queue "$SCRATCH_QUEUE" --yes`.

#### Options and output

- Peek / receive default to one message; `--max-messages` accepts 1 to 32.
- Receive defaults to a 30-second visibility timeout; send / update default to zero.
  Keep `--visibility-timeout` below the remaining message lifetime, which defaults to seven days.
- Send / update return JSON containing `id` and `pop_receipt`; peek has no receipt.
  Each result occupies one JSON line. Messages not deleted become available after the timeout.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| Missing required options | Set the matching `.env` variables; do not overwrite the file |
| Changes to `.env` have no effect | Remove stale exported variables or pass CLI options |
| Missing Terraform plugins | Run `terraform -chdir=infra/scenarios/azure_messaging init` in the Terraform checkout |
| Unauthorized / forbidden | Check the calling identity, tenant, roles above, and network restrictions |
| Event Hubs returns zero | Retry with `--max-wait-time 30 --starting-position '-1'`; check the endpoint and receive role |
| Event Grid rejects the schema | Match `--schema` to the topic's `inputSchema` |
| Queue Storage update / delete fails | Use the latest `pop_receipt` for that message |

## Reference: retrieve settings from Azure

If Terraform outputs are unavailable, use these read commands to get settings.
Sign in, select the subscription, and **run only the commands for your services**.
Reading configuration or testing the CLIs does not require `terraform apply`.

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

If a namespace returns `https://example.servicebus.windows.net:443/`, use only
`example.servicebus.windows.net`. Keep the full URLs for Event Grid / Queue Storage.
Listing queues also needs its data role. No secrets or account keys are needed.

## Further reading

- [Event Grid Python SDK](https://learn.microsoft.com/en-us/python/api/overview/azure/eventgrid-readme?view=azure-python)
- [Event Hubs Python quickstart](https://learn.microsoft.com/en-us/azure/event-hubs/event-hubs-python-get-started-send?tabs=passwordless%2Croles-azure-portal)
- [Service Bus Queue Python quickstart](https://learn.microsoft.com/en-us/azure/service-bus-messaging/service-bus-python-how-to-use-queues?tabs=passwordless)
- [Queue Storage Python quickstart](https://learn.microsoft.com/en-us/azure/storage/queues/storage-quickstart-queues-python?tabs=passwordless%2Croles-azure-portal%2Cenvironment-variable-windows%2Csign-in-azure-cli)
