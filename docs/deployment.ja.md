# デプロイ

ローカルで確認したアプリやドキュメントを公開します。
**公開したいものに合う手順を 1 つ選んでください。**

| 公開したいもの | 公開先 | 事前に用意するもの |
| --- | --- | --- |
| Python API | [Azure Functions](#azure-functions) | 既存の Linux Function App |
| Docker で動く API | [Azure Container Apps](#azure-container-apps) | 既存の Container App とレジストリ |
| 検証済み Docker イメージ | [GHCR](#ghcr-github-pages) | GitHub Actions の公開権限 |
| MkDocs のドキュメントサイト | [GitHub Pages](#ghcr-github-pages) | Pages の公開元を GitHub Actions に設定 |

## 公開前の共通確認

- [ローカル開発](scripts.md)でアプリを動かしておきます。
- コマンドは、この Python リポジトリのルートで実行します。
  `your-...` や `<...>` は実際の値に置き換えます。
- Azure では `az login` でサインインし、`az account show` で対象を確認します。
  必要なら `az account set --subscription "<subscription-id>"` で切り替えます。
- GitHub の secret 登録や Actions の操作には `gh` が必要です。`gh auth login` で認証します。
- ローカル開発は認証なしです。Azure では、公開前に Easy Auth とアプリロールを設定してください。
  Azure リソースやイメージの保存には料金が発生する場合があります。

probe は `/healthz` と `/readyz` を使います。`/docs` や Task 全件取得には依存しません。
本番では OpenAPI ドキュメントを既定で公開しません。

既定の保存先は InMemory で、replica 間で共有されません。
Cosmos を使う場合は [Task コンテナーの準備](cosmosdb.md#task-api)を済ませ、
Functions のアプリ設定 / Container Apps の環境変数に `TASK_REPOSITORY=cosmosdb`、
`AZURE_COSMOS_DB_ENDPOINT`、`AZURE_COSMOS_DB_DATABASE`、`AZURE_COSMOS_DB_TASK_CONTAINER` を設定します。
API のマネージド ID に対象のデータプレーン RBAC を付与し、管理 CLI の権限は付けません。
管理 CLI 用の account 名・subscription・resource group は API の起動に不要です。

## 保護されたデプロイの初期設定

`infra/main.bicep` と `infra/app.bicep` を同梱しています。外部 Terraform
リポジトリは不要です。staging / production を別のリソースグループに構築します。
Log Analytics、ローカル認証を無効にした Application Insights、管理者認証を無効にした
ACR、Container Apps、実行用とデプロイ用の別々のマネージド ID を作成します。
既定の公開先は GHCR です。ACR へのイメージの転送は自動では行いません。

1. API 用の Entra アプリ登録を作り、`Task.ReadWrite` アプリロールを呼び出し元に割り当てます。
   Easy Auth がトークンを検証し、API が principal ヘッダーで認可します。
   **Easy Auth を経由せず到達できる origin では、このヘッダーを信頼してはいけません。**
2. GHCR パッケージを public にし、検証済みのダイジェストを用意します。可変タグは使いません。
3. `az login` と `gh auth login` を実行します。初期構築にはリソース作成とロール割り当ての権限が必要です。
   レビュー担当者の数値 ID は `gh api users/REVIEWER --jq .id` で取得します。

   ```shell
   bash scripts/bootstrap-azure.sh OWNER/REPO staging rg-api-staging eastus api \
     ghcr.io/owner/repo@sha256:REPLACE_WITH_64_HEX_DIGITS \
     YOUR_ENTRA_APPLICATION_CLIENT_ID YOUR_REVIEWER_USER_ID
   bash scripts/bootstrap-azure.sh OWNER/REPO production rg-api-production eastus api \
     ghcr.io/owner/repo@sha256:REPLACE_WITH_64_HEX_DIGITS \
     YOUR_ENTRA_APPLICATION_CLIENT_ID YOUR_REVIEWER_USER_ID
   ```

   Azure の OIDC 設定より先に GitHub 環境を保護します。main のみ許可し、
   production の承認を必須にして自己承認・管理者バイパスを禁止します。
   GitHub プランにより保護機能が利用できない場合は、保護を外して続行しないでください。
   環境変数 `AZURE_CLIENT_ID`、`AZURE_TENANT_ID`、`AZURE_SUBSCRIPTION_ID`、
   `RESOURCE_GROUP`、`CONTAINER_APP_NAME` を設定します。OIDC subject は
   `repo:OWNER/REPO:environment:staging` または `...:production` です。
   再実行では既存のレビュー担当者と待機時間を保持し、main 以外の許可を変更前に拒否します。
   担当者の変更は GitHub 設定画面で明示的に行ってください。
4. ID、アプリロール、認証、環境の承認者を確認してから CD を有効にします。
   InMemory では最大 replica を 1 にします。複数 replica は永続化とデータプレーン RBAC を設定してから使います。

デプロイせず検証するには次を実行します。

```shell
az bicep build --file infra/main.bicep --outfile /tmp/main.json
az bicep lint --file infra/main.bicep
```

`az deployment group what-if` で差分を確認してから適用してください。
再適用時も現在のダイジェストを指定します。古いイメージに戻るのを防ぐためです。
初回は internal ingress で作成し、Easy Auth の構築成功後に bootstrap が外部公開します。
認証済みのアプリへの再適用で公開を維持する場合は `externalIngress=true` を指定します。
既定値は外部公開を安全側に閉じます。
初回 bootstrap 用のイメージは事前に存在する、レビュー・証明済みのものを使います。

### リポジトリの保護とリリース

private vulnerability reporting、secret scanning、push protection、Dependabot、
CodeQL を設定画面で有効にします。`scripts/init_template.py` で `OWNER` を置換し、
CODEOWNERS が実際の担当者を指すことを確認してください。

`.github/rulesets/` はインポート用のサンプルです。main は `ci-ok` と `pr-title`、
CODEOWNERS レビュー、squash merge と merge queue を要求します。
タグ保護の `bypass_actors` には信頼するリリース用 GitHub App の integration ID
（`actor_type: "Integration"`、`bypass_mode: "always"`）を追加してからインポートします。
空のままでは全ての `v*` タグ作成を禁止します。全 write ユーザーに例外を付けないでください。

```shell
gh api --method POST repos/OWNER/REPO/rulesets --input .github/rulesets/main.json
gh api --method POST repos/OWNER/REPO/rulesets --input .github/rulesets/release-tags.json
```

サンプルは medium 以上の CodeQL 検出もゲートします。private リポジトリでは
Code Security と ruleset のプラン対応を確認してからインポートします。
immutable releases も有効にします。
Conventional Commit の PR タイトルから release-please がリリースを作成します。
イメージは一度だけビルドして検証し、provenance / SBOM を付与します。
staging と承認済み production には同じダイジェストをデプロイします。
プレリリースで `latest` は更新しません。

ロールバックは手動デプロイワークフローに過去の検証済みダイジェストを指定します。
再ビルドせず、通常と同じ証明の検証・環境承認・probe を通します。
private リポジトリの証明に必要な GitHub プランがない場合は、検証を無効にせず、
対応プランまたは別途レビューした署名方式を用意してください。

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
uv export --locked --extra functions --format requirements-txt --no-dev --no-emit-project --output-file requirements.txt
```

#### 2. 発行する

```shell
func azure functionapp publish "$FUNCTION_APP_NAME" --build remote
```

リモートビルドが依存関係をインストールします。別の FastAPI 実装や専用 Docker イメージは不要です。
アプリの設定は Azure 側で行います。`local.settings.json` は発行しません。

#### 3. 応答を確認する

```shell
curl --fail --show-error "https://$FUNCTION_APP_NAME.azurewebsites.net/tasks"
curl --fail --show-error "https://$FUNCTION_APP_NAME.azurewebsites.net/readyz"
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
uv export --locked --extra functions --format requirements-txt --no-dev --no-emit-project --output-file requirements.txt
func azure functionapp publish "$FUNCTION_APP_NAME" --subscription "$SUBSCRIPTION_ID" --build remote --python
```

コードや依存関係を変更した場合は、両コマンドを再実行します。

#### 3. 認証設定に合わせて確認する

既定では Microsoft Entra 認証は無効です。

```shell
curl --fail --show-error "$FUNCTION_APP_URL/tasks"
curl --fail --show-error "$FUNCTION_APP_URL/readyz"
```

`enable_authentication=true` で適用した場合は、代わりに次を使います。
同じ state のアプリケーション ID URI 向けにトークンを取得します。

```shell
AUTH_RESOURCE=$(terraform -chdir="$SCENARIO_DIR" output -raw function_app_authentication_identifier_uri)
ACCESS_TOKEN=$(az account get-access-token --subscription "$SUBSCRIPTION_ID" --resource "$AUTH_RESOURCE" --query accessToken --output tsv)
curl --fail --show-error --header "Authorization: Bearer $ACCESS_TOKEN" "$FUNCTION_APP_URL/tasks"
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
IMAGE_DIGEST=$(docker buildx imagetools inspect "$IMAGE" --format '{{.Manifest.Digest}}')
IMAGE="${IMAGE%:*}@$IMAGE_DIGEST"
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
curl --fail --show-error "https://$CONTAINER_APP_FQDN/tasks"
curl --fail --show-error "https://$CONTAINER_APP_FQDN/readyz"
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
| ヘルスチェックのパス | `/healthz`（生存）・`/readyz`（依存先の疎通） |
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
    '.container_image = $image | .container_port = 8000 | .health_probe_path = "/healthz" | .container_command = []' \
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
curl --fail --show-error "$CONTAINER_APP_URL/tasks"
curl --fail --show-error "$CONTAINER_APP_URL/readyz"
```

Microsoft Entra 認証を有効にした場合は、代わりに次を使います。

```shell
AUTH_RESOURCE=$(terraform -chdir="$SCENARIO_DIR" output -raw container_app_authentication_identifier_uri)
ACCESS_TOKEN=$(az account get-access-token --subscription "$SUBSCRIPTION_ID" --resource "$AUTH_RESOURCE" --query accessToken -o tsv)
curl --fail --show-error --header "Authorization: Bearer $ACCESS_TOKEN" "$CONTAINER_APP_URL/tasks"
curl --fail --show-error --output /dev/null --header "Authorization: Bearer $ACCESS_TOKEN" "$CONTAINER_APP_URL/docs"
unset ACCESS_TOKEN
```

認証やアクセス制御がなければ、external ingress は API を一般公開します。
`deployment.auto.tfvars.json` は次回の apply 用に保持してください。
シナリオの MCP デプロイスクリプトを再実行すると、イメージやポートの設定が置き換わります。

## GHCR と GitHub Pages

GHCR は `GITHUB_TOKEN` で公開します。Docker Hub トークンは不要です。
Actions の package 公開権限と、Container Apps 用の public package を設定してください。

**Settings → Pages** の公開元を **GitHub Actions** にします。read-only 権限・資格情報を
保持しない checkout でビルドし、Pages artifact を別の `github-pages` 環境で公開します。
`gh-pages` ブランチへの push と Static Web Apps トークンは不要です。

既定では閲覧解析や作者の SNS リンクを含みません。必要なら自分の解析 ID と
プライバシー告知を設定してください。MkDocs / Material の依存には上限を設け、
upstream の保守状態を確認して更新します。後継への移行は別ブランチで試し、
日英の両言語・Mermaid・既存の URL・strict build が動作するまで切り替えません。

Copilot cloud agent の環境定義は `.github/workflows/copilot-setup-steps.yml` です。
default branch にマージしてから有効になります。手順と安全境界は AGENTS.md に記載しています。
`.mcp.json` の Microsoft Learn は対応クライアントで任意に使います。
cloud agent の MCP はリポジトリ設定画面で別途設定し、資格情報をソースに保存しません。

`.github/hooks/guardrails.json` は強制 push や Azure 削除などの典型的な操作ミスを拒否します。
コマンドの文字列検査は sandbox ではなく、変数展開や任意のプログラムまで安全性を保証しません。
人の承認・最小権限の ID・環境保護を、実際の強制境界として維持してください。
