# Deployment

Publish the app or documentation after checking it locally.
**Choose one procedure that matches what you want to publish.**

| What to publish | Target | Prepare first |
| --- | --- | --- |
| Python API | [Azure Functions](#azure-functions) | Existing Linux Function App |
| Containerized API | [Azure Container Apps](#azure-container-apps) | Existing Container App and registry |
| Docker image | [Docker Hub](#docker-hub) | Docker Hub account and access token |
| MkDocs documentation site | [Azure Static Web Apps](#azure-static-web-apps) | Azure resource group and GitHub repository |

## Before publishing

- Check the app using the [local development guide](scripts.md).
- Run commands from the root of this Python repository.
  Replace `your-...` and `<...>` with actual values.
- For Azure, sign in with `az login` and check the target with `az account show`.
  Switch with `az account set --subscription "<subscription-id>"` if needed.
- GitHub secrets and Actions commands need `gh`, authenticated with `gh auth login`.
- The sample API is anonymous. Set up access controls before exposing it publicly.
  Azure resources and image storage may incur charges.

For API checks, expect a Task array (initially `[]`) from `/tasks` and HTTP 200 from `/docs`.
The mock `/` has been removed. Probes use `/docs` to avoid repeatedly fetching all Tasks.

InMemory is the default and does not share data between replicas.
For Cosmos, [prepare the Task container](cosmosdb.md#task-api-persistence-and-container-management),
then set `TASK_REPOSITORY=cosmosdb`, `AZURE_COSMOS_DB_ENDPOINT`, `AZURE_COSMOS_DB_DATABASE`,
and `AZURE_COSMOS_DB_TASK_CONTAINER` in Functions app settings / Container Apps environment variables.
Grant the API managed identity the appropriate data-plane RBAC, not management CLI permissions.
Management account-name/subscription/resource-group settings are unnecessary for API startup.

## Azure Functions

**Tools**: uv, Azure CLI, Functions Core Tools v4, and curl.
Use an existing Linux Function App with an Azure-supported Python version,
Functions runtime v4, and Azure Storage configured. This procedure does not create an app.

### Publish to an existing Function App

#### 1. Export dependencies

Before **each** publish, generate `requirements.txt` from `uv.lock`.
The file is Git-ignored but included in Functions publishing.

```shell
FUNCTION_APP_NAME=your-function-app-name
uv export --locked --format requirements-txt --no-dev --no-hashes --no-emit-project --output-file requirements.txt
```

#### 2. Publish

```shell
func azure functionapp publish "$FUNCTION_APP_NAME" --build remote
```

Remote build installs the dependencies. No second FastAPI implementation or
dedicated Docker image is needed. Configure app settings in Azure; do not publish `local.settings.json`.

#### 3. Check the response

```shell
curl --fail --show-error "https://$FUNCTION_APP_NAME.azurewebsites.net/tasks"
curl --fail --show-error --output /dev/null "https://$FUNCTION_APP_NAME.azurewebsites.net/docs"
```

If the app has authentication enabled, also supply the credentials it requires.

### Use the Terraform Flex Consumption scenario

If you already applied
[`azure_functions_flex_consumption`](https://github.com/ks6088ts/template-terraform/tree/main/infra/scenarios/azure_functions_flex_consumption),
use this procedure. Terraform creates the infrastructure; publish the app code
from this repository. Install Terraform and initialize it for **the same state
used for the original deployment**.

**Do not use the scenario's `scripts/publish_code.sh`.**
It publishes the bundled `src/` sample, not this app's `function_app.py` and
`template_azure_python/` package.

#### 1. Check the target app

```shell
SCENARIO_DIR=/absolute/path/to/template-terraform/infra/scenarios/azure_functions_flex_consumption
az login
SUBSCRIPTION_ID=$(terraform -chdir="$SCENARIO_DIR" output -raw subscription_id)
FUNCTION_APP_ID=$(terraform -chdir="$SCENARIO_DIR" output -raw function_app_id)
FUNCTION_APP_NAME=$(terraform -chdir="$SCENARIO_DIR" output -raw function_app_name)
FUNCTION_APP_URL=$(terraform -chdir="$SCENARIO_DIR" output -raw function_app_url)
az account set --subscription "$SUBSCRIPTION_ID"
az functionapp show --ids "$FUNCTION_APP_ID" \
  --query "{name:name,state:state,defaultHostName:defaultHostName}" --output table
```

Confirm the displayed app is the intended target before continuing.

#### 2. Export and publish

```shell
uv export --locked --format requirements-txt --no-dev --no-hashes --no-emit-project --output-file requirements.txt
func azure functionapp publish "$FUNCTION_APP_NAME" --subscription "$SUBSCRIPTION_ID" --build remote --python
```

Run both commands again after changing code or dependencies.

#### 3. Verify with the configured authentication

Microsoft Entra authentication is off by default:

```shell
curl --fail --show-error "$FUNCTION_APP_URL/tasks"
curl --fail --show-error --output /dev/null "$FUNCTION_APP_URL/docs"
```

If you applied `enable_authentication=true`, use this instead.
Acquire a token for the application ID URI from the same state:

```shell
AUTH_RESOURCE=$(terraform -chdir="$SCENARIO_DIR" output -raw function_app_authentication_identifier_uri)
ACCESS_TOKEN=$(az account get-access-token --subscription "$SUBSCRIPTION_ID" --resource "$AUTH_RESOURCE" --query accessToken --output tsv)
curl --fail --show-error --header "Authorization: Bearer $ACCESS_TOKEN" "$FUNCTION_APP_URL/tasks"
curl --fail --show-error --output /dev/null --header "Authorization: Bearer $ACCESS_TOKEN" "$FUNCTION_APP_URL/docs"
unset ACCESS_TOKEN
```

The Functions HTTP trigger itself is anonymous. When enabled, App Service
authentication checks the token before the request reaches the trigger.

## Azure Container Apps

**Tools**: Docker, Azure CLI, and curl.
Use an existing Container App and a registry it can pull from.
You also need registry push permissions and an authenticated registry session.
For a Terraform-managed app, use the Terraform procedure below instead.

### Update an existing Container App

#### 1. Build and push

```shell
IMAGE=your-registry.example.com/template-azure-python:your-tag
RESOURCE_GROUP_NAME=your-resource-group-name
CONTAINER_APP_NAME=your-container-app-name

docker build --platform linux/amd64 -t "$IMAGE" .
docker push "$IMAGE"
```

#### 2. Update the port and image

The HTTP ingress target port is **8000**.
**The `external` setting below makes this anonymous API public.**
Use `internal` ingress or suitable access controls for restricted access.

```shell
az containerapp ingress enable --name "$CONTAINER_APP_NAME" \
  --resource-group "$RESOURCE_GROUP_NAME" --type external --target-port 8000
az containerapp update --name "$CONTAINER_APP_NAME" \
  --resource-group "$RESOURCE_GROUP_NAME" --image "$IMAGE"
```

#### 3. Check the response

```shell
CONTAINER_APP_FQDN=$(az containerapp show --name "$CONTAINER_APP_NAME" --resource-group "$RESOURCE_GROUP_NAME" --query properties.configuration.ingress.fqdn -o tsv)
curl --fail --show-error "https://$CONTAINER_APP_FQDN/tasks"
curl --fail --show-error --output /dev/null "https://$CONTAINER_APP_FQDN/docs"
```

### Use the Terraform Container Apps scenario

If you already applied
[`azure_container_apps`](https://github.com/ks6088ts/template-terraform/tree/main/infra/scenarios/azure_container_apps),
reuse its ACR and **replace its existing Container App with this API**.
No new app is created. If necessary, provision the scenario first using its README.

Updating a Terraform-managed app with `az containerapp update` may be undone by
a later apply. Update through Terraform here instead.

**Extra tools**: Terraform, jq, and a running Docker daemon.
`SCENARIO_DIR` must connect to the original state.
The calling identity needs `AcrPush` on ACR; the scenario grants it to the
Terraform operator by default. The Container App's managed identity already has `AcrPull`.

#### 1. Check the target and prerequisites

```shell
SCENARIO_DIR=/absolute/path/to/template-terraform/infra/scenarios/azure_container_apps
az login
ACR_ID=$(terraform -chdir="$SCENARIO_DIR" output -raw acr_id)
ACR_NAME=$(terraform -chdir="$SCENARIO_DIR" output -raw acr_name)
ACR_LOGIN_SERVER=$(terraform -chdir="$SCENARIO_DIR" output -raw acr_login_server)
SUBSCRIPTION_ID=$(printf '%s' "$ACR_ID" | cut -d/ -f3)
az account set --subscription "$SUBSCRIPTION_ID"
"$SCENARIO_DIR/scripts/validate_prerequisites.sh"
```

#### 2. Build and push

```shell
IMAGE_REPOSITORY=template-azure-python
IMAGE_TAG=$(git rev-parse --short HEAD)
IMAGE="$ACR_LOGIN_SERVER/$IMAGE_REPOSITORY:$IMAGE_TAG"
docker build --platform linux/amd64 --tag "$IMAGE" .
az acr login --name "$ACR_NAME" --subscription "$SUBSCRIPTION_ID"
docker push "$IMAGE"
```

#### 3. Set the image and ports in Terraform

Pin the pushed image by digest. The command below updates
`deployment.auto.tfvars.json` while preserving its other settings.

| Setting | Value |
| --- | --- |
| Image | Pushed image digest |
| Ingress and health probe port | `8000` |
| Health probe path | `/docs` |
| Container command | Dockerfile default |

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
    '.container_image = $image | .container_port = 8000 | .health_probe_path = "/docs" | .container_command = []' \
    "$VARS_FILE" > "$TEMP_FILE"
  mv "$TEMP_FILE" "$VARS_FILE"
)
```

Do not use the scenario's `build_image.sh` / `deploy_image.sh`.
They target its bundled MCP server in `src/`, port 8080, and `/health`.

#### 4. Review and apply

Add the **same `-var` / `-var-file` arguments to both commands** that you used
for the initial deployment. In particular, preserve `enable_authentication=true`.

```shell
terraform -chdir="$SCENARIO_DIR" plan
terraform -chdir="$SCENARIO_DIR" apply
```

Before applying, check that only the intended image, ports, health probes, and
container command change.

#### 5. Check the API

Do not use MCP-specific `verify_deployment.sh`, which checks `/health` and `/mcp`.
Check this API's routes:

```shell
CONTAINER_APP_URL=$(terraform -chdir="$SCENARIO_DIR" output -raw container_app_url)
curl --fail --show-error "$CONTAINER_APP_URL/tasks"
curl --fail --show-error --output /dev/null "$CONTAINER_APP_URL/docs"
```

If Microsoft Entra authentication is enabled, use this instead:

```shell
AUTH_RESOURCE=$(terraform -chdir="$SCENARIO_DIR" output -raw container_app_authentication_identifier_uri)
ACCESS_TOKEN=$(az account get-access-token --subscription "$SUBSCRIPTION_ID" --resource "$AUTH_RESOURCE" --query accessToken -o tsv)
curl --fail --show-error --header "Authorization: Bearer $ACCESS_TOKEN" "$CONTAINER_APP_URL/tasks"
curl --fail --show-error --output /dev/null --header "Authorization: Bearer $ACCESS_TOKEN" "$CONTAINER_APP_URL/docs"
unset ACCESS_TOKEN
```

External ingress makes the API public unless authentication or access controls
are enabled. Keep `deployment.auto.tfvars.json` for later applies.
Rerunning the scenario's MCP deployment script replaces these image and port settings.

## Docker Hub

This publishes an **image**; it does not start an API server.

1. Create a Docker Hub [access token](https://app.docker.com/settings/personal-access-tokens/create).
2. Register repository secrets. Enter the values when prompted:

   ```shell
   gh secret set DOCKERHUB_USERNAME
   gh secret set DOCKERHUB_TOKEN
   ```

3. Push a tag starting with `v` to trigger the `docker-release` workflow.
4. Check that GitHub Actions succeeds and tags appear in `<username>/template-azure-python` on Docker Hub.

   ```shell
   gh run list --workflow docker-release.yaml --limit 1
   ```

## Azure Static Web Apps

This repository's workflow publishes the **MkDocs site**, not FastAPI.
The default documentation deployment is GitHub Pages on pushes to `main`.
Configure the following only if you want to use Static Web Apps.

### 1. Create a Static Web App

Use an existing resource group:

```shell
RESOURCE_GROUP_NAME=your-resource-group-name
SWA_NAME=your-static-web-app-name
az staticwebapp create --name "$SWA_NAME" --resource-group "$RESOURCE_GROUP_NAME"
```

### 2. Register the deployment secret

Retrieve the API key and register it in GitHub. Do not print it or save it in source.

```shell
AZURE_STATIC_WEB_APPS_API_TOKEN=$(az staticwebapp secrets list --name "$SWA_NAME" --resource-group "$RESOURCE_GROUP_NAME" --query "properties.apiKey" -o tsv)
gh secret set AZURE_STATIC_WEB_APPS_API_TOKEN --body "$AZURE_STATIC_WEB_APPS_API_TOKEN"
unset AZURE_STATIC_WEB_APPS_API_TOKEN
```

### 3. Run the workflow

The default trigger is manual. The workflow builds documentation and uploads the generated site.

```shell
gh workflow run azure-static-web-app.yaml
gh run list --workflow azure-static-web-app.yaml --limit 1
```

To deploy automatically, follow the workflow comments to enable the push trigger for `main`.

### 4. Check the published site

Wait for Actions to succeed, then open this hostname in a browser.
Check that both English and Japanese pages are available:

```shell
az staticwebapp show --name "$SWA_NAME" --resource-group "$RESOURCE_GROUP_NAME" --query defaultHostname -o tsv
```

See [deployment from GitHub Actions](https://docs.github.com/en/actions/use-cases-and-examples/deploying/deploying-to-azure-static-web-app)
and [`az staticwebapp create`](https://learn.microsoft.com/en-us/cli/azure/staticwebapp?view=azure-cli-latest#az-staticwebapp-create).
