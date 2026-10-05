# Monitoring and logs

Read Azure monitoring data and logs from the CLI.
All commands are read-only except the optional telemetry emission exercise.
The CLIs do not assign roles, change diagnostic settings, or deploy collectors.

## 1. Set the read targets

Complete the [development and common Azure setup](scripts.md) and prepare the
resources you need. All features in the
[`azure_observability` Terraform scenario](https://github.com/ks6088ts/template-terraform/tree/main/infra/scenarios/azure_observability)
are off by default. Enable only the required features in that repository.

| Data to read | Required scenario features |
| --- | --- |
| Managed Prometheus | `features.azure_monitor` |
| Log Analytics `AzureActivity` | `features.log_analytics` and `features.activity_log` |
| Application Insights | `features.application_insights` and `features.log_analytics` |
| Network Watcher | `features.network_watcher` |
| Subscription Activity Log API | No feature flag; independent of workspaces |

`features.activity_log` configures export; it does not enable the Activity Log API.
Azure Monitor Workspace is for Prometheus and is separate from Log Analytics.

Read nonsecret outputs from your Terraform checkout:

```shell
terraform -chdir=infra/scenarios/azure_observability output
terraform -chdir=infra/scenarios/azure_observability output -raw azure_monitor_id
```

Set only the values you need in this Python repository's existing `.env`:

| Source | `.env` variable | Value format |
| --- | --- | --- |
| `azure_monitor_id` | `AZURE_MONITOR_ID` | Azure Monitor Workspace ARM ID |
| `log_analytics_workspace_id` | `AZURE_LOG_ANALYTICS_WORKSPACE_ID` | Workspace GUID |
| `application_insights_id` | `AZURE_APPLICATION_INSIGHTS_ID` | Application Insights ARM ID |
| `network_watcher_id` | `AZURE_NETWORK_WATCHER_ID` | Watcher ARM ID |
| `az account show --query id --output tsv` | `AZURE_SUBSCRIPTION_ID` | Subscription GUID |
| `resource_group_name` or the watcher's actual group | `AZURE_RESOURCE_GROUP` | Optional filter; empty for subscription-wide reads |

An ARM ID is a path starting with `/subscriptions/<id>/resourceGroups/<group>/providers/`.
A GUID has the form `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`.
**For Log Analytics, use the GUID, not the `log_analytics_id` ARM ID.**
`activity_log_id` identifies an export setting, not a subscription.
Do not configure `null` outputs for disabled features; skip those exercises.

To override settings, Monitor / Application Insights / Watcher use `--resource-id`,
Log Analytics uses `--workspace-id`, and Activity Log uses `--subscription-id`.

## 2. Check read permissions

Ask an administrator to grant these permissions to the actual calling identity:

| Operation | Role | Scope |
| --- | --- | --- |
| Workspace / Watcher metadata | `Reader` | Target resource; listing needs group or subscription access |
| PromQL queries | `Monitoring Data Reader` | Azure Monitor Workspace |
| Log Analytics queries | `Log Analytics Reader` | Log Analytics workspace |
| Application Insights queries | `Reader` or workspace query access | Application Insights or its backing workspace |
| Activity Log API | `Reader`, including Activity Log read access | Subscription |

PromQL's `Monitoring Data Reader` is not `Monitoring Reader`.
Application Insights can use component-level `Reader` when the workspace permits
resource-based access. Otherwise, grant query access such as `Log Analytics Reader`
on the backing workspace.

See [Prometheus API access](https://learn.microsoft.com/azure/azure-monitor/metrics/prometheus-api-promql)
and [Log Analytics access](https://learn.microsoft.com/azure/azure-monitor/logs/manage-access).

## 3. Read the data you need

Run the remaining commands from the root of this Python repository.
Choose only available targets. Add `--help` to a command to see all options.

### Prometheus: workspace and metrics

```shell
uv run --locked python -m scripts.cli_azure_monitor show-workspace
uv run --locked python -m scripts.cli_azure_monitor query-prometheus --query 'up'
```

The scenario does not deploy a collector. Without a separate collection setup,
`status: success` with an empty `result` is normal.

### Log Analytics: exported Activity Log

```shell
uv run --locked python -m scripts.cli_log_analytics query-logs --hours 24 --limit 100
uv run --locked python -m scripts.cli_log_analytics summarize-activity --hours 24 --limit 100
```

These run fixed `AzureActivity` queries, not arbitrary KQL.
Configure [diagnostic export](https://learn.microsoft.com/azure/azure-monitor/platform/activity-log#export-activity-log)
to the selected workspace and allow ingestion time. Without it, the table may be
missing or empty.

### Application Insights: requests and other telemetry

```shell
uv run --locked python -m scripts.cli_application_insights query-telemetry \
  --table AppRequests --hours 24 --limit 100
```

Reading does not need a connection string. `--table` accepts `AppRequests`,
`AppTraces`, `AppMetrics`, and `AppDependencies`.

### Network Watcher: location and settings

```shell
uv run --locked python -m scripts.cli_network_watcher list-watchers
uv run --locked python -m scripts.cli_network_watcher show-watcher
```

The watcher may be in a different resource group from the scenario.
Leave `AZURE_RESOURCE_GROUP` empty to discover across the subscription.
Select an individual watcher with `show-watcher --resource-id "<watcher-ARM-ID>"`.
These [read-only operations](https://learn.microsoft.com/azure/network-watcher/network-watcher-overview)
do not start packet captures or connectivity tests.

### Activity Log API: subscription operation history

```shell
uv run --locked python -m scripts.cli_activity_log list-events --hours 24 --limit 100
uv run --locked python -m scripts.cli_activity_log summarize-events --hours 24 --limit 100
```

These work without workspace export. A quiet subscription can return no events.
See the [Activity Log overview](https://learn.microsoft.com/azure/azure-monitor/platform/activity-log).

### Filters and summary limits

- Log, telemetry, and Activity Log commands accept `--hours` from 1 to 168
  (default 24) and `--limit` from 1 to 1,000 (default 100).
- `list-watchers`, `list-events`, and `summarize-events` accept
  `--resource-group "<group>"` or `AZURE_RESOURCE_GROUP`.

| Command | What `--limit` limits |
| --- | --- |
| `query-logs`, `query-telemetry` | Returned rows |
| Log Analytics `summarize-activity` | Groups returned after aggregating all matching rows in the time window |
| Activity Log `summarize-events` | Events retrieved and counted; not the total for the time window |

## 4. Instrument the API

The API uses the Azure Monitor OpenTelemetry Distro for FastAPI requests, standard
metrics, correlated package logs, and instrumented HTTP/Azure SDK dependencies.
Application code reads no environment variables directly. Values flow from `.env`
or the hosting environment through Pydantic settings into the process-level
telemetry initializer.

The following defaults keep local development Azure-independent:

```dotenv
PROJECT_NAME=template-azure-python
TELEMETRY_ENABLED=false
TELEMETRY_TRACES_PER_SECOND=5
TELEMETRY_LIVE_METRICS_ENABLED=false
APPLICATIONINSIGHTS_CONNECTION_STRING=
```

`PROJECT_NAME` becomes the OpenTelemetry `service.name` and Application Insights
cloud role name. `TELEMETRY_TRACES_PER_SECOND` is a positive, per-process limit.
Five replicas with the default can therefore sample up to about 25 traces per
second in total. Size it against the number of workers/replicas and the ingestion
budget. Live Metrics is separately controlled because it adds a continuous channel.

### Verify disabled behavior

Leave `TELEMETRY_ENABLED=false`, then run:

```shell
uv run --locked python -m scripts.template serve-container-apps
curl --fail http://127.0.0.1:8000/
```

The expected response is `{"Hello":"World"}`. No connection string is required,
and no Azure Monitor provider is installed.

### Verify fail-fast configuration

Set `TELEMETRY_ENABLED=true` while leaving
`APPLICATIONINSIGHTS_CONNECTION_STRING` empty, then start the server again:

```shell
uv run --locked python -m scripts.template serve-container-apps
```

Startup must fail with a sanitized message stating that the connection string is
not configured. If the API starts, the configuration contract is broken. Do not
paste the secret into the command line to perform this check.

### Verify API telemetry in Azure

Privately set `APPLICATIONINSIGHTS_CONNECTION_STRING` in the Git-ignored `.env`,
keep `TELEMETRY_ENABLED=true`, start the server, and generate requests:

```shell
curl --fail http://127.0.0.1:8000/
curl --fail http://127.0.0.1:8000/docs
```

Allow for ingestion delay, then query the same Application Insights resource:

```shell
uv run --locked python -m scripts.cli_application_insights query-telemetry \
  --table AppRequests --hours 1 --limit 100
```

Find successful `GET /` and `GET /docs` requests. Confirm HTTP status `200` and
that the cloud role/service name matches `PROJECT_NAME`. Sampling means a small
number of requests may not appear; send a bounded batch, wait, and query again
rather than disabling sampling in production.

When an API route makes an instrumented HTTP or Azure SDK call, query
`AppDependencies` and confirm its operation/trace ID links to the parent request.
When code logs through a logger under `template_azure_python`, query `AppTraces`
and confirm the same correlation. Query `AppMetrics` for generated standard or
custom metrics. The root endpoint intentionally does not create fake dependencies,
per-request informational logs, or demo metrics merely to populate these tables.

### Scale and extension boundaries

- The Distro owns batch processing, retries, exporter lifetime, and supported
  FastAPI/Azure SDK instrumentation. The application initializes it once per
  process, never per request.
- Keep resource and metric attributes stable and low-cardinality. Do not attach
  request IDs, user IDs, payloads, tokens, or other sensitive/unbounded values.
- Rate limiting bounds each process, not the whole deployment. Re-evaluate it when
  worker or replica counts change, and monitor ingestion cost and sampling effects.
- Telemetry initialization fails startup only when explicitly enabled. This avoids
  a healthy-looking but unobserved production process while preserving local use.
- Azure Monitor is the only implemented backend. A future OTLP exporter belongs
  behind the initialization boundary; routers and domain code should continue to
  use OpenTelemetry APIs rather than exporter-specific APIs.

## 5. Emit and find telemetry from the CLI, optionally

**Only this step sends data. It may incur ingestion charges.**

### Set the connection string locally

The scenario does not output the connection string. Copy it privately from
Application Insights' Azure portal **Overview** into the Git-ignored `.env` as
`APPLICATIONINSIGHTS_CONNECTION_STRING`, or set it using local secret management.

Keep the template value empty. Never paste it into source, shell arguments or
history, logs, screenshots, or shared output. There is no connection-string CLI
option. See [connection strings](https://learn.microsoft.com/azure/azure-monitor/app/connection-strings)
and [Python OpenTelemetry](https://learn.microsoft.com/azure/azure-monitor/app/opentelemetry-enable?tabs=python).

The internal adapter obtains the value from the central settings package as a
`SecretStr`, excluded from settings dumps. SDK-only environment controls are
temporary and restored after emission. See [architecture](architecture/index.md).

### Emit a sample

```shell
uv run --locked python -m scripts.cli_application_insights emit-telemetry --count 10
```

`--count` accepts 1 to 100 (default 10). The command emits server spans,
correlated logs, and metric increments, then prints a unique `run_id`.
It does not create dependency spans. Flush failures and observed SDK warnings
are reported. **`flushed: true` means local provider flushing completed, not that
Azure accepted or ingested the data.**

### Find data from the same run

Allow ingestion time, then check recent requests and each signal using the printed UUID:

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

`--run-id` is optional, but must be a UUID when supplied.

| Check | Field or value |
| --- | --- |
| Time | `timestamp` |
| Run ID | `customDimensions.run_id` |
| `quickstart.events` metric | Compare the run's sum of `valueSum` with `--count` |

The CLI maps table aliases to the resource API's `requests`, `traces`,
`customMetrics`, and `dependencies`. JSON columns retain that API's format.
Metrics are aggregated, so compare values rather than row counts.

Scenario sampling defaults to 25%. Client-side sampling is separate; the emitter
uses `always_on`. Span and log row counts may not equal `--count`, and signals
may arrive at different times. See [sampling](https://learn.microsoft.com/azure/azure-monitor/app/opentelemetry-sampling)
and [ingestion latency](https://learn.microsoft.com/azure/azure-monitor/logs/data-ingestion-time).
If data is missing, wait and query the same `run_id` again rather than resending without limits.

Remove the local connection string when finished.
**Deleting local settings does not stop Azure charges.**

## Troubleshooting

| Symptom | Action |
| --- | --- |
| `Missing option` | Add the IDs from the mapping to `.env` or pass CLI options; `az login` does not set them |
| Variables missing from an old `.env` | Add them to the existing file; template updates are not applied automatically |
| Only some resource groups appear | Check the `AZURE_RESOURCE_GROUP` filter |
| 403 | Check identity, tenant, role scope, propagation time, and network restrictions |
| Missing `AzureActivity` | Check diagnostic export to the chosen workspace and ingestion |
| Application Insights table error | Update the CLI; resource and workspace APIs use different schemas |
| Emitted data not found | Query the same `run_id`; check destination, query target, sampling, SDK warnings, and network access |

CLI options and temporary environment variables do not persist to later terminals.
After configuration, run the commands in a normal terminal again.
In the [Application Insights schema](https://learn.microsoft.com/azure/azure-monitor/app/data-model-complete),
do not confuse resource API `timestamp` / `customDimensions` with workspace
`TimeGenerated` / `Properties`.
