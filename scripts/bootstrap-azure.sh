#!/usr/bin/env bash
set -euo pipefail

if [[ $# != 8 ]]; then
  echo "Usage: $0 OWNER/REPO staging|production RESOURCE_GROUP LOCATION PREFIX IMAGE@sha256:DIGEST AUTH_CLIENT_ID REVIEWER_USER_ID" >&2
  exit 2
fi
repository=$1
environment=$2
resource_group=$3
location=$4
prefix=$5
image=$6
auth_client_id=$7
reviewer=$8
[[ "$repository" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]
[[ "$environment" == staging || "$environment" == production ]]
[[ "$resource_group" =~ ^[A-Za-z0-9][A-Za-z0-9_.()-]{0,89}$ ]]
[[ "$location" =~ ^[a-z0-9]+$ ]]
[[ "$prefix" =~ ^[a-z0-9]{3,16}$ ]]
[[ "$image" =~ ^ghcr.io/[a-z0-9_.-]+/[a-z0-9_.-]+@sha256:[0-9a-f]{64}$ ]]
[[ "$auth_client_id" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]]
[[ "$reviewer" =~ ^[0-9]+$ ]]
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
temporary=$(mktemp -d)
trap 'rm -rf -- "$temporary"' EXIT

# Reject unsafe existing policies before changing any environment protection.
if gh api "repos/$repository/environments/$environment" \
  > "$temporary/current-environment.json" 2> "$temporary/environment-error"; then
  policies=$(gh api "repos/$repository/environments/$environment/deployment-branch-policies")
  jq -e '.branch_policies | type == "array"' <<< "$policies" > /dev/null
  if jq -e '.branch_policies[] | select(.name != "main" or .type != "branch")' <<< "$policies" > /dev/null; then
    echo "Remove non-main deployment policies from the environment before continuing." >&2
    exit 1
  fi
elif grep -Fq '(HTTP 404)' "$temporary/environment-error"; then
  printf '{}\n' > "$temporary/current-environment.json"
  policies='{"branch_policies":[]}'
else
  echo "Unable to inspect the existing environment; no protections were changed." >&2
  exit 1
fi

# Preserve existing reviewers; production gets its first reviewer if necessary.
jq -n --arg environment "$environment" --argjson reviewer "$reviewer" \
  --slurpfile current "$temporary/current-environment.json" \
  '([$current[0].protection_rules[]? | select(.type == "required_reviewers")
     | .reviewers[] | {type: .type, id: .reviewer.id}]) as $reviewers |
   ([$current[0].protection_rules[]? | select(.type == "wait_timer") | .wait_timer][0] // 0) as $wait |
  {deployment_branch_policy: {protected_branches: false, custom_branch_policies: true},
    prevent_self_review: true, can_admins_bypass: false, wait_timer: $wait}
   + if ($reviewers | length) > 0 then {reviewers: $reviewers}
     elif $environment == "production" then
       {reviewers: [{type: "User", id: $reviewer}]}
     else {reviewers: []} end' > "$temporary/environment.json"
gh api --method PUT "repos/$repository/environments/$environment" --input "$temporary/environment.json" > /dev/null
if ! jq -e '.branch_policies[] | select(.name == "main" and .type == "branch")' <<< "$policies" > /dev/null; then
  gh api --method POST "repos/$repository/environments/$environment/deployment-branch-policies" \
    -f name=main -f type=branch > /dev/null
fi
policies=$(gh api "repos/$repository/environments/$environment/deployment-branch-policies")
jq -e '.branch_policies | type == "array"' <<< "$policies" > /dev/null
if jq -e '.branch_policies[] | select(.name != "main" or .type != "branch")' <<< "$policies" > /dev/null; then
  echo "Remove non-main deployment policies from the environment before continuing." >&2
  exit 1
fi

az group create --name "$resource_group" --location "$location" --output none
az deployment group create --resource-group "$resource_group" \
  --template-file "$root/infra/main.bicep" \
  --parameters namePrefix="$prefix" environment="$environment" \
    githubRepository="$repository" image="$image" authClientId="$auth_client_id" \
  --query properties.outputs --output json > "$temporary/outputs.json"
container_app=$(jq -er '.containerAppName.value' "$temporary/outputs.json")
# Open ingress only after the full deployment, including Easy Auth, succeeds.
az containerapp ingress enable --resource-group "$resource_group" \
  --name "$container_app" --type external --target-port 8000 --transport http --output none
for mapping in \
  AZURE_CLIENT_ID:deployClientId \
  AZURE_TENANT_ID:tenantId \
  AZURE_SUBSCRIPTION_ID:subscriptionId \
  RESOURCE_GROUP:resourceGroupName \
  CONTAINER_APP_NAME:containerAppName; do
  variable=${mapping%%:*}
  output=${mapping#*:}
  value=$(jq -er --arg output "$output" '.[$output].value' "$temporary/outputs.json")
  gh variable set "$variable" --repo "$repository" --env "$environment" --body "$value"
done
echo "Configured $environment. Verify its reviewers, main-only policy, Easy Auth, and app-role assignments before enabling CD."
