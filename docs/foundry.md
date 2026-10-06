# Microsoft Foundry

Ask an AI model a question, or create and chat with an agent.
The CLI module is `scripts.cli_foundry`.

For opt-in Agent quality checks with DeepEval, see [LLM evaluation](evaluation.md).

## 1. Set the endpoint

Complete the [development and common Azure setup](scripts.md), then prepare:

- a Microsoft Foundry account and project;
- a model that supports the Responses API; the default model name is `gpt-5-mini`;
- access for the calling identity and the project's managed identity.

Set this value in `.env` to your actual project URL:

```dotenv
FOUNDRY_PROJECT_ENDPOINT=https://<account>.services.ai.azure.com/api/projects/<project>
```

**Use an HTTPS URL containing `/api/projects/`.**
Malformed URLs report an input error with exit code 2 before authentication.
Run the remaining commands from the root of this Python repository.

## 2. Check access

Assign the [Foundry User role](https://learn.microsoft.com/azure/foundry/concepts/rbac-foundry)
on the Foundry account to both identities:

| Identity | Purpose |
| --- | --- |
| The user or service principal running the CLI | Calling the API |
| The project's managed identity | Access from the project |

`Foundry User` was previously called `Azure AI User`; you may still see the old name.
`Owner` or `Contributor` alone does not provide these data permissions.
Projects created in the Foundry portal may receive the assignments automatically,
depending on the creator's permissions.

### Assign missing roles

An administrator with role-assignment permissions runs these commands.
This example assumes **Azure CLI is signed in as a user**.
Replace the placeholders:

```shell
SUBSCRIPTION_ID="$(az account show --query id --output tsv)"
RESOURCE_GROUP="<foundry-resource-group>"
FOUNDRY_ACCOUNT="<foundry-account-name>"
FOUNDRY_PROJECT="<foundry-project-name>"
FOUNDRY_SCOPE="/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.CognitiveServices/accounts/${FOUNDRY_ACCOUNT}"
PROJECT_SCOPE="${FOUNDRY_SCOPE}/projects/${FOUNDRY_PROJECT}"

USER_OBJECT_ID="$(az ad signed-in-user show --query id --output tsv)"
PROJECT_PRINCIPAL_ID="$(az resource show --ids "$PROJECT_SCOPE" --query identity.principalId --output tsv)"
printf '%s\n' "$PROJECT_PRINCIPAL_ID"
```

If `PROJECT_PRINCIPAL_ID` is empty, configure the project's managed identity first.
After obtaining the ID, assign both roles:

```shell
az role assignment create \
  --assignee-object-id "$USER_OBJECT_ID" --assignee-principal-type User \
  --role "Foundry User" --scope "$FOUNDRY_SCOPE"
az role assignment create \
  --assignee-object-id "$PROJECT_PRINCIPAL_ID" --assignee-principal-type ServicePrincipal \
  --role "Foundry User" --scope "$FOUNDRY_SCOPE"
```

If a service principal runs the CLI, use its object ID and
`--assignee-principal-type ServicePrincipal` for the first assignment instead.

### Verify the assignments

```shell
az role assignment list \
  --scope "$FOUNDRY_SCOPE" --include-inherited \
  --query "[?principalId=='${USER_OBJECT_ID}' || principalId=='${PROJECT_PRINCIPAL_ID}'].{principalType:principalType,role:roleDefinitionName,scope:scope}" \
  --output table
```

Confirm that both identities have `Foundry User` or its previous name.
Allow several minutes for new assignments to take effect.

## 3. Run the command you need

You can try these three operations independently.

### Ask a model

```shell
uv run --locked python -m scripts.cli_foundry chat-model
```

The model's answer appears as text. To choose the model and question:

```shell
uv run --locked python -m scripts.cli_foundry chat-model \
  --model gpt-5-mini --prompt "What is the size of France in square miles?"
```

### Create an agent

```shell
uv run --locked python -m scripts.cli_foundry create-agent \
  --agent-name MyAgent --model gpt-5-mini \
  --instructions "You are a helpful assistant."
```

The command prints the agent ID, name, and version.
Running it again with the same name creates a new version.

### Chat with an agent

```shell
uv run --locked python -m scripts.cli_foundry chat-agent \
  --agent-name MyAgent \
  --prompt "What is the size of France in square miles?" \
  --follow-up-prompt "And what is the capital city?"
```

This creates or updates the agent and asks two questions in the same conversation.
**You do not need to run `create-agent` first.**

## Find options

Use `--endpoint` to override the endpoint in `.env`.
Use `--help` to see all options and defaults:

```shell
uv run --locked python -m scripts.cli_foundry --help
uv run --locked python -m scripts.cli_foundry chat-model --help
uv run --locked python -m scripts.cli_foundry create-agent --help
uv run --locked python -m scripts.cli_foundry chat-agent --help
```

## If you get a 403 error

For `PermissionDeniedError: Error code: 403`, check these items before changing code:

1. Run `az account show` to check the subscription, tenant, and calling identity.
2. Check that `FOUNDRY_PROJECT_ENDPOINT` is the project URL.
3. Check model readiness and Responses API support, using the resource names set above.

   ```shell
   az cognitiveservices account deployment show \
     --resource-group "$RESOURCE_GROUP" --name "$FOUNDRY_ACCOUNT" \
     --deployment-name "gpt-5-mini" \
     --query "{state:properties.provisioningState,responses:properties.capabilities.responses,model:properties.model.name,version:properties.model.version}" \
     --output table
   ```

   Change `--deployment-name` if you use a different deployment.
4. Check that both the calling identity and project managed identity have the roles above.
5. Wait for role propagation, then retry `chat-model`.

If the error persists, check the account's firewall, virtual network, and private
endpoints. See the [HTTP error guide](https://learn.microsoft.com/azure/foundry/openai/how-to/troubleshoot-errors).

Do not replace the endpoint for `create-agent` or `chat-agent` with a resource-level
OpenAI URL. That does not fix project permissions and bypasses the required project features.
