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
  Microsoft Foundry sample and publishing to existing Azure resources

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
