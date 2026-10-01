# Deployment

## Azure Functions (existing Python Function App)

Use an existing Linux Function App configured for a supported Python version,
Functions runtime v4, and an Azure Storage account. Log in to Azure with
`az login`. Before **each** publish, generate the standard Python dependency
file from `uv.lock`. The file is intentionally ignored by Git but included in
Functions publishing.

```shell
uv export --locked --format requirements-txt --no-dev --no-hashes --no-emit-project --output-file requirements.txt
FUNCTION_APP_NAME=your-function-app-name
func azure functionapp publish "$FUNCTION_APP_NAME" --build remote
curl "https://$FUNCTION_APP_NAME.azurewebsites.net/"
# {"Hello":"World"}
```

Remote build installs `requirements.txt`; no second FastAPI implementation or
Functions-specific Docker image is required. Set application settings in Azure
rather than publishing `local.settings.json`.

### Reusing the `azure_functions_flex_consumption` Terraform scenario

If the
[azure_functions_flex_consumption scenario](https://github.com/ks6088ts/template-terraform/tree/main/infra/scenarios/azure_functions_flex_consumption)
has already been applied, publish this repository to its existing Function
App. Terraform provisions the infrastructure but does not publish application
code.

Run these commands from the root of this repository. Set `SCENARIO_DIR` to the
local scenario directory connected to the same Terraform state used for the
deployment. In addition to the prerequisites in the
[scripts and development guide](scripts.md), Terraform must be installed and
initialized for that state.

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
application. That script stages and publishes the scenario's bundled `src/`
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
curl --fail --show-error --header "Authorization: ******" "$FUNCTION_APP_URL/"
# {"Hello":"World"}
curl --fail --show-error --output /dev/null --header "Authorization: ******" "$FUNCTION_APP_URL/docs"
unset ACCESS_TOKEN
```

The published HTTP trigger is anonymous at the Functions host. With
`enable_authentication=true`, the scenario's App Service authentication layer
requires the bearer token before requests reach that trigger.

## Azure Container Apps (existing Container App)

Push the Docker image to a registry that the existing Container App can pull
from. Configure its HTTP ingress target port to **8000**, then update its image.
Replace the placeholders with your own resources.

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

External ingress makes this sample's anonymous API publicly reachable. Use
internal ingress or appropriate access controls where required. Both
deployments use the routes in `template_azure_python/api.py` without copying or
changing application code.

### Reusing the `azure_container_apps` Terraform scenario

If the
[azure_container_apps scenario](https://github.com/ks6088ts/template-terraform/tree/main/infra/scenarios/azure_container_apps)
has already been applied, reuse its ACR and **replace its existing Container
App** rather than creating another app. The scenario manages that app with
Terraform, so deploy through Terraform instead of `az containerapp update`,
which a later apply could undo. Follow the scenario's README to provision it
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
the image, ingress and probe port to **8000**, probe path to `/`, and container
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
initial deployment, in particular `enable_authentication=true` if set through
`-var` or `-var-file`. Check the plan before applying it: only the intended
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

If the scenario enabled Microsoft Entra authentication, both routes require an
access token. Instead of the unauthenticated `curl` commands above, use:

```shell
AUTH_RESOURCE=$(terraform -chdir="$SCENARIO_DIR" output -raw container_app_authentication_identifier_uri)
ACCESS_TOKEN=$(az account get-access-token --subscription "$SUBSCRIPTION_ID" --resource "$AUTH_RESOURCE" --query accessToken -o tsv)
curl --fail --show-error --header "Authorization: ******" "$CONTAINER_APP_URL/"
curl --fail --show-error --output /dev/null --header "Authorization: ******" "$CONTAINER_APP_URL/docs"
unset ACCESS_TOKEN
```

The scenario's external ingress exposes this app publicly unless authentication
or other access controls are enabled. Keep `deployment.auto.tfvars.json` for
subsequent Terraform applies. Running the scenario's MCP deployment script
again would replace these image and port settings.

## Docker Hub

To publish the Docker image to Docker Hub,
[create an access token](https://app.docker.com/settings/personal-access-tokens/create)
and set these secrets in the repository settings:

```shell
gh secret set DOCKERHUB_USERNAME --body "$DOCKERHUB_USERNAME"
gh secret set DOCKERHUB_TOKEN --body "$DOCKERHUB_TOKEN"
```

## Azure Static Web Apps

Create a Static Web App, retrieve its API key, and save that key as a GitHub
Actions secret:

```shell
RESOURCE_GROUP_NAME=your-resource-group-name
SWA_NAME=your-static-web-app-name

# Create a static app
az staticwebapp create --name "$SWA_NAME" --resource-group "$RESOURCE_GROUP_NAME"

# Retrieve the API key
AZURE_STATIC_WEB_APPS_API_TOKEN=$(az staticwebapp secrets list --name "$SWA_NAME" --query "properties.apiKey" -o tsv)

# Set the API key as a GitHub secret
gh secret set AZURE_STATIC_WEB_APPS_API_TOKEN --body "$AZURE_STATIC_WEB_APPS_API_TOKEN"
```

For more information:

- [Deploying to Azure Static Web App](https://docs.github.com/en/actions/use-cases-and-examples/deploying/deploying-to-azure-static-web-app)
- [Create a static web app: `az staticwebapp create`](https://learn.microsoft.com/en-us/cli/azure/staticwebapp?view=azure-cli-latest#az-staticwebapp-create)
