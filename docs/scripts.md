# Local development

Set up development, start the API, and test your changes.
The default InMemory backend with telemetry disabled runs without connecting to Azure.
Run all commands below from the repository root.

## Required tools

Start with Python, uv, and Make. Install the other tools only when you need them.

| Tool | When you need it |
| --- | --- |
| [Python 3.10+](https://www.python.org/downloads/) | All Python commands. CI tests 3.10 through 3.14 |
| [uv 0.12.19](https://docs.astral.sh/uv/getting-started/installation/) | Managing dependencies and running commands |
| [GNU Make](https://www.gnu.org/software/make/) | `make` commands |
| `curl` | Checking API responses |
| [actionlint](https://github.com/rhysd/actionlint) | `make lint` and `make ci-test`. CI uses v1.7.12 |
| [Docker](https://docs.docker.com/get-docker/) | Docker and Compose |
| [Azure Functions Core Tools v4](https://learn.microsoft.com/azure/azure-functions/functions-run-local) | Running Functions locally |
| [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) | Azure sample authentication and deployment |

## 1. Set up development

```shell
make install-deps-dev
```

This installs all development dependencies and the [prek](https://prek.j178.dev/)
Git hook. **It replaces any existing pre-commit hook.**
CI uses a smaller dependency set without JupyterLab. Paid LLM evaluation dependencies are excluded from both
default development and CI installation; see [LLM evaluation](evaluation.md) for the optional `eval` group.

## 2. Run FastAPI

### Start the server

```shell
uv run --locked python -m scripts.template serve-container-apps
```

The default URL is `http://127.0.0.1:8000`.
Press `Ctrl+C` in the server terminal to stop it.

### Check the response

Run these commands from another terminal:

```shell
curl http://127.0.0.1:8000/tasks
curl -I http://127.0.0.1:8000/docs
```

Initially the first command returns `[]`; the second returns HTTP 200. The removed mock `/` returns 404.
Open <http://127.0.0.1:8000/docs> in a browser to try the API.

### Change the address or port

Stop the default server before running:

```shell
uv run --locked python -m scripts.template serve-container-apps --host 0.0.0.0 --port 8080
```

This example listens on all network interfaces.
Use `--host 127.0.0.1` to restrict it to your own machine.

### Select storage

Use `--repository in-memory` (default), `--repository cosmosdb`, or `--repository duckdb`.
When omitted, `TASK_REPOSITORY` resolves from OS environment → `.env` → default.
See [Cosmos DB](cosmosdb.md#task-api-persistence-and-container-management) for settings, permissions,
and container preparation. The API never creates resources automatically.

```shell
uv run --locked python -m scripts.template serve-container-apps --repository cosmosdb
```

If selecting Cosmos DB fails at startup with `CosmosResourceNotFoundError, status=404`,
follow [Task API startup troubleshooting](cosmosdb.md#task-api-startup-troubleshooting)
to check effective settings and Azure resources and safely prepare the missing dedicated Task container.

Direct `uvicorn template_azure_python.api:app` also reads `TASK_REPOSITORY`.
Pass the same environment settings to Docker/Compose. InMemory is isolated per app;
Cosmos shares the configured container.

For a local dbt-built DuckDB, first complete the [dbt quick run](dbt/index.md).
Stop other connections to that file, then set its **existing** absolute path:

```shell
export DUCKDB_PATH="$DBT_PROJECT_DIR/task_analytics.duckdb"
export TELEMETRY_ENABLED=false
uv run --locked python -m scripts.template serve-container-apps --repository duckdb
```

`GET /tasks` now returns the six sample Tasks, not an empty array.
The same `--repository duckdb` option works with `serve-functions`; export `DUCKDB_PATH`
in the terminal that starts the launcher. Direct Uvicorn additionally needs `TASK_REPOSITORY=duckdb`.
Missing files or an incompatible `main.fct_tasks` table fail explicitly; the API never creates them.
This is a **single-process local exercise**, not a distributed persistence option.
Stop the API before running dbt against the same file.
API writes update only `fct_tasks`, not raw data or reports; rebuilding with dbt overwrites them.
Follow the [API integration exercise](dbt/tutorial.md#8-connect-the-task-api-and-verify-persistence)
and [storage and analytics extension guide](dbt/backends.md) for verification and design details.

## 3. Run with Functions, if needed

**Extra tool**: Azure Functions Core Tools v4.
This runs the same FastAPI app in a local Functions host.

### Prepare local settings

Copy the example only if the settings file does not exist:

```shell
test -f local.settings.json || cp local.settings.json.example local.settings.json
```

This HTTP-only sample works with an empty `AzureWebJobsStorage`.
To clear storage health warnings, start Azurite and set that value to
`UseDevelopmentStorage=true`. Other triggers need a valid storage connection.

### Start and check the host

```shell
uv run --locked python -m scripts.template serve-functions
```

From another terminal:

```shell
curl http://127.0.0.1:7071/tasks
curl -I http://127.0.0.1:7071/docs
```

Expect an initial `[]` and HTTP 200.
To use a different port, add an option such as `--port 7072` to the start command.
This command also accepts `--repository cosmosdb` or `TASK_REPOSITORY`.
The CLI passes selection to the Functions child process without changing the parent environment.

### Before publishing

- `function_app.py` loads the same FastAPI app through `AsgiFunctionApp`, following
  the [Azure sample](https://github.com/Azure-Samples/fastapi-on-azure-functions).
- `host.json` removes the `/api` prefix, so the URLs are `/tasks` and `/docs`.
- The HTTP trigger is **anonymous**. Add access controls before handling sensitive data.
- In Azure, the runtime loads `function_app.py` directly. This CLI is only for local use.
- `.env` and `local.settings.json` are excluded from publishing and Docker builds.
  See the [deployment guide](deployment.md) to publish the app.

## 4. Check your changes

Choose the command that matches your goal. You do not need to run every command each time.

| Goal | Command |
| --- | --- |
| List available Make commands | `make` |
| Run tests | `make test` |
| Run Git hook checks | `make hooks-check` |
| Check code, types, and GitHub Actions configuration | `make lint` |
| Prepare dependencies and run format, lint, and test checks | `make ci-test` |
| Start JupyterLab | `make jupyterlab` |

`make lint` runs [zizmor](https://zizmor.sh/) offline and fails on
high-severity GitHub Actions findings. Run
`uv run --locked zizmor --offline .` to see lower-severity findings too.

## Run with Docker, if needed

Start Docker, then build the image:

```shell
make docker-build
```

Start the server at `http://127.0.0.1:8000`. Press `Ctrl+C` to stop it.

```shell
make docker-run
```

The Dockerfile starts `serve-container-apps` on `0.0.0.0:8000`.
`make docker-run` restricts the host port to `127.0.0.1`.

### Check the image

| Check | Command |
| --- | --- |
| Start a container, check `/tasks` and `/docs`, then stop it | `make docker-smoke-test` |
| Run Dockerfile lint, build, scan, and startup checks | `make ci-test-docker` |

The smoke test starts its own container; it does not need `make docker-run` to be running.
The Trivy scan currently reports vulnerabilities without failing the build.

### Use Compose

```shell
test -f .env || cp .env.template .env
docker compose up --build
```

Compose starts the same FastAPI app.

To check Azure live monitoring from a local process, follow the
[Live Metrics verification steps](monitoring.md#verify-live-metrics-display-with-the-local-api).
Compose passes `.env` into the container and overrides `PROJECT_NAME` to `hello`.
The current port mapping exposes all interfaces; for local-only access,
change the port in `compose.yml` to `127.0.0.1:8000:8000`.

## Common setup for Azure samples

To send a local OpenTelemetry sample and check stored data in Azure portal, follow
the [emission and KQL instructions](monitoring.md#5-emit-and-find-telemetry-from-the-cli-optionally).
No API server is needed.

Complete these steps only if you want to try an Azure sample:

1. Install Azure CLI and prepare the service resources you will use.
2. Copy `.env` only if it does not exist, then fill in the settings for your service.

   ```shell
   test -f .env || cp .env.template .env
   ```

3. Sign in and check the subscription and identity.

   ```shell
   az login
   az account show --query "{subscription:name,tenantId:tenantId,user:user.name}" --output table
   ```

   If needed, switch with `az account set --subscription "<subscription-id>"`.

4. Follow the service guide to grant access to the identity that actually runs the commands.

Azure sample settings take precedence in this order:
**CLI options, exported shell variables, `.env`, defaults**.
Update only the variables you need; do not overwrite an existing `.env`.
The file is Git-ignored. Never commit secrets.

Authentication uses `DefaultAzureCredential`: it can use `az login` locally
or a managed identity in Azure. Other configured credentials can take precedence.
A managed identity does not inherit your local user's permissions.

Application settings are loaded by `template_azure_python.settings` using Pydantic Settings.
The relative `.env` path uses the current working directory and does not search parents.
SDK-owned authentication variables must be exported in the OS or hosting environment;
dotenv values are not injected into the process environment.
See [architecture](architecture/index.md) for configuration and SDK boundaries.

| Sample | Guide |
| --- | --- |
| AI models and agents | [Microsoft Foundry](foundry.md) |
| Data storage and retrieval | [Azure Cosmos DB](cosmosdb.md) |
| Events and messages | [Messaging](messaging.md) |
| Monitoring data and logs | [Monitoring and logs](monitoring.md) |

## CLI help and basic commands

A CLI is a command-line interface. Use `--help` to see its options:

```shell
uv run --locked python -m scripts.template --help
uv run --locked python -m scripts.template hello
uv run --locked python -m scripts.template --verbose hello --name Azure
```

The basic commands use the same settings package and precedence. They read `.env`
when present, or use OS values and defaults when it is absent.

## Edit the documentation, if needed

| Goal | Command |
| --- | --- |
| Build the English and Japanese pages | `make ci-test-docs` |
| Preview with live reload | `make docs-serve` |

The site uses Material for MkDocs and `mkdocs-static-i18n` for both languages.
A move to Zensical or another tool must preserve this multilingual output.
Zensical does not run unsupported MkDocs plugins.
