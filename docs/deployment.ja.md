# デプロイ

## Azure Functions（既存の Python Function App）

サポート対象の Python バージョン、Functions ランタイム v4、Azure Storage
アカウントが設定された既存の Linux Function App を使用します。`az login` で
Azure にサインインしてください。**発行するたびに** `uv.lock` から標準の Python
依存関係ファイルを生成します。このファイルは意図的に Git の無視対象になっていますが、
Functions の発行には含まれます。

```shell
uv export --locked --format requirements-txt --no-dev --no-hashes --no-emit-project --output-file requirements.txt
FUNCTION_APP_NAME=your-function-app-name
func azure functionapp publish "$FUNCTION_APP_NAME" --build remote
curl "https://$FUNCTION_APP_NAME.azurewebsites.net/"
# {"Hello":"World"}
```

リモートビルドが `requirements.txt` をインストールするため、別の FastAPI
実装や Functions 専用 Docker イメージは不要です。`local.settings.json` を
発行するのではなく、アプリケーション設定は Azure 側で設定してください。

### `azure_functions_flex_consumption` Terraform シナリオの再利用

[azure_functions_flex_consumption シナリオ](https://github.com/ks6088ts/template-terraform/tree/main/infra/scenarios/azure_functions_flex_consumption)
が適用済みの場合、このリポジトリを既存の Function App へ発行します。Terraform
はインフラストラクチャをプロビジョニングしますが、アプリケーションコードは発行しません。

このリポジトリのルートから次のコマンドを実行します。`SCENARIO_DIR` には初回
デプロイと同じ Terraform state に接続されたローカルシナリオディレクトリを指定します。
[スクリプトと開発ガイド](scripts.md)の前提条件に加え、Terraform をインストールし、
対象 state 向けに初期化しておく必要があります。

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

表示されたアプリが意図した対象であることを確認します。次にロック済みの実行時依存関係を
エクスポートし、Flex 互換のリモートビルドで発行します。

```shell
uv export --locked --format requirements-txt --no-dev --no-hashes --no-emit-project --output-file requirements.txt
func azure functionapp publish "$FUNCTION_APP_NAME" --subscription "$SUBSCRIPTION_ID" --build remote --python
```

このアプリケーションでは Terraform シナリオの `scripts/publish_code.sh` を
使用しないでください。このスクリプトは、このリポジトリの `function_app.py` と
`template_azure_python/` パッケージではなく、シナリオ付属の `src/` サンプルを
ステージングして発行します。アプリケーションまたは依存関係を変更した後は、
エクスポートと発行コマンドを再実行してください。

このシナリオでは Microsoft Entra 認証が既定で無効です。次のコマンドで
デプロイを確認します。

```shell
curl --fail --show-error "$FUNCTION_APP_URL/"
# {"Hello":"World"}
curl --fail --show-error --output /dev/null "$FUNCTION_APP_URL/docs"
```

`enable_authentication=true` を指定してシナリオを適用した場合、同じ Terraform
state から正確なアプリケーション ID URI 用のトークンを取得し、両リクエストへ
付与します。

```shell
AUTH_RESOURCE=$(terraform -chdir="$SCENARIO_DIR" output -raw function_app_authentication_identifier_uri)
ACCESS_TOKEN=$(az account get-access-token --subscription "$SUBSCRIPTION_ID" --resource "$AUTH_RESOURCE" --query accessToken --output tsv)
curl --fail --show-error --header "Authorization: ******" "$FUNCTION_APP_URL/"
# {"Hello":"World"}
curl --fail --show-error --output /dev/null --header "Authorization: ******" "$FUNCTION_APP_URL/docs"
unset ACCESS_TOKEN
```

発行された HTTP トリガーは Functions ホストでは匿名です。
`enable_authentication=true` の場合、シナリオの App Service 認証レイヤーが
トリガーへ到達する前に bearer token を要求します。

## Azure Container Apps（既存の Container App）

既存 Container App から取得できるレジストリへ Docker イメージを push します。
HTTP ingress のターゲットポートを **8000** に設定し、イメージを更新します。
プレースホルダーは自身のリソースに置き換えてください。

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

external ingress を使用すると、このサンプルの匿名 API は一般公開されます。必要に応じて
internal ingress または適切なアクセス制御を使用してください。どちらのデプロイも
アプリケーションコードを複製・変更せず、`template_azure_python/api.py` の
ルートを使用します。

### `azure_container_apps` Terraform シナリオの再利用

[azure_container_apps シナリオ](https://github.com/ks6088ts/template-terraform/tree/main/infra/scenarios/azure_container_apps)
が適用済みの場合、新しいアプリを作成せず、その ACR を再利用して**既存の Container
App を置き換えます**。このアプリはシナリオの Terraform で管理されているため、
後の apply で元に戻り得る `az containerapp update` ではなく Terraform 経由で
デプロイします。必要に応じ、先にシナリオの README に従ってプロビジョニングしてください。

このリポジトリのルートから次のコマンドを実行します。`SCENARIO_DIR` には初回
デプロイと同じ Terraform state にアクセスできるローカルシナリオディレクトリを
指定します。Terraform、起動中の Docker daemon、Azure CLI、`jq`、`curl` が
必要です。シナリオのレジストリに対する `AcrPush` が付与された ID でサインインします。
既定では Terraform 実行 ID に付与されます。Container App の managed identity
には `AcrPull` が設定済みです。

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

push したイメージを digest で固定し、シナリオの無視対象ファイル
`deployment.auto.tfvars.json` に設定します。以前にシナリオ付属の MCP
サーバーをデプロイしていた場合、既存の他の設定を保持したまま、イメージ、ingress と
probe のポートを **8000**、probe パスを `/`、container command を
Dockerfile の既定値へ変更します。シナリオの `build_image.sh` と
`deploy_image.sh` は付属の `src/` を対象にポート 8080 と `/health` を
設定するため、このイメージには使用しないでください。

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

初回デプロイで使用したものと同じ Terraform 変数ファイルとコマンドラインオプションを
維持してください。特に `-var` または `-var-file` で
`enable_authentication=true` を指定した場合は同じ設定が必要です。apply 前に
plan を確認し、意図したイメージ、ポート、probe、command だけが変更されることを
確かめます。

```shell
terraform -chdir="$SCENARIO_DIR" plan
terraform -chdir="$SCENARIO_DIR" apply
```

`/health` と `/mcp` を期待するシナリオの MCP 専用
`verify_deployment.sh` ではなく、FastAPI のルートを確認します。

```shell
CONTAINER_APP_URL=$(terraform -chdir="$SCENARIO_DIR" output -raw container_app_url)
curl --fail --show-error "$CONTAINER_APP_URL/"
# {"Hello":"World"}
curl --fail --show-error --output /dev/null "$CONTAINER_APP_URL/docs"
```

シナリオで Microsoft Entra 認証を有効にした場合、どちらのルートにも access
token が必要です。上記の未認証 `curl` の代わりに次を使用します。

```shell
AUTH_RESOURCE=$(terraform -chdir="$SCENARIO_DIR" output -raw container_app_authentication_identifier_uri)
ACCESS_TOKEN=$(az account get-access-token --subscription "$SUBSCRIPTION_ID" --resource "$AUTH_RESOURCE" --query accessToken -o tsv)
curl --fail --show-error --header "Authorization: ******" "$CONTAINER_APP_URL/"
curl --fail --show-error --output /dev/null --header "Authorization: ******" "$CONTAINER_APP_URL/docs"
unset ACCESS_TOKEN
```

認証や他のアクセス制御を有効にしない限り、シナリオの external ingress はアプリを
一般公開します。後続の Terraform apply のため `deployment.auto.tfvars.json`
を保持してください。シナリオの MCP デプロイスクリプトを再実行すると、これらの
イメージとポート設定は置き換えられます。

## Docker Hub

Docker イメージを Docker Hub へ公開するには、
[access token を作成](https://app.docker.com/settings/personal-access-tokens/create)
し、リポジトリ設定に次の secret を登録します。

```shell
gh secret set DOCKERHUB_USERNAME --body "$DOCKERHUB_USERNAME"
gh secret set DOCKERHUB_TOKEN --body "$DOCKERHUB_TOKEN"
```

## Azure Static Web Apps

Static Web App を作成して API key を取得し、GitHub Actions secret として
保存します。

```shell
RESOURCE_GROUP_NAME=your-resource-group-name
SWA_NAME=your-static-web-app-name

# Static Web App を作成
az staticwebapp create --name "$SWA_NAME" --resource-group "$RESOURCE_GROUP_NAME"

# API key を取得
AZURE_STATIC_WEB_APPS_API_TOKEN=$(az staticwebapp secrets list --name "$SWA_NAME" --query "properties.apiKey" -o tsv)

# API key を GitHub secret に設定
gh secret set AZURE_STATIC_WEB_APPS_API_TOKEN --body "$AZURE_STATIC_WEB_APPS_API_TOKEN"
```

詳細は次の資料を参照してください。

- [Azure Static Web App へのデプロイ](https://docs.github.com/en/actions/use-cases-and-examples/deploying/deploying-to-azure-static-web-app)
- [Static Web App の作成: `az staticwebapp create`](https://learn.microsoft.com/en-us/cli/azure/staticwebapp?view=azure-cli-latest#az-staticwebapp-create)
