[![test](https://github.com/ks6088ts/template-azure-python/actions/workflows/test.yaml/badge.svg?branch=main)](https://github.com/ks6088ts/template-azure-python/actions/workflows/test.yaml?query=branch%3Amain)
[![docker](https://github.com/ks6088ts/template-azure-python/actions/workflows/docker.yaml/badge.svg?branch=main)](https://github.com/ks6088ts/template-azure-python/actions/workflows/docker.yaml?query=branch%3Amain)
[![docker-release](https://github.com/ks6088ts/template-azure-python/actions/workflows/docker-release.yaml/badge.svg)](https://github.com/ks6088ts/template-azure-python/actions/workflows/docker-release.yaml)
[![ghcr-release](https://github.com/ks6088ts/template-azure-python/actions/workflows/ghcr-release.yaml/badge.svg)](https://github.com/ks6088ts/template-azure-python/actions/workflows/ghcr-release.yaml)
[![docs](https://github.com/ks6088ts/template-azure-python/actions/workflows/github-pages.yaml/badge.svg)](https://github.com/ks6088ts/template-azure-python/actions/workflows/github-pages.yaml)

# template-azure-python

This is a template repository for Python

## Prerequisites

- [Python 3.10+](https://www.python.org/downloads/) (CI tests 3.10 through 3.14)
- [uv 0.12.19](https://docs.astral.sh/uv/getting-started/installation/)
- [GNU Make](https://www.gnu.org/software/make/)
- [actionlint](https://github.com/rhysd/actionlint) for local lint/CI checks (CI uses v1.7.12)
- [Docker](https://docs.docker.com/get-docker/) for the Docker targets
- [Azure Functions Core Tools v4](https://learn.microsoft.com/azure/azure-functions/functions-run-local) for running Functions locally
- `curl` for the HTTP checks below
- [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) for publishing to existing Azure resources

## Development instructions

### Local development

Use Makefile to run the project locally.

```shell
# help
make

# install dependencies for development
make install-deps-dev

# check all configured hooks
make hooks-check

# run tests
make test

# run CI tests
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

### FastAPI on Azure Container Apps (or local Uvicorn)

The same FastAPI app in `template_azure_python/api.py` is used by both hosts.
Start it with Uvicorn locally:

```shell
uv run --locked python -m scripts.template serve-container-apps
```

It listens on `http://127.0.0.1:8000` by default. Use `--host` and `--port`
to change the listening address, for example:

```shell
uv run --locked python -m scripts.template serve-container-apps --host 0.0.0.0 --port 8080
```

Check the default server from another terminal:

```shell
curl http://127.0.0.1:8000/
# {"Hello":"World"}
curl -I http://127.0.0.1:8000/docs
```

Interactive API documentation is available at `http://127.0.0.1:8000/docs`.

### FastAPI on Azure Functions

The root-level `function_app.py` wraps that **same** FastAPI app with Azure
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
health warning with the empty value even while these HTTP routes work; to
satisfy the health check, run Azurite and set `AzureWebJobsStorage` to
`UseDevelopmentStorage=true` in `local.settings.json`. Install Core Tools v4
and start the local Functions host:

```shell
uv run --locked python -m scripts.template serve-functions
# Or use a different local port: ... serve-functions --port 7072
```

From another terminal, verify both the API and its documentation:

```shell
curl http://127.0.0.1:7071/
# {"Hello":"World"}
curl -I http://127.0.0.1:7071/docs
```

The CLI starts Core Tools only for local development. In Azure, the Functions
runtime discovers `function_app.py` directly; it does not run this CLI.
The private `local.settings.json` and `.env` are excluded from Functions
publishing and Docker builds.

### Docker development

```shell
# build docker image
make docker-build

# run the FastAPI server on http://127.0.0.1:8000/ (Ctrl+C to stop)
make docker-run

# verify the image's default startup and HTTP routes, then stop it
make docker-smoke-test

# run CI tests in docker container
make ci-test-docker
```

The Dockerfile defaults to `serve-container-apps` on `0.0.0.0:8000`, ready for
Container Apps ingress targeting port 8000. To use Compose, create `.env`
from `.env.template` if it does not already exist, then run
`docker compose up --build`. Compose now uses the same FastAPI startup as the
image instead of overriding it with a file server.

The Docker CI target lints, builds, scans, and makes HTTP requests against the
running image. The Trivy scan currently reports vulnerabilities without
failing the build; review its findings before enabling a blocking severity
threshold.

The documentation uses Material for MkDocs with `mkdocs-static-i18n` to publish
both languages. A switch to Zensical requires equivalent multilingual output;
unsupported MkDocs plugins are not run by Zensical.

## Deployment instructions

### Azure Functions (existing Python Function App)

Use an existing Linux Function App configured for a supported Python version,
Functions runtime v4, and an Azure Storage account. Log in to Azure with
`az login`. Before **each** publish, generate the standard Python dependency
file from `uv.lock` (the file is intentionally ignored by Git but included in
Functions publishing):

```shell
uv export --locked --format requirements-txt --no-dev --no-hashes --no-emit-project --output-file requirements.txt
FUNCTION_APP_NAME=your-function-app-name
func azure functionapp publish "$FUNCTION_APP_NAME" --build remote
curl "https://$FUNCTION_APP_NAME.azurewebsites.net/"
# {"Hello":"World"}
```

Remote build installs `requirements.txt`; no second FastAPI implementation or
Functions-specific Docker image is required. Set any application settings in
Azure rather than publishing `local.settings.json`.

#### Reusing the `azure_functions_flex_consumption` Terraform scenario

If the
[azure_functions_flex_consumption scenario](https://github.com/ks6088ts/template-terraform/tree/main/infra/scenarios/azure_functions_flex_consumption)
has already been applied, publish this repository to its existing Function App.
Terraform provisions the infrastructure but does not publish application code.
Run these commands from the root of this repository, and set `SCENARIO_DIR` to
the local scenario directory connected to the same Terraform state used for the
deployment. In addition to the prerequisites above, Terraform must be installed
and initialized for that state.

```shell
SCENARIO_DIR=/absolute/path/to/template-terraform/infra/scenarios/azure_functions_flex_consumption
az login
SUBSCRIPTION_ID=$(terraform -chdir="$SCENARIO_DIR" output -raw subscription_id)
FUNCTION_APP_ID=$(terraform -chdir="$SCENARIO_DIR" output -raw function_app_id)
FUNCTION_APP_NAME=$(terraform -chdir="$SCENARIO_DIR" output -raw function_app_name)
FUNCTION_APP_URL=$(terraform -chdir="$SCENARIO_DIR" output -raw function_app_url)
az account set --subscription "$SUBSCRIPTION_ID"
az functionapp show --ids "$FUNCTION_APP_ID" --query "{name:name,state:state,defaultHostName:defaultHostName}" --output table
```

Confirm that the displayed app is the intended target. Then export the locked
runtime dependencies and publish with a Flex-compatible remote build:

```shell
uv export --locked --format requirements-txt --no-dev --no-hashes --no-emit-project --output-file requirements.txt
func azure functionapp publish "$FUNCTION_APP_NAME" --subscription "$SUBSCRIPTION_ID" --build remote --python
```

Do not use the Terraform scenario's `scripts/publish_code.sh` for this
application: that script stages and publishes the scenario's bundled `src/`
sample instead of this repository's `function_app.py` and
`template_azure_python/` package. Re-run the export and publish commands after
changing the application or its dependencies.

The scenario disables Microsoft Entra authentication by default. Verify that
deployment with:

```shell
curl --fail --show-error "$FUNCTION_APP_URL/"
# {"Hello":"World"}
curl --fail --show-error --output /dev/null "$FUNCTION_APP_URL/docs"
```

If the scenario was applied with `enable_authentication=true`, acquire a token
for the exact application ID URI from the same Terraform state and include it
in both requests:

```shell
AUTH_RESOURCE=$(terraform -chdir="$SCENARIO_DIR" output -raw function_app_authentication_identifier_uri)
ACCESS_TOKEN=$(az account get-access-token --subscription "$SUBSCRIPTION_ID" --resource "$AUTH_RESOURCE" --query accessToken --output tsv)
curl --fail --show-error --header "Authorization: Bearer $ACCESS_TOKEN" "$FUNCTION_APP_URL/"
# {"Hello":"World"}
curl --fail --show-error --output /dev/null --header "Authorization: Bearer $ACCESS_TOKEN" "$FUNCTION_APP_URL/docs"
unset ACCESS_TOKEN
```

The published HTTP trigger is anonymous at the Functions host. With
`enable_authentication=true`, the scenario's App Service authentication layer
requires the bearer token before requests reach that trigger.

### Azure Container Apps (existing Container App)

Push the Docker image to a registry that the existing Container App can pull
from. Configure its HTTP ingress target port to **8000**, then update its
image (replace the placeholders with your own resources):

```shell
IMAGE=your-registry.example.com/template-azure-python:your-tag
RESOURCE_GROUP_NAME=your-resource-group-name
CONTAINER_APP_NAME=your-container-app-name

docker build -t "$IMAGE" .
docker push "$IMAGE"
az containerapp ingress enable --name "$CONTAINER_APP_NAME" --resource-group "$RESOURCE_GROUP_NAME" --type external --target-port 8000
az containerapp update --name "$CONTAINER_APP_NAME" --resource-group "$RESOURCE_GROUP_NAME" --image "$IMAGE"

CONTAINER_APP_FQDN=$(az containerapp show --name "$CONTAINER_APP_NAME" --resource-group "$RESOURCE_GROUP_NAME" --query properties.configuration.ingress.fqdn -o tsv)
curl "https://$CONTAINER_APP_FQDN/"
# {"Hello":"World"}
```

External ingress makes this sample's anonymous API publicly reachable; use
internal ingress or appropriate access controls where required. Both
deployments use the routes in `template_azure_python/api.py` without copying
or changing application code.

#### Reusing the `azure_container_apps` Terraform scenario

If the [azure_container_apps scenario](https://github.com/ks6088ts/template-terraform/tree/main/infra/scenarios/azure_container_apps)
has already been applied, reuse its ACR and **replace its existing Container
App** rather than creating another app. The scenario manages that app with
Terraform, so deploy through Terraform instead of `az containerapp update`
(which a later apply could undo). Follow the scenario's README to provision it
first if necessary.

Run these commands from the root of this repository. Set `SCENARIO_DIR` to the
local scenario directory with access to the same Terraform state used for the
initial deployment. You need Terraform, a running Docker daemon, Azure CLI,
`jq`, and `curl`. Sign in with an identity granted `AcrPush` on the scenario's
registry; by default the scenario grants it to the Terraform identity. The
Container App already has a managed identity with `AcrPull`.

```shell
SCENARIO_DIR=/absolute/path/to/template-terraform/infra/scenarios/azure_container_apps
az login
ACR_ID=$(terraform -chdir="$SCENARIO_DIR" output -raw acr_id)
ACR_NAME=$(terraform -chdir="$SCENARIO_DIR" output -raw acr_name)
ACR_LOGIN_SERVER=$(terraform -chdir="$SCENARIO_DIR" output -raw acr_login_server)
SUBSCRIPTION_ID=$(printf '%s' "$ACR_ID" | cut -d/ -f3)
az account set --subscription "$SUBSCRIPTION_ID"
"$SCENARIO_DIR/scripts/validate_prerequisites.sh"

IMAGE_REPOSITORY=template-azure-python
IMAGE_TAG=$(git rev-parse --short HEAD)
IMAGE="$ACR_LOGIN_SERVER/$IMAGE_REPOSITORY:$IMAGE_TAG"
docker build --platform linux/amd64 --tag "$IMAGE" .
az acr login --name "$ACR_NAME" --subscription "$SUBSCRIPTION_ID"
docker push "$IMAGE"
```

Pin the pushed image by digest in the scenario's ignored
`deployment.auto.tfvars.json`. If the scenario previously deployed its bundled
MCP server, preserve any other settings already in that file while changing
the image, ingress/probe port to **8000**, probe path to `/`, and container
command to the Dockerfile default. Its `build_image.sh` and `deploy_image.sh`
target the bundled `src/` and configure port 8080 and `/health`, so do not use
them for this image.

```shell
(
  set -eu
  IMAGE_DIGEST=$(az acr repository show --name "$ACR_NAME" --subscription "$SUBSCRIPTION_ID" --image "$IMAGE_REPOSITORY:$IMAGE_TAG" --query digest -o tsv)
  if ! jq -n -e --arg digest "$IMAGE_DIGEST" '$digest | test("^sha256:[0-9a-fA-F]{64}$")' >/dev/null; then
    printf 'ACR did not return a SHA-256 digest\n' >&2
    exit 1
  fi
  IMAGE_BY_DIGEST="$ACR_LOGIN_SERVER/$IMAGE_REPOSITORY@$IMAGE_DIGEST"
  VARS_FILE="$SCENARIO_DIR/deployment.auto.tfvars.json"
  if [ ! -f "$VARS_FILE" ]; then
    printf '{}\n' > "$VARS_FILE"
  fi
  TEMP_FILE=$(mktemp "${VARS_FILE}.XXXXXX")
  trap 'rm -f "$TEMP_FILE"' EXIT
  jq -e --arg image "$IMAGE_BY_DIGEST" \
    '.container_image = $image | .container_port = 8000 | .health_probe_path = "/" | .container_command = []' \
    "$VARS_FILE" > "$TEMP_FILE"
  mv "$TEMP_FILE" "$VARS_FILE"
)
```

Keep the same Terraform variable files and command-line options used for the
initial deployment (in particular `enable_authentication=true` if set via
`-var` or `-var-file`). Check the plan before applying it: only the intended
image, port, probes, and command should change.

```shell
terraform -chdir="$SCENARIO_DIR" plan
terraform -chdir="$SCENARIO_DIR" apply
```

Verify the FastAPI routes rather than the scenario's MCP-specific
`verify_deployment.sh`, which expects `/health` and `/mcp`:

```shell
CONTAINER_APP_URL=$(terraform -chdir="$SCENARIO_DIR" output -raw container_app_url)
curl --fail --show-error "$CONTAINER_APP_URL/"
# {"Hello":"World"}
curl --fail --show-error --output /dev/null "$CONTAINER_APP_URL/docs"
```

If the scenario enabled Microsoft Entra authentication, both routes require
an access token. Instead of the unauthenticated `curl` commands above, use:

```shell
AUTH_RESOURCE=$(terraform -chdir="$SCENARIO_DIR" output -raw container_app_authentication_identifier_uri)
ACCESS_TOKEN=$(az account get-access-token --subscription "$SUBSCRIPTION_ID" --resource "$AUTH_RESOURCE" --query accessToken -o tsv)
curl --fail --show-error --header "Authorization: Bearer $ACCESS_TOKEN" "$CONTAINER_APP_URL/"
curl --fail --show-error --output /dev/null --header "Authorization: Bearer $ACCESS_TOKEN" "$CONTAINER_APP_URL/docs"
unset ACCESS_TOKEN
```

The scenario's external ingress exposes this app publicly unless authentication
or other access controls are enabled. Keep `deployment.auto.tfvars.json` for
subsequent Terraform applies; running the scenario's MCP deployment script
again would replace these image and port settings.

### Docker Hub

To publish the docker image to Docker Hub, you need to [create access token](https://app.docker.com/settings/personal-access-tokens/create) and set the following secrets in the repository settings.

```shell
gh secret set DOCKERHUB_USERNAME --body $DOCKERHUB_USERNAME
gh secret set DOCKERHUB_TOKEN --body $DOCKERHUB_TOKEN
```

### Azure Static Web Apps

```shell
RESOURCE_GROUP_NAME=your-resource-group-name
SWA_NAME=your-static-web-app-name

# Create a static app
az staticwebapp create --name $SWA_NAME --resource-group $RESOURCE_GROUP_NAME

# Retrieve the API key
AZURE_STATIC_WEB_APPS_API_TOKEN=$(az staticwebapp secrets list --name $SWA_NAME --query "properties.apiKey" -o tsv)

# Set the API key as a GitHub secret
gh secret set AZURE_STATIC_WEB_APPS_API_TOKEN --body $AZURE_STATIC_WEB_APPS_API_TOKEN
```

Refer to the following links for more information:

- [Deploying to Azure Static Web App](https://docs.github.com/en/actions/use-cases-and-examples/deploying/deploying-to-azure-static-web-app)
- [Create a static web app: `az staticwebapp create`](https://learn.microsoft.com/en-us/cli/azure/staticwebapp?view=azure-cli-latest#az-staticwebapp-create)
