# デプロイ

ローカルで確認したアプリやドキュメントを公開します。
**公開したいものに合う手順を 1 つ選んでください。**

| 公開したいもの | 公開先 | 事前に用意するもの |
| --- | --- | --- |
| Python API | [Azure Functions](#azure-functions) | 既存の Linux Function App |
| Docker で動く API | [Azure Container Apps](#azure-container-apps) | 既存の Container App とレジストリ |
| Docker イメージ | [Docker Hub](#docker-hub) | Docker Hub アカウントと access token |
| MkDocs のドキュメントサイト | [Azure Static Web Apps](#azure-static-web-apps) | Azure のリソースグループと GitHub リポジトリ |

## 公開前の共通確認

- [ローカル開発](scripts.md)でアプリを動かしておきます。
- コマンドは、この Python リポジトリのルートで実行します。
  `your-...` や `<...>` は実際の値に置き換えます。
- Azure では `az login` でサインインし、`az account show` で対象を確認します。
  必要なら `az account set --subscription "<subscription-id>"` で切り替えます。
- GitHub の secret 登録や Actions の操作には `gh` が必要です。`gh auth login` で認証します。
- API は認証なしのサンプルです。一般公開する前に、必要なアクセス制御を用意してください。
  Azure リソースやイメージの保存には料金が発生する場合があります。

API の確認では、`/` が `{"Hello":"World"}` を返し、`/docs` が HTTP 200 を返せば正常です。

## Azure Functions

**必要なツール**: uv、Azure CLI、Functions Core Tools v4、curl。
Function App は、Azure がサポートする Python バージョン、Functions ランタイム v4、
Azure Storage を設定した既存の Linux アプリを使います。この手順ではアプリを作成しません。

### 既存の Function App に公開する

#### 1. 依存関係を出力する

**発行のたびに** `uv.lock` から `requirements.txt` を作成します。
このファイルは Git の無視対象ですが、Functions への発行には含まれます。

```shell
FUNCTION_APP_NAME=your-function-app-name
uv export --locked --format requirements-txt --no-dev --no-hashes --no-emit-project --output-file requirements.txt
```

#### 2. 発行する

```shell
func azure functionapp publish "$FUNCTION_APP_NAME" --build remote
```

リモートビルドが依存関係をインストールします。別の FastAPI 実装や専用 Docker イメージは不要です。
アプリの設定は Azure 側で行います。`local.settings.json` は発行しません。

#### 3. 応答を確認する

```shell
curl --fail --show-error "https://$FUNCTION_APP_NAME.azurewebsites.net/"
curl --fail --show-error --output /dev/null "https://$FUNCTION_APP_NAME.azurewebsites.net/docs"
```

アプリで認証を有効にしている場合は、その設定に合う認証情報も必要です。

### Terraform の Flex Consumption シナリオを使う場合

[`azure_functions_flex_consumption`](https://github.com/ks6088ts/template-terraform/tree/main/infra/scenarios/azure_functions_flex_consumption)
を適用済みの場合は、以下の手順を使います。
Terraform はインフラを作成し、アプリのコードはこのリポジトリから発行します。
Terraform をインストールし、**初回と同じ state（リソースの管理記録）**向けに初期化しておきます。

**シナリオの `scripts/publish_code.sh` は使いません。**
そのスクリプトは付属の `src/` サンプルを発行し、このアプリの
`function_app.py` と `template_azure_python/` を発行しません。

#### 1. 対象のアプリを確認する

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

表示されたアプリが公開先であることを確認してから進みます。

#### 2. 依存関係を出力して発行する

```shell
uv export --locked --format requirements-txt --no-dev --no-hashes --no-emit-project --output-file requirements.txt
func azure functionapp publish "$FUNCTION_APP_NAME" --subscription "$SUBSCRIPTION_ID" --build remote --python
```

コードや依存関係を変更した場合は、両コマンドを再実行します。

#### 3. 認証設定に合わせて確認する

既定では Microsoft Entra 認証は無効です。

```shell
curl --fail --show-error "$FUNCTION_APP_URL/"
curl --fail --show-error --output /dev/null "$FUNCTION_APP_URL/docs"
```

`enable_authentication=true` で適用した場合は、代わりに次を使います。
同じ state のアプリケーション ID URI 向けにトークンを取得します。

```shell
AUTH_RESOURCE=$(terraform -chdir="$SCENARIO_DIR" output -raw function_app_authentication_identifier_uri)
ACCESS_TOKEN=$(az account get-access-token --subscription "$SUBSCRIPTION_ID" --resource "$AUTH_RESOURCE" --query accessToken --output tsv)
curl --fail --show-error --header "Authorization: Bearer $ACCESS_TOKEN" "$FUNCTION_APP_URL/"
curl --fail --show-error --output /dev/null --header "Authorization: Bearer $ACCESS_TOKEN" "$FUNCTION_APP_URL/docs"
unset ACCESS_TOKEN
```

Functions の HTTP トリガー自体は匿名です。認証を有効にした場合は、
その手前の App Service 認証がトークンを確認します。

## Azure Container Apps

**必要なツール**: Docker、Azure CLI、curl。
既存の Container App と、そこからイメージを取得できるレジストリを使います。
レジストリへの push 権限とログインも必要です。
Terraform で管理するアプリには、次の Terraform 用手順を使ってください。

### 既存の Container App を更新する

#### 1. イメージをビルドして push する

```shell
IMAGE=your-registry.example.com/template-azure-python:your-tag
RESOURCE_GROUP_NAME=your-resource-group-name
CONTAINER_APP_NAME=your-container-app-name

docker build --platform linux/amd64 -t "$IMAGE" .
docker push "$IMAGE"
```

#### 2. ポートとイメージを更新する

HTTP の受け口（ingress）のポートは **8000** です。
**次の `external` 設定は、認証なしの API を一般公開します。**
内部向けの場合は `internal`、または適切なアクセス制御を使ってください。

```shell
az containerapp ingress enable --name "$CONTAINER_APP_NAME" \
  --resource-group "$RESOURCE_GROUP_NAME" --type external --target-port 8000
az containerapp update --name "$CONTAINER_APP_NAME" \
  --resource-group "$RESOURCE_GROUP_NAME" --image "$IMAGE"
```

#### 3. 応答を確認する

```shell
CONTAINER_APP_FQDN=$(az containerapp show --name "$CONTAINER_APP_NAME" --resource-group "$RESOURCE_GROUP_NAME" --query properties.configuration.ingress.fqdn -o tsv)
curl --fail --show-error "https://$CONTAINER_APP_FQDN/"
curl --fail --show-error --output /dev/null "https://$CONTAINER_APP_FQDN/docs"
```

### Terraform の Container Apps シナリオを使う場合

[`azure_container_apps`](https://github.com/ks6088ts/template-terraform/tree/main/infra/scenarios/azure_container_apps)
を適用済みの場合、その ACR を再利用し、**既存の Container App をこの API に置き換えます。**
新しいアプリは作成しません。未作成なら、先にシナリオの README に従って準備します。

Terraform 管理下のアプリを `az containerapp update` で変更すると、後の apply で戻るおそれがあります。
ここでは Terraform 経由で更新します。

**追加で必要なもの**: Terraform、jq、起動中の Docker。
`SCENARIO_DIR` は初回と同じ state に接続されたディレクトリです。
実行 ID には ACR の `AcrPush` が必要です（既定は Terraform 実行者）。
Container App のマネージド ID には `AcrPull` が設定済みです。

#### 1. 対象と前提条件を確認する

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

#### 2. イメージをビルドして push する

```shell
IMAGE_REPOSITORY=template-azure-python
IMAGE_TAG=$(git rev-parse --short HEAD)
IMAGE="$ACR_LOGIN_SERVER/$IMAGE_REPOSITORY:$IMAGE_TAG"
docker build --platform linux/amd64 --tag "$IMAGE" .
az acr login --name "$ACR_NAME" --subscription "$SUBSCRIPTION_ID"
docker push "$IMAGE"
```

#### 3. Terraform にイメージとポートを設定する

push 済みイメージを digest（イメージの固定識別子）で指定します。
次のコマンドは、既存の他の設定を保ったまま `deployment.auto.tfvars.json` を更新します。

| 変更する項目 | 設定値 |
| --- | --- |
| イメージ | push 済みの digest |
| ingress とヘルスチェックのポート | `8000` |
| ヘルスチェックのパス | `/` |
| 起動コマンド | Dockerfile の既定値 |

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

シナリオの `build_image.sh` / `deploy_image.sh` は使いません。
付属の MCP サーバー向けに `src/`、ポート 8080、`/health` を設定するスクリプトです。

#### 4. 変更内容を確認して適用する

初回に使った `-var` / `-var-file` は、次の**両コマンドにも同じ指定を追加**します。
特に `enable_authentication=true` を維持してください。

```shell
terraform -chdir="$SCENARIO_DIR" plan
terraform -chdir="$SCENARIO_DIR" apply
```

plan で意図したイメージ・ポート・ヘルスチェック・起動コマンドだけが変わることを確認してから apply します。

#### 5. API の応答を確認する

MCP 専用の `verify_deployment.sh` は `/health` と `/mcp` を確認するため、使いません。
この API のルートを確認します。

```shell
CONTAINER_APP_URL=$(terraform -chdir="$SCENARIO_DIR" output -raw container_app_url)
curl --fail --show-error "$CONTAINER_APP_URL/"
curl --fail --show-error --output /dev/null "$CONTAINER_APP_URL/docs"
```

Microsoft Entra 認証を有効にした場合は、代わりに次を使います。

```shell
AUTH_RESOURCE=$(terraform -chdir="$SCENARIO_DIR" output -raw container_app_authentication_identifier_uri)
ACCESS_TOKEN=$(az account get-access-token --subscription "$SUBSCRIPTION_ID" --resource "$AUTH_RESOURCE" --query accessToken -o tsv)
curl --fail --show-error --header "Authorization: Bearer $ACCESS_TOKEN" "$CONTAINER_APP_URL/"
curl --fail --show-error --output /dev/null --header "Authorization: Bearer $ACCESS_TOKEN" "$CONTAINER_APP_URL/docs"
unset ACCESS_TOKEN
```

認証やアクセス制御がなければ、external ingress は API を一般公開します。
`deployment.auto.tfvars.json` は次回の apply 用に保持してください。
シナリオの MCP デプロイスクリプトを再実行すると、イメージやポートの設定が置き換わります。

## Docker Hub

この手順は**イメージの公開**です。API サーバーの起動は行いません。

1. Docker Hub の [access token](https://app.docker.com/settings/personal-access-tokens/create)を作成します。
2. GitHub リポジトリに secret を登録します。次のコマンドで表示される入力欄に値を入れます。

   ```shell
   gh secret set DOCKERHUB_USERNAME
   gh secret set DOCKERHUB_TOKEN
   ```

3. `v` で始まるタグを push すると、`docker-release` ワークフローがイメージを公開します。
4. GitHub Actions の成功と、Docker Hub の `<username>/template-azure-python` のタグを確認します。

   ```shell
   gh run list --workflow docker-release.yaml --limit 1
   ```

## Azure Static Web Apps

このリポジトリのワークフローは **MkDocs のサイト**を公開します。FastAPI の公開先ではありません。
既定のドキュメント公開は GitHub Pages（`main` への push）です。
Static Web Apps を使う場合だけ、以下を設定します。

### 1. Static Web App を作成する

既存のリソースグループを指定します。

```shell
RESOURCE_GROUP_NAME=your-resource-group-name
SWA_NAME=your-static-web-app-name
az staticwebapp create --name "$SWA_NAME" --resource-group "$RESOURCE_GROUP_NAME"
```

### 2. デプロイ用の secret を登録する

API key を取得して GitHub に登録します。値を表示したり、ソースに保存したりしないでください。

```shell
AZURE_STATIC_WEB_APPS_API_TOKEN=$(az staticwebapp secrets list --name "$SWA_NAME" --resource-group "$RESOURCE_GROUP_NAME" --query "properties.apiKey" -o tsv)
gh secret set AZURE_STATIC_WEB_APPS_API_TOKEN --body "$AZURE_STATIC_WEB_APPS_API_TOKEN"
unset AZURE_STATIC_WEB_APPS_API_TOKEN
```

### 3. ワークフローを実行する

既定は手動実行です。ドキュメントをビルドして、生成されたサイトをアップロードします。

```shell
gh workflow run azure-static-web-app.yaml
gh run list --workflow azure-static-web-app.yaml --limit 1
```

自動実行する場合は、ワークフローのコメントに従い `main` への push トリガーを有効にします。

### 4. 公開サイトを確認する

Actions の成功を待ち、次のホスト名をブラウザーで開きます。
英語・日本語のページが表示されることを確認してください。

```shell
az staticwebapp show --name "$SWA_NAME" --resource-group "$RESOURCE_GROUP_NAME" --query defaultHostname -o tsv
```

詳細は [GitHub Actions からの公開](https://docs.github.com/en/actions/use-cases-and-examples/deploying/deploying-to-azure-static-web-app)と
[`az staticwebapp create`](https://learn.microsoft.com/en-us/cli/azure/staticwebapp?view=azure-cli-latest#az-staticwebapp-create)を参照してください。
