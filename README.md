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
