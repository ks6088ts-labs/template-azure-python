[![test](https://github.com/ks6088ts-labs/template-azure-python/actions/workflows/test.yaml/badge.svg?branch=main)](https://github.com/ks6088ts-labs/template-azure-python/actions/workflows/test.yaml?query=branch%3Amain)
[![docker](https://github.com/ks6088ts-labs/template-azure-python/actions/workflows/docker.yaml/badge.svg?branch=main)](https://github.com/ks6088ts-labs/template-azure-python/actions/workflows/docker.yaml?query=branch%3Amain)
[![docker-release](https://github.com/ks6088ts-labs/template-azure-python/actions/workflows/docker-release.yaml/badge.svg)](https://github.com/ks6088ts-labs/template-azure-python/actions/workflows/docker-release.yaml)
[![ghcr-release](https://github.com/ks6088ts-labs/template-azure-python/actions/workflows/ghcr-release.yaml/badge.svg)](https://github.com/ks6088ts-labs/template-azure-python/actions/workflows/ghcr-release.yaml)
[![docs](https://github.com/ks6088ts-labs/template-azure-python/actions/workflows/github-pages.yaml/badge.svg)](https://github.com/ks6088ts-labs/template-azure-python/actions/workflows/github-pages.yaml)

# template-azure-python

A template repository for Python projects.

## Documentation

| Topic | English | 日本語 |
| --- | --- | --- |
| Home | [Overview](https://ks6088ts-labs.github.io/template-azure-python/) | [概要](https://ks6088ts-labs.github.io/template-azure-python/ja/) |
| Scripts and development | [Guide](https://ks6088ts-labs.github.io/template-azure-python/scripts/) | [ガイド](https://ks6088ts-labs.github.io/template-azure-python/ja/scripts/) |
| Deployment | [Guide](https://ks6088ts-labs.github.io/template-azure-python/deployment/) | [ガイド](https://ks6088ts-labs.github.io/template-azure-python/ja/deployment/) |

## Azure Messaging CLIs

Event Grid, Event Hubs, Service Bus, and Queue Storage use `.env` configuration
and `DefaultAzureCredential`, without connection strings or shared keys.
See the [English guide](docs/scripts.md#azure-messaging-clis) or
[日本語ガイド](docs/scripts.ja.md) for the Terraform output mapping, required
RBAC, and commands. Preserve existing `.env` settings when adding messaging
values, run commands from the repository root, and sign in with `az login`.

### Troubleshooting

| Symptom | What to check |
| --- | --- |
| Missing `--endpoint`, `--fully-qualified-namespace`, or queue options | Populate the corresponding `.env` variables; do not replace an existing file with the template. |
| Updated `.env` values are not used | Exported shell variables take precedence because `load_dotenv(override=False)` preserves them; explicit CLI options override both. Remove stale exports or pass the desired option. |
| `terraform output` reports `Required plugins are not installed` | Run `terraform init` in the Terraform scenario, or [retrieve configuration directly from Azure](docs/scripts.md#recover-configuration-from-azure). Reading existing resources does not require `terraform apply`. |
| Unauthorized or forbidden errors | Check the identity selected by `DefaultAzureCredential`, tenant, and [data-plane RBAC](docs/scripts.md#required-messaging-rbac). `Owner`/`Contributor` alone is not sufficient; also check network restrictions. |
| Event Hubs returns `{"received": 0}` despite retained events | The default 15-second timeout includes initial authentication, connection, and partition discovery. Try `--max-wait-time 30 --starting-position '-1'`; `@latest` only reads new events. |
| Event Grid rejects the event schema | Match `--schema` to the topic's `inputSchema`: `event-grid` for `EventGridSchema`, `cloud-event` for `CloudEventSchemaV1_0`. |
| Queue Storage update/delete fails | Use the latest `pop_receipt` returned by receive or update; either operation invalidates the previous receipt. |

Use dedicated scratch queues for lifecycle checks. Service Bus receive completes
and deletes messages; Queue Storage queue deletion removes all messages. Never
use an existing application queue for destructive smoke tests.
