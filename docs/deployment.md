# Deployment

Publish the app or documentation after checking it locally.
**Choose one procedure that matches what you want to publish.**

| What to publish | Target | Prepare first |
| --- | --- | --- |
| Python API | [Azure Functions](#azure-functions) | Existing Linux Function App |
| Containerized API | [Azure Container Apps](#azure-container-apps) | Existing Container App and registry |
| Tested Docker image | [GHCR](#ghcr-and-github-pages) | GitHub Actions permissions |
| MkDocs documentation site | [GitHub Pages](#ghcr-and-github-pages) | Pages source set to GitHub Actions |

## Before publishing

- Check the app using the [local development guide](scripts.md).
- Run commands from the root of this Python repository.
  Replace `your-...` and `<...>` with actual values.
- For Azure, sign in with `az login` and check the target with `az account show`.
  Switch with `az account set --subscription "<subscription-id>"` if needed.
- GitHub secrets and Actions commands need `gh`, authenticated with `gh auth login`.
- Local development is anonymous. Azure deployments must use protected ingress
  and Easy Auth before exposing the Task API publicly.
  Azure resources and image storage may incur charges.

Probes use `/healthz` and `/readyz`, not `/docs` or the Task collection.
Production disables OpenAPI documentation by default.

InMemory is the default and does not share data between replicas.
For Cosmos, [prepare the Task container](cosmosdb.md#task-api-persistence-and-container-management),
then set `TASK_REPOSITORY=cosmosdb`, `AZURE_COSMOS_DB_ENDPOINT`, `AZURE_COSMOS_DB_DATABASE`,
and `AZURE_COSMOS_DB_TASK_CONTAINER` in Functions app settings / Container Apps environment variables.
Grant the API managed identity the appropriate data-plane RBAC, not management CLI permissions.
Management account-name/subscription/resource-group settings are unnecessary for API startup.

## Protected deployment setup

The repository includes `infra/main.bicep` and `infra/app.bicep`; no external
Terraform repository is required. Provision separate staging and production
resource groups. The templates create Log Analytics, Application Insights with
local authentication disabled, an admin-disabled ACR, Container Apps, and separate
runtime/deployment managed identities. GHCR is the default release registry;
the ACR is available for a future private-registry integration, not automatically
populated by the release workflow.

1. Create an Entra application registration for the API. Expose an application
   role named `Task.ReadWrite`, assign it to authorized callers, and use the
   application client ID below. Easy Auth verifies tokens at ingress; the API
   authorizes its trusted principal header. **Never enable header-based
   authentication on an origin that callers can reach without Easy Auth.**
2. Make the GHCR package public so Container Apps can pull it without stored
   credentials. Choose a verified image digest, never a mutable tag.
3. Sign in with `az login` and `gh auth login`. The provisioning identity needs
   resource creation and role-assignment permissions; the generated deployment
   identity is scoped only to its Container App.
4. Run bootstrap for each environment (the final argument is a numeric GitHub
   user ID, obtained with `gh api users/REVIEWER --jq .id`):

   ```shell
   bash scripts/bootstrap-azure.sh OWNER/REPO staging rg-api-staging eastus api \
     ghcr.io/owner/repo@sha256:REPLACE_WITH_64_HEX_DIGITS \
     YOUR_ENTRA_APPLICATION_CLIENT_ID YOUR_REVIEWER_USER_ID
   bash scripts/bootstrap-azure.sh OWNER/REPO production rg-api-production eastus api \
     ghcr.io/owner/repo@sha256:REPLACE_WITH_64_HEX_DIGITS \
     YOUR_ENTRA_APPLICATION_CLIENT_ID YOUR_REVIEWER_USER_ID
   ```

   Bootstrap creates environment protections **before** Azure federation:
   main-only deployment branches, no administrator bypass, and a mandatory
   production reviewer who cannot approve their own deployment. It writes
   environment variables `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`,
   `AZURE_SUBSCRIPTION_ID`, `RESOURCE_GROUP`, and `CONTAINER_APP_NAME`.
   Each Azure OIDC subject is
   `repo:OWNER/REPO:environment:staging` or `...:production`.
   Environment protection availability depends on repository visibility and plan.
   If GitHub rejects protection setup, do not bypass it to enable production CD.
   Reruns preserve existing reviewers and wait timers and reject non-main
   policies before modifying protections. Change reviewer membership manually
   in GitHub settings when needed.
5. Review the provisioned identity, ingress, application roles, environment
   reviewers, and policies before enabling automatic deployment. Keep
   `maxReplicas: 1` for process-local demo storage. Use a shared durable adapter
   and its data-plane RBAC before enabling multiple replicas.

Validate changes without deploying:

```shell
az bicep build --file infra/main.bicep --outfile /tmp/main.json
az bicep lint --file infra/main.bicep
az deployment group what-if --resource-group rg-api-staging \
  --template-file infra/main.bicep --parameters \
  namePrefix=api environment=staging githubRepository=OWNER/REPO \
  image=ghcr.io/owner/repo@sha256:REPLACE_WITH_64_HEX_DIGITS \
  authClientId=YOUR_ENTRA_APPLICATION_CLIENT_ID
```

Infrastructure applies manage configuration as well as the image: pass the
currently promoted digest on subsequent applies to avoid reverting a release.
Initial ingress is internal; bootstrap opens it only after Easy Auth deployment
succeeds. For subsequent applies to an already protected app, pass
`externalIngress=true`; the default safely closes external ingress.
An initial bootstrap image must already exist; provision from a reviewed,
attested release rather than a third-party demo image.

### Repository protections

Enable private vulnerability reporting, secret scanning, push protection,
Dependabot alerts, and CodeQL in repository settings. Review `SECURITY.md`.
Replace `OWNER` in `.github/CODEOWNERS`, documentation metadata, and issue links
using `scripts/init_template.py` before enabling CODEOWNERS enforcement.

The rulesets in `.github/rulesets/` are **samples to review**, not automatically
applied settings. Before importing release-tag protection, add your trusted
release GitHub App's integration ID to `bypass_actors` with
`actor_type: "Integration"` and `bypass_mode: "always"`. Without that explicit
publisher, creation of all `v*` tags is intentionally denied. Do not grant a
bypass to all writers.

```shell
gh api --method POST repos/OWNER/REPO/rulesets --input .github/rulesets/main.json
gh api --method POST repos/OWNER/REPO/rulesets --input .github/rulesets/release-tags.json
```

The main sample requires CODEOWNERS approval, `ci-ok`, `pr-title`, squash
merges, and a merge queue. Confirm merge queues are supported by your plan.
The sample also gates CodeQL security findings at medium or above.
Verify Code Security/ruleset entitlement before importing it into a private
repository. Enable immutable releases in GitHub settings.

### Release, verification, and rollback

Release automation uses Conventional Commit squash titles and release-please.
Release jobs build once, smoke-test the resulting image, and publish provenance
and an SBOM. Staging and production use the same immutable digest; production
requires environment approval. A prerelease must not update `latest`.
Deployment verifies GitHub provenance before changing Azure.

For rollback, run the manual deployment workflow with a previously verified
digest from this repository's trusted main-branch release workflow. It uses
the same staging/production approval, verification, and probe checks as a
normal deployment; it does not rebuild an old revision. Keep the last known
good digest in release records and verify it before approving production.

GitHub artifact attestations require a supported GitHub plan for private
repositories. Do not disable verification to work around missing entitlements;
configure the required plan or a separately reviewed signing solution first.

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
uv export --locked --extra functions --format requirements-txt --no-dev --no-emit-project --output-file requirements.txt
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
curl --fail --show-error "https://$FUNCTION_APP_NAME.azurewebsites.net/readyz"
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
uv export --locked --extra functions --format requirements-txt --no-dev --no-emit-project --output-file requirements.txt
func azure functionapp publish "$FUNCTION_APP_NAME" --subscription "$SUBSCRIPTION_ID" --build remote --python
```

Run both commands again after changing code or dependencies.

#### 3. Verify with the configured authentication

Microsoft Entra authentication is off by default:

```shell
curl --fail --show-error "$FUNCTION_APP_URL/tasks"
curl --fail --show-error "$FUNCTION_APP_URL/readyz"
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

App Service authentication must protect the trigger before traffic reaches it.
Use the same production settings and app-role policy as Container Apps.

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
IMAGE_DIGEST=$(docker buildx imagetools inspect "$IMAGE" --format '{{.Manifest.Digest}}')
IMAGE="${IMAGE%:*}@$IMAGE_DIGEST"
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
curl --fail --show-error "https://$CONTAINER_APP_FQDN/readyz"
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
| Health probe paths | `/healthz` and `/readyz` |
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
    '.container_image = $image | .container_port = 8000 | .health_probe_path = "/healthz" | .container_command = []' \
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
curl --fail --show-error "$CONTAINER_APP_URL/readyz"
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

## GHCR and GitHub Pages

GHCR publication uses `GITHUB_TOKEN`, not a Docker Hub token. Grant Actions
package publication permission and make the resulting package public for the
default Container Apps path.

In **Settings → Pages**, select **GitHub Actions** as the source. The Pages
workflow builds with read-only permissions and credential-free checkout,
uploads a Pages artifact, and deploys from a separate `github-pages`
environment. No `gh-pages` branch or Static Web Apps deployment token is needed.

Documentation has no analytics or author social links by default. If analytics
are needed, configure your own property with an appropriate privacy notice.
MkDocs/Material dependencies are bounded; review upstream support status before
upgrading. Evaluate a successor in a separate branch and migrate only after
both languages, Mermaid diagrams, deep links, and strict builds work. Do not
replace the existing Japanese/English content with an unverified alpha migration.

Copilot cloud agent setup is in `.github/workflows/copilot-setup-steps.yml`;
it takes effect after merging into the default branch. AGENTS.md documents
commands and safety boundaries. The Microsoft Learn MCP entry in `.mcp.json`
is opt-in for compatible clients; configure cloud-agent MCP servers separately
in repository settings, without credentials in checked-in configuration.

The pre-tool hooks in `.github/hooks/guardrails.json` reject common destructive
shell mistakes such as force pushes and Azure deletion. They are not a sandbox:
shell indirection and arbitrary programs cannot be reliably secured by command
matching. Keep human approval, least-privilege identities, and environment
protections as the enforcement boundaries.
