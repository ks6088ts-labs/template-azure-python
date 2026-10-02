# スクリプトと開発

## 前提条件

- [Python 3.10+](https://www.python.org/downloads/)（CI は 3.10 から 3.14 でテスト）
- [uv 0.12.19](https://docs.astral.sh/uv/getting-started/installation/)
- [GNU Make](https://www.gnu.org/software/make/)
- ローカル lint と CI チェック用の
  [actionlint](https://github.com/rhysd/actionlint)（CI は v1.7.12 を使用）
- Docker ターゲット用の [Docker](https://docs.docker.com/get-docker/)
- Functions のローカル実行用の
  [Azure Functions Core Tools v4](https://learn.microsoft.com/azure/azure-functions/functions-run-local)
- HTTP 確認用の `curl`
- Azure SDK サンプルと既存 Azure リソースへの発行用の
  [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli)

## Make ターゲット

リポジトリルートで次のコマンドを実行します。

```shell
# 利用可能なターゲットを表示
make

# 開発用依存関係と Git hook をインストール
make install-deps-dev

# 設定済みの全 hook を確認
make hooks-check

# テストを実行
make test

# CI テスト一式を実行
make ci-test

# 英語と日本語のドキュメントをビルド
make ci-test-docs

# JupyterLab を起動
make jupyterlab
```

`make install-deps-dev` は開発用グループをすべてインストールし、以前の
pre-commit hook を置き換えて [prek](https://prek.j178.dev/) Git hook を
インストールします。CI は JupyterLab を含まない小さな依存関係セットを使用します。
notebook グループは `make jupyterlab` から利用できます。

`make lint` はオフラインの [zizmor](https://zizmor.sh/) チェックも実行し、
重大度 high の GitHub Actions 設定上の問題をブロックします。低い重大度も確認するには
`uv run --locked zizmor --offline .` を実行してください。

## アプリケーション CLI

`scripts.template` モジュールはアプリケーション開発用コマンドを提供します。
コマンドとオプションの一覧を表示するには次を実行します。

```shell
uv run --locked python -m scripts.template --help
```

### 基本コマンド

存在する場合は `.env` から設定を読み込み、サンプルコマンドを実行します。

```shell
uv run --locked python -m scripts.template hello
uv run --locked python -m scripts.template --verbose hello --name Azure
```

### Azure Container Apps またはローカル Uvicorn 上の FastAPI

どちらのホストも `template_azure_python/api.py` の同じ FastAPI アプリを使用します。
ローカルで Uvicorn を起動します。

```shell
uv run --locked python -m scripts.template serve-container-apps
```

既定では `http://127.0.0.1:8000` で待ち受けます。アドレスを変更するには
`--host` と `--port` を使用します。

```shell
uv run --locked python -m scripts.template serve-container-apps --host 0.0.0.0 --port 8080
```

別のターミナルから既定のサーバーを確認します。

```shell
curl http://127.0.0.1:8000/
# {"Hello":"World"}
curl -I http://127.0.0.1:8000/docs
```

対話型 API ドキュメントは `http://127.0.0.1:8000/docs` で確認できます。

### Azure Functions 上の FastAPI

ルートの `function_app.py` は
[Azure FastAPI サンプル](https://github.com/Azure-Samples/fastapi-on-azure-functions)
と同様に、同じ FastAPI アプリを Azure Functions の `AsgiFunctionApp` で
ラップします。`host.json` は既定の `/api` ルートプレフィックスを削除するため、
ホスト間で URL は同一です。サンプルと同様に HTTP トリガーは匿名です。
機密性のあるルートを公開する前にアクセス制御を追加してください。

リポジトリルートで、無視対象のローカル設定ファイルを一度作成します。

```shell
cp local.settings.json.example local.settings.json
```

この例では HTTP 専用アプリのため `AzureWebJobsStorage` を空にしています。
他のトリガーには有効なストレージ接続が必要です。値が空でも HTTP ルートは動作しますが、
Core Tools がストレージのヘルス警告を出す場合があります。ヘルスチェックを満たすには
Azurite を起動し、`local.settings.json` の `AzureWebJobsStorage` を
`UseDevelopmentStorage=true` に設定します。

Core Tools v4 をインストールしてローカル Functions ホストを起動します。

```shell
uv run --locked python -m scripts.template serve-functions
# 別のローカルポートを使用
uv run --locked python -m scripts.template serve-functions --port 7072
```

別のターミナルから API とドキュメントを確認します。

```shell
curl http://127.0.0.1:7071/
# {"Hello":"World"}
curl -I http://127.0.0.1:7071/docs
```

CLI が Core Tools を起動するのはローカル開発時だけです。Azure では Functions
ランタイムが `function_app.py` を直接検出し、この CLI は実行しません。非公開の
`local.settings.json` と `.env` は Functions の発行と Docker ビルドから
除外されます。

## Microsoft Foundry CLI

`scripts.cli_foundry` モジュールは Microsoft Foundry Python SDK
クイックスタートを実行します。環境変数テンプレートをコピーし、
`FOUNDRY_PROJECT_ENDPOINT` に `/api/projects/` を含む HTTPS
プロジェクト URL を設定して認証します。

```shell
cp .env.template .env
az login
uv run --locked python -m scripts.cli_foundry --help
```

### 必要な Foundry RBAC

プロジェクトエンドポイントは `DefaultAzureCredential` を介して Microsoft
Entra ID 認証を使用します。コマンドを実行する前に、Foundry アカウントで
[Foundry User ロール](https://learn.microsoft.com/ja-jp/azure/foundry/concepts/rbac-foundry)
を次の両方に割り当ててください。

- CLI を実行するユーザーまたはサービスプリンシパル
- Foundry プロジェクトのマネージド ID

`Foundry User` の旧名称は `Azure AI User` です。名称変更の反映中は旧名称が
表示される場合があります。Azure の `Owner` と `Contributor` は管理プレーンの
アクセス権を付与しますが、プロジェクトの全データプレーン権限は付与しないため、
このロールの代わりにはなりません。Foundry ポータルでプロジェクトを作成し、
作成者がロールを割り当てられる場合は自動的に設定されることがあります。それ以外の
方法で作成したプロジェクトでは、次の割り当てが必要になる場合があります。

実行者にはロール割り当てを作成する権限が必要です。プレースホルダーを置き換え、
Foundry アカウントのスコープでアクセス権を付与します。

```shell
SUBSCRIPTION_ID="$(az account show --query id --output tsv)"
RESOURCE_GROUP="<foundry-resource-group>"
FOUNDRY_ACCOUNT="<foundry-account-name>"
FOUNDRY_PROJECT="<foundry-project-name>"

FOUNDRY_SCOPE="/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.CognitiveServices/accounts/${FOUNDRY_ACCOUNT}"
PROJECT_SCOPE="${FOUNDRY_SCOPE}/projects/${FOUNDRY_PROJECT}"

USER_OBJECT_ID="$(az ad signed-in-user show --query id --output tsv)"
PROJECT_PRINCIPAL_ID="$(az resource show \
  --ids "${PROJECT_SCOPE}" \
  --query identity.principalId \
  --output tsv)"

az role assignment create \
  --assignee-object-id "${USER_OBJECT_ID}" \
  --assignee-principal-type User \
  --role "Foundry User" \
  --scope "${FOUNDRY_SCOPE}"

az role assignment create \
  --assignee-object-id "${PROJECT_PRINCIPAL_ID}" \
  --assignee-principal-type ServicePrincipal \
  --role "Foundry User" \
  --scope "${FOUNDRY_SCOPE}"
```

`PROJECT_PRINCIPAL_ID` が空の場合は、続行する前にプロジェクトのマネージド ID を
構成してください。両方の割り当てが表示されることを確認します。

```shell
az role assignment list \
  --scope "${FOUNDRY_SCOPE}" \
  --include-inherited \
  --query "[?roleDefinitionName=='Foundry User' && (principalId=='${USER_OBJECT_ID}' || principalId=='${PROJECT_PRINCIPAL_ID}')].{principalType:principalType,role:roleDefinitionName,scope:scope}" \
  --output table
```

### `PermissionDeniedError: 403` のトラブルシューティング

プロジェクトのデータプレーンロールが不足していると、コマンドが次のようなエラーで
終了することがあります。レスポンス本文が空の場合もあります。

```text
PermissionDeniedError: Error code: 403
```

コードを変更する前に、次の順序で確認してください。

1. Azure CLI が意図したサブスクリプション、テナント、ID を使用していることを
   確認します。

   ```shell
   az account show \
     --query "{subscription:name,tenantId:tenantId,user:user.name}" \
     --output table
   ```

2. `FOUNDRY_PROJECT_ENDPOINT` が
   `https://<account>.services.ai.azure.com/api/projects/<project>` 形式の
   プロジェクト URL であることを確認します。
3. デプロイが存在して準備済みであり、Responses API に対応していることを
   確認します。

   ```shell
   az cognitiveservices account deployment show \
     --resource-group "${RESOURCE_GROUP}" \
     --name "${FOUNDRY_ACCOUNT}" \
     --deployment-name "gpt-5-mini" \
     --query "{state:properties.provisioningState,responses:properties.capabilities.responses,model:properties.model.name,version:properties.model.version}" \
     --output table
   ```

4. 前述のロール割り当て確認コマンドを実行します。呼び出し元 ID または
   プロジェクトのマネージド ID が表示されない場合は、不足している
   `Foundry User` の割り当てを作成します。
5. RBAC の反映に数分待ってから、再実行します。

   ```shell
   uv run --locked python -m scripts.cli_foundry chat-model
   ```

デプロイが準備済みで両方のロールが存在しているにもかかわらず 403 が続く場合は、
Foundry アカウントのファイアウォール、仮想ネットワーク、プライベートエンドポイント
設定を確認してください。ネットワーク拒否やリソース停止の確認方法は、Microsoft の
[HTTP エラーのトラブルシューティングガイド](https://learn.microsoft.com/ja-jp/azure/foundry/openai/how-to/troubleshoot-errors)
を参照してください。`create-agent` または `chat-agent` でプロジェクトエンドポイントを
リソースレベルの OpenAI エンドポイントに置き換えないでください。これはプロジェクトの
アクセス設定を修正せず、プロジェクト固有の機能を迂回します。

モデルへ直接 1 つのプロンプトを送信します。

```shell
uv run --locked python -m scripts.cli_foundry chat-model
uv run --locked python -m scripts.cli_foundry chat-model \
  --model gpt-5-mini \
  --prompt "What is the size of France in square miles?"
```

プロンプトエージェントを作成します。同名のエージェントが存在する場合は新しい
バージョンを作成します。

```shell
uv run --locked python -m scripts.cli_foundry create-agent
uv run --locked python -m scripts.cli_foundry create-agent \
  --agent-name MyAgent \
  --model gpt-5-mini \
  --instructions "You are a helpful assistant."
```

エージェントを作成または更新し、2 ターンの会話を実行します。

```shell
uv run --locked python -m scripts.cli_foundry chat-agent
uv run --locked python -m scripts.cli_foundry chat-agent \
  --agent-name MyAgent \
  --prompt "What is the size of France in square miles?" \
  --follow-up-prompt "And what is the capital city?"
```

`FOUNDRY_PROJECT_ENDPOINT` を上書きするには `--endpoint` を使用します。
すべてのオプションと既定値は各コマンドの `--help` で確認できます。

## Azure Cosmos DB CLI

`scripts.cli_cosmosdb` モジュールは
[Azure Cosmos DB for NoSQL Python クイックスタート](https://learn.microsoft.com/ja-jp/azure/cosmos-db/quickstart-python)
の Python SDK 操作を個別コマンドとして集約します。環境変数テンプレートを
コピーしてアカウントエンドポイントを設定し、Microsoft Entra ID で認証します。

```shell
cp .env.template .env
az login
uv run --locked python -m scripts.cli_cosmosdb --help
```

ローカルでは `DefaultAzureCredential` が Azure CLI でサインインした ID を
使用します。この ID には、データベースとコンテナーの作成、およびアイテムの
書き込み、読み取り、クエリに必要な最小権限の Azure Cosmos DB データプレーン
アクセス許可を付与してください。

既定値はクイックスタートと同じ `cosmicworks` データベース、`products`
コンテナー、`/category` パーティションキーです。各コマンドは必要に応じて
データベースとコンテナーを作成します。サーバーレス構成と共有スループット構成
に対応するため、専用スループットは既定では指定しません。新しいコンテナーに
専用スループットが必要な場合は、`--throughput` で RU/s を指定します。

チュートリアルのアイテムを作成します。同じ ID が存在する場合は置き換えます。

```shell
uv run --locked python -m scripts.cli_cosmosdb upsert-item
uv run --locked python -m scripts.cli_cosmosdb upsert-item \
  --item-id aaaaaaaa-0000-1111-2222-bbbbbbbbbbbb \
  --category gear-surf-surfboards \
  --name "Yamba Surfboard" \
  --quantity 12 \
  --no-sale
```

アイテム ID とパーティションキーを使ってポイント読み取りを実行します。

```shell
uv run --locked python -m scripts.cli_cosmosdb read-item
uv run --locked python -m scripts.cli_cosmosdb read-item \
  --item-id aaaaaaaa-0000-1111-2222-bbbbbbbbbbbb \
  --category gear-surf-surfboards
```

クイックスタートのパラメーター化されたパーティション内カテゴリクエリを
実行します。

```shell
uv run --locked python -m scripts.cli_cosmosdb query-items
uv run --locked python -m scripts.cli_cosmosdb query-items \
  --category gear-surf-surfboards
```

環境変数 `AZURE_COSMOS_DB_ENDPOINT`、`AZURE_COSMOS_DB_DATABASE`、
`AZURE_COSMOS_DB_CONTAINER` の値を上書きするには、`--endpoint`、
`--database`、`--container` を使用します。すべてのオプションは各コマンドの
`--help` で確認できます。

## Azure メッセージング CLI

4 つの独立したモジュールで、次の記事のパスワードレスの例を実行できます。

- [Event Grid Python SDK](https://learn.microsoft.com/en-us/python/api/overview/azure/eventgrid-readme?view=azure-python)
- [Event Hubs Python クイックスタート](https://learn.microsoft.com/en-us/azure/event-hubs/event-hubs-python-get-started-send?tabs=passwordless%2Croles-azure-portal)
- [Service Bus Queue Python クイックスタート](https://learn.microsoft.com/en-us/azure/service-bus-messaging/service-bus-python-how-to-use-queues?tabs=passwordless)
- [Queue Storage Python クイックスタート](https://learn.microsoft.com/en-us/azure/storage/queues/storage-quickstart-queues-python?tabs=passwordless%2Croles-azure-portal%2Cenvironment-variable-windows%2Csign-in-azure-cli)

### Terraform 出力と認証

[`ks6088ts/template-terraform` の `infra/scenarios/azure_messaging`](https://github.com/ks6088ts/template-terraform/tree/main/infra/scenarios/azure_messaging)
でデプロイ済みのリソースを使用します。各サービスは既定で無効のため、同リポジトリの
手順で使用するサービスを有効にしてください。この Python リポジトリで Terraform を
変更する必要はありません。Terraform のチェックアウト先で出力を確認します。

```shell
terraform -chdir=infra/scenarios/azure_messaging output
# 1 つの値を引用符なしで表示:
terraform -chdir=infra/scenarios/azure_messaging output -raw event_grid_topic_endpoint
```

この Python リポジトリでテンプレートを一度コピーし（既存の `.env` は上書きしない）、
プレースホルダーを対応する出力に置き換えてサインインします。

```shell
cp .env.template .env
az login
uv run --locked python -m scripts.cli_event_grid --help
uv run --locked python -m scripts.cli_event_hubs --help
uv run --locked python -m scripts.cli_service_bus --help
uv run --locked python -m scripts.cli_queue_storage --help
```

| Terraform 出力 | `.env` 変数 | CLI 上書きオプション |
| --- | --- | --- |
| `event_grid_topic_endpoint` | `AZURE_EVENT_GRID_TOPIC_ENDPOINT` | `--endpoint` |
| `event_hubs_namespace_fqdn` | `AZURE_EVENT_HUBS_FULLY_QUALIFIED_NAMESPACE` | `--fully-qualified-namespace` |
| `event_hub_name` | `AZURE_EVENT_HUB_NAME` | `--event-hub` |
| `event_hub_consumer_group_name` | `AZURE_EVENT_HUB_CONSUMER_GROUP` | `--consumer-group` |
| `service_bus_namespace_fqdn` | `AZURE_SERVICE_BUS_FULLY_QUALIFIED_NAMESPACE` | `--fully-qualified-namespace` |
| `service_bus_queue_name` | `AZURE_SERVICE_BUS_QUEUE_NAME` | `--queue` |
| `queue_storage_endpoint` | `AZURE_QUEUE_STORAGE_ENDPOINT` | `--endpoint` |
| `queue_storage_queue_name` | `AZURE_QUEUE_STORAGE_QUEUE_NAME` | `--queue` |

無効なサービスの出力は null または未表示のため、設定値として使わないでください。
名前空間には `<namespace>.servicebus.windows.net` のようなホスト名だけを指定し、
スキームやパスは含めません。エンドポイントは HTTPS URL です。Storage には
Blob/DFS ではなく Queue エンドポイントを指定します。組み込みコンシューマー
グループ名は文字列 `$Default` です。シェルでは `'$Default'` と引用してください。

4 つの CLI は **`DefaultAzureCredential` のみ**を使用します。ローカルでは
`az login` などの開発者資格情報、Azure ではホストのマネージド ID を利用できます。
意図した ID を構成して下記のロールを付与してください。Azure のマネージド ID は
ローカルユーザーの権限を継承しません。既定の資格情報チェーンで他の資格情報が
設定されていると Azure CLI より優先される場合があります。接続文字列、アカウント
キー、SAS のオプションはありません。Terraform シナリオもデータプレーンの
共有キー・ローカル認証を無効にしています。

### Azure から設定を再取得する

`terraform output` が `Required plugins are not installed` で失敗する場合は、
Terraform のチェックアウト先でシナリオを初期化してから出力を取得します。

```shell
terraform -chdir=infra/scenarios/azure_messaging init
```

Terraform を使わず、Azure から秘密情報を含まない設定値を取得することもできます。
サインインと対象サブスクリプションの選択を済ませ、リソース名を置き換えて実行します。

```shell
RESOURCE_GROUP="<messaging-resource-group>"
EVENT_HUBS_NAMESPACE="<event-hubs-namespace>"
EVENT_HUB="<event-hub-name>"
SERVICE_BUS_NAMESPACE="<service-bus-namespace>"
STORAGE_ACCOUNT="<queue-storage-account>"

az eventgrid topic list --resource-group "$RESOURCE_GROUP" \
  --query '[].{name:name,endpoint:endpoint,inputSchema:inputSchema}' --output table
az eventhubs namespace show --resource-group "$RESOURCE_GROUP" \
  --name "$EVENT_HUBS_NAMESPACE" --query serviceBusEndpoint --output tsv
az eventhubs eventhub list --resource-group "$RESOURCE_GROUP" \
  --namespace-name "$EVENT_HUBS_NAMESPACE" --query '[].name' --output tsv
az eventhubs eventhub consumer-group list --resource-group "$RESOURCE_GROUP" \
  --namespace-name "$EVENT_HUBS_NAMESPACE" --eventhub-name "$EVENT_HUB" \
  --query '[].name' --output tsv
az servicebus namespace show --resource-group "$RESOURCE_GROUP" \
  --name "$SERVICE_BUS_NAMESPACE" --query serviceBusEndpoint --output tsv
az servicebus queue list --resource-group "$RESOURCE_GROUP" \
  --namespace-name "$SERVICE_BUS_NAMESPACE" --query '[].name' --output tsv
az storage account show --resource-group "$RESOURCE_GROUP" \
  --name "$STORAGE_ACCOUNT" --query primaryEndpoints.queue --output tsv
az storage queue list --account-name "$STORAGE_ACCOUNT" --auth-mode login \
  --query '[].name' --output tsv
```

名前空間の `serviceBusEndpoint` はホスト名だけを使います。たとえば
`https://example.servicebus.windows.net:443/` は
`example.servicebus.windows.net` にします。Event Grid と Queue Storage には
HTTPS URL 全体を設定します。前述の対応表の変数だけを更新し、既存の `.env` の
他の設定を削除しないでください。`.env` はローカルでのみ保持し、Git の無視対象に
します。アカウントキーや SAS は不要です。Storage のキュー一覧取得には
データプレーンロールが必要です。設定の取得や CLI の検証に `terraform apply` は
必要ありません。

### 必要なメッセージング RBAC

シナリオは有効な各サービスについて次のロールを `operator_principal_id` 出力の
プリンシパルに割り当てます。既定は Terraform 実行者で、同名の入力変数で別の
プリンシパルを指定できます。

| サービス | 割り当て済みデータプレーンロール | 割り当てスコープ（Terraform 出力） |
| --- | --- | --- |
| Event Grid | `EventGrid Data Sender` | Custom Topic (`event_grid_topic_id`) |
| Event Hubs | `Azure Event Hubs Data Sender`, `Azure Event Hubs Data Receiver` | 名前空間 (`event_hubs_namespace_id`) |
| Service Bus | `Azure Service Bus Data Sender`, `Azure Service Bus Data Receiver` | 名前空間 (`service_bus_namespace_id`) |
| Queue Storage | `Storage Queue Data Contributor` | Storage アカウント (`queue_storage_account_id`) |

呼び出し元が権限を付与された ID と一致することを確認します。割り当てを調べるには、
Terraform 出力のリソース ID とプリンシパルのオブジェクト ID（Azure で実行する
場合はマネージド ID のオブジェクト ID）を代入します。

```shell
az account show --query "{subscription:name,tenantId:tenantId,user:user.name}" --output table
MESSAGING_SCOPE="<resource-ID-from-the-scope-column>"
PRINCIPAL_ID="<calling-principal-object-ID>"
az role assignment list \
  --scope "$MESSAGING_SCOPE" --include-inherited \
  --query "[?principalId=='${PRINCIPAL_ID}'].{role:roleDefinitionName,scope:scope}" \
  --output table
```

実行時の ID がシナリオ実行者と異なる場合、権限を持つ管理者が必要なロールをその
ID に付与してください。管理プレーンの `Owner`/`Contributor` だけでは
データプレーンロールの代わりになりません。反映には数分かかります。認可に失敗する
場合はテナント、エンドポイント、リソースのネットワーク制限も確認してください。

### 記事の機能とコマンドの対応

| 記事の機能 | モジュール | コマンド・シナリオ向けの調整 |
| --- | --- | --- |
| Event Grid: Send a Cloud Event | `scripts.cli_event_grid` | `publish-event`; トピックの入力スキーマを選択 |
| Event Grid: Send Multiple Events | `scripts.cli_event_grid` | `publish-events`; リストを 1 回で送信 |
| Event Grid: Namespace 受信・処理 | — | 対象外: Namespace、namespace topic、pull subscription がない |
| Event Hubs: Send events | `scripts.cli_event_hubs` | `send-events`; 1 つの SDK batch |
| Event Hubs: Receive events | `scripts.cli_event_hubs` | `receive-events`; 上限付き、Blob checkpoint なし |
| Service Bus: Send single message | `scripts.cli_service_bus` | `send-message` |
| Service Bus: Send a list | `scripts.cli_service_bus` | `send-message-list`; リストを 1 回で送信 |
| Service Bus: Send a batch | `scripts.cli_service_bus` | `send-message-batch`; 明示的な SDK batch |
| Service Bus: Receive/complete | `scripts.cli_service_bus` | `receive-messages`; 表示後に complete |
| Queue Storage: Create queue | `scripts.cli_queue_storage` | `create-queue` |
| Queue Storage: Add message | `scripts.cli_queue_storage` | `send-message` |
| Queue Storage: Peek messages | `scripts.cli_queue_storage` | `peek-messages` |
| Queue Storage: Update message | `scripts.cli_queue_storage` | `update-message` |
| Queue Storage: Get queue length | `scripts.cli_queue_storage` | `get-queue-length`; 概算件数 |
| Queue Storage: Receive messages | `scripts.cli_queue_storage` | `receive-messages`; 削除しない |
| Queue Storage: Delete message | `scripts.cli_queue_storage` | `delete-message`; ID と pop receipt を指定 |
| Queue Storage: Delete queue | `scripts.cli_queue_storage` | `delete-queue`; 確認または明示的な `--yes` |

### Event Grid Basic Custom Topic

既定のペイロードで単一または複数（既定は 3 件）のイベントを発行します。既定の
`--schema event-grid` は Terraform の既定値 `EventGridSchema` に対応します。

```shell
uv run --locked python -m scripts.cli_event_grid publish-event
uv run --locked python -m scripts.cli_event_grid publish-events
uv run --locked python -m scripts.cli_event_grid publish-events \
  --subject "samples/orders" --event-type "Sample.OrderCreated" \
  --data '{"orderId":42,"status":"created"}' --data-version "1.0" --count 2
```

Terraform の既定トピックが受け付けるのは `EventGridSchema` だけです。この
トピックに次のコマンドを実行すると、CloudEvent の `source` などのプロパティが
Event Grid イベントのスキーマに適合しないため `BadRequest` で失敗します。

```shell
uv run --locked python -m scripts.cli_event_grid publish-events \
  --schema cloud-event --count 3
```

既定のデプロイでは `--schema` を省略するか、`--schema event-grid` を明示して
ください。CloudEvent を発行するには、先に Terraform シナリオで
`event_grid_input_schema = "CloudEventSchemaV1_0"` を設定し、その構成をトピックへ
適用します。発行 CLI から、デプロイ済みトピックの入力スキーマを選択または変換する
ことはできません。

`--data` は JSON オブジェクトである必要があり、配列やスカラーは指定できません。
`event_grid_input_schema = "CloudEventSchemaV1_0"` でデプロイしたトピックには
`--schema cloud-event` を明示します。`--source` は CloudEvent の source です。

```shell
uv run --locked python -m scripts.cli_event_grid publish-event \
  --endpoint "https://<topic>.<region>-1.eventgrid.azure.net/api/events" \
  --schema cloud-event --source "/samples/orders" \
  --subject "orders/42" --event-type "Sample.OrderCreated" \
  --data '{"orderId":42}'
```

`--data-version` は Event Grid スキーマ用メタデータであり、CloudEvent の
バージョン指定ではありません。`publish-events --count` は全イベントをリストで
1 回だけ送信します。発行結果は `schema`、`count`、`ids` を含む 1 つの JSON
オブジェクトです。`CustomEventSchema` と Namespace のコンシューマー操作
（receive、acknowledge、release、reject、renew lock）は対象外です。シナリオは
Event Grid Namespace ではなく Basic Custom Topic を作成し、イベント
サブスクリプションも作成しません。発行成功だけでは後続の配信先は構成されません。

### Event Hubs

既定ではクイックスタートの 3 イベントを送信します。`--message` を繰り返すと
任意のイベントで 1 つの batch を作成できます。送信結果は `{"sent": N}` です。

```shell
uv run --locked python -m scripts.cli_event_hubs send-events
uv run --locked python -m scripts.cli_event_hubs send-events \
  --fully-qualified-namespace "<namespace>.servicebus.windows.net" \
  --event-hub events --message "First event" --message '{"orderId":42}'
uv run --locked python -m scripts.cli_event_hubs receive-events
uv run --locked python -m scripts.cli_event_hubs receive-events \
  --consumer-group '$Default' --starting-position '-1' \
  --max-events 3 --max-wait-time 10
```

受信の既定値は最大 100 件、アイドルタイムアウト 15 秒です。
`--max-events` は 1～10,000 を指定できます。
`--max-events` 件に達するか、全パーティションを通じて
`--max-wait-time` 秒間イベントが届かなくなると終了し、ペイロードと
パーティション・シーケンスのメタデータを JSON 行で表示した後に受信件数を表示します。
イベントのフィールドは `body`、`partition_id`、`offset`、`sequence_number`、
`enqueued_time` で、最後は 0 件の場合も含めて `{"received": N}` です。
実イベントの受信ごとにタイムアウトをリセットします。コールバックが届かない場合や
パーティションが見つからない場合もタイムアウトします。別のパーティションで受信が
続いていれば、空のパーティションだけを理由に終了しません。
`--starting-position` の既定値は `-1`（保持中のイベントの先頭）、
`--consumer-group` の既定値は `$Default` です。受信は非破壊で、
**checkpoint は保存しません**。同じ開始位置で再実行すると保持中のイベントを
再読込することがあります。シナリオは Blob container と
`Storage Blob Data Contributor` を用意しないため、記事の Blob checkpoint
store は意図的に対象外としています。

最初のタイムアウトには認証、接続、パーティション探索の時間も含まれます。
短すぎると保持中のイベントを受信する前に `{"received": 0}` で終了するため、
`--max-wait-time 30 --starting-position '-1'` で再実行し、名前空間、Event Hub 名、
コンシューマーグループ、受信の RBAC を確認してください。`@latest` は受信側の
接続時点で既に存在するイベントを読みません。シェルで export 済みの環境変数は
`.env` より優先され、明示的な CLI オプションはその両方より優先されます。

### Service Bus Queue

3 種類の送信コマンドで異なる SDK 送信形式を確認できます。`--message` で本文、
`--count` で list/batch の件数（既定は 3 件）を変更します。
受信の既定値は最大 10 件、待機時間 5 秒です。

```shell
uv run --locked python -m scripts.cli_service_bus send-message
uv run --locked python -m scripts.cli_service_bus send-message-list
uv run --locked python -m scripts.cli_service_bus send-message-batch
uv run --locked python -m scripts.cli_service_bus send-message --message "Hello queue"
uv run --locked python -m scripts.cli_service_bus send-message-list --message "Order" --count 2
uv run --locked python -m scripts.cli_service_bus send-message-batch --message "Order" --count 2
uv run --locked python -m scripts.cli_service_bus receive-messages
uv run --locked python -m scripts.cli_service_bus receive-messages \
  --fully-qualified-namespace "<namespace>.servicebus.windows.net" \
  --queue queue --max-messages 5 --max-wait-time 10
```

`send-message-list` はリストを `send_messages` に 1 回渡します。
`send-message-batch` は `ServiceBusMessageBatch` に追加し、容量を超えた場合は
メッセージを黙って欠落させず明示的に報告します。その場合は `--count` または本文
サイズを減らしてください。受信は件数・待機時間で制限されます。送信は
`{"sent": N}`、受信は各メッセージの `body`、`message_id`、メタデータを含む
JSON オブジェクトを表示した後、`{"received": N}` を表示します。
各オブジェクトはインデント付きの複数行ではなく 1 行で出力されます。
正常に表示した各メッセージは **complete** され、キューから削除されます。
Event Hubs や Queue Storage の受信とは異なります。シナリオは Topic と
Subscription もデプロイしますが、この CLI は Queue のみを対象とします。

### Queue Storage のライフサイクル（検証用キュー）

例では一意な検証用（scratch）キューを使用します。削除時も含め、`--queue` で
`.env` の Terraform 管理下のキューを上書きします。Azure Storage の有効な
キュー名（小文字英数字とハイフン）を使用してください。`.env` にエンドポイントを
設定した状態で、既定のメッセージと上限を試します。

```shell
SCRATCH_QUEUE="messaging-cli-scratch-$(date +%s)"
uv run --locked python -m scripts.cli_queue_storage create-queue --queue "$SCRATCH_QUEUE"
uv run --locked python -m scripts.cli_queue_storage send-message --queue "$SCRATCH_QUEUE"
uv run --locked python -m scripts.cli_queue_storage peek-messages --queue "$SCRATCH_QUEUE"
uv run --locked python -m scripts.cli_queue_storage get-queue-length --queue "$SCRATCH_QUEUE"
uv run --locked python -m scripts.cli_queue_storage receive-messages --queue "$SCRATCH_QUEUE"
```

本文、非表示時間（秒）、取得件数を変更できます。peek/receive の既定の取得件数は
1 件、receive の既定の非表示時間は 30 秒です。send/update の非表示時間は
既定で 0 秒です。非表示時間はメッセージの残りの有効期間より短くしてください
（メッセージの既定の有効期間は 7 日です）。peek/receive の
`--max-messages` は **1～32** です。

```shell
uv run --locked python -m scripts.cli_queue_storage send-message \
  --queue "$SCRATCH_QUEUE" --message "Please update me" --visibility-timeout 0
uv run --locked python -m scripts.cli_queue_storage peek-messages \
  --queue "$SCRATCH_QUEUE" --max-messages 2
uv run --locked python -m scripts.cli_queue_storage receive-messages \
  --queue "$SCRATCH_QUEUE" --max-messages 2 --visibility-timeout 120
```

send、receive、update は、後続操作に必要な `id` と `pop_receipt` を
JSON で返します。send/update は 1 つのメタデータオブジェクト、
receive は各メッセージのメタデータを含む集約オブジェクト
`{"received": N, "messages": [...]}` を出力します。空の受信結果は
`{"received": 0, "messages": []}` です。JSONL として処理できるように、
各結果は 1 行で完結します。peek は pop receipt を含まないメタデータの配列を返し、
可視性を変更せずメッセージを消費しません。receive は
指定時間だけ非表示にしますが、**削除はしません**。削除しなければ再び表示されます。
キュー長はサービスの概算件数であり、現在表示されるメッセージだけの件数ではありません。

最新の受信結果から ID と対応する pop receipt をコピーし、非表示時間内に
更新します。

```shell
MESSAGE_ID="<message-ID-from-receive>"
POP_RECEIPT="<matching-pop-receipt-from-receive>"
uv run --locked python -m scripts.cli_queue_storage update-message \
  --queue "$SCRATCH_QUEUE" --message-id "$MESSAGE_ID" --pop-receipt "$POP_RECEIPT" \
  --message "Updated content" --visibility-timeout 120
```

更新は **新しい pop receipt** を返します。古い値を置き換えてください。
再受信でも receipt が変わるため、同じメッセージの更新・削除には常に最新の値を
使用します。

```shell
POP_RECEIPT="<new-pop-receipt-from-update>"
uv run --locked python -m scripts.cli_queue_storage delete-message \
  --queue "$SCRATCH_QUEUE" --message-id "$MESSAGE_ID" --pop-receipt "$POP_RECEIPT"
# 検証用キューのみを削除（対話確認あり）:
uv run --locked python -m scripts.cli_queue_storage delete-queue --queue "$SCRATCH_QUEUE"
# 非対話クリーンアップの場合の代替コマンド（明示的な同意）:
uv run --locked python -m scripts.cli_queue_storage delete-queue --queue "$SCRATCH_QUEUE" --yes
```

削除を拒否すると Azure API を呼ばずにキャンセルします。非対話実行でのキュー
削除には `--yes` が必要です。キュー削除は残りのメッセージもすべて削除するため、
上記クリーンアップで検証用キューを Terraform 管理下のキューに置き換えないで
ください。`--endpoint` で Queue サービスのエンドポイントを上書きできます。
各コマンドの `--help` で全オプションと既定値を確認できます。

## Azure 可観測性 CLI

以下の短い実習は
[`ks6088ts/template-terraform` の `infra/scenarios/azure_observability`](https://github.com/ks6088ts/template-terraform/tree/main/infra/scenarios/azure_observability)
で作成済みのリソースを使用します。シナリオの機能は**すべて既定で無効**です。
必要なリソースだけをそちらのリポジトリの `features.azure_monitor`、
`features.log_analytics`、`features.application_insights`、
`features.network_watcher` で有効化してください。Application Insights
には Log Analytics も必要です。`features.activity_log` は診断エクスポートを
構成し、こちらも `features.log_analytics` が必要です。
ライブの Activity Log API の有効化ではありません。
Azure Monitor Workspace は **マネージド
Prometheus** 用であり、Log Analytics とは別です。シナリオは Prometheus
コレクターを作成しないため、別途収集を構成していなければ `up` が空でも正常です。
Network Watcher は別のリソースグループに存在する場合があります。
サブスクリプションの Activity Log はワークスペースとは独立して存在します。

### ID と読み取り権限の設定

Terraform のチェックアウトで非シークレットの出力を確認します。

```shell
terraform -chdir=infra/scenarios/azure_observability output
# 引用符なしで単一の値を取得:
terraform -chdir=infra/scenarios/azure_observability output -raw azure_monitor_id
```

この Python リポジトリでは `.env` が未作成の場合のみテンプレートをコピーし、
下表の ID を設定して認証します。

```shell
test -f .env || cp .env.template .env
az login
az account show --query '{subscription:id,tenant:tenantId}' --output table
```

| Terraform 出力 / 取得元 | リソース / 値 | `.env` 変数 | CLI による上書き |
| --- | --- | --- | --- |
| `azure_monitor_id` | Azure Monitor Workspace の ARM ID (`Microsoft.Monitor/accounts`) | `AZURE_MONITOR_ID` | `--resource-id` |
| `log_analytics_workspace_id` | Log Analytics の workspace/customer **GUID**（ARM ID の `log_analytics_id` ではない） | `AZURE_LOG_ANALYTICS_WORKSPACE_ID` | `--workspace-id` |
| `application_insights_id` | Application Insights の ARM ID (`Microsoft.Insights/components`) | `AZURE_APPLICATION_INSIGHTS_ID` | `--resource-id` |
| `network_watcher_id` | Network Watcher の ARM ID (`Microsoft.Network/networkWatchers`) | `AZURE_NETWORK_WATCHER_ID` | `--resource-id` |
| `az account show --query id --output tsv` | サブスクリプション GUID（シナリオ出力なし） | `AZURE_SUBSCRIPTION_ID` | `--subscription-id` |
| `resource_group_name` または既存 Watcher の実際のグループ | 任意のグループフィルター。空ならサブスクリプション全体 | `AZURE_RESOURCE_GROUP` | `--resource-group` |

ARM ID は `/subscriptions/<id>/resourceGroups/<group>/providers/` で始まり、
ワークスペース GUID は `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` 形式です。
無効な機能の出力は null または未出力です。`null` を設定せず、対象の実習を省略してください。
非シークレットの CLI オプションは環境変数 / `.env` を上書きします。各コマンドの
`--help` も参照してください。読み取りには `DefaultAzureCredential` を使用し、
ローカルでは `az login` の認証情報を利用できます。他の構成済み認証情報が
優先される場合もあります。

管理者に依頼し、実際に実行する ID に次のアクセス権を付与してください。

| 操作 | 必要な権限とスコープ |
| --- | --- |
| ワークスペース / Watcher のメタデータ取得 | 対象リソースの管理プレーン `Reader`。Watcher 一覧には選択したリソースグループ / サブスクリプションのアクセス権が必要 |
| PromQL クエリ | **Azure Monitor Workspace** の `Monitoring Data Reader` |
| Log Analytics ワークスペースへのクエリ | Log Analytics ワークスペースの `Log Analytics Reader` |
| Application Insights のリソース中心クエリ | ワークスペースのアクセスモードがリソース権限を許可する場合、Application Insights コンポーネントの `Reader`。それ以外では保存先ワークスペースの `Log Analytics Reader` などのクエリ権限が必要 |
| サブスクリプション Activity Log | Activity Log 読み取り権限を含む、サブスクリプションスコープの `Reader` |

PromQL の `Monitoring Data Reader` は汎用の `Monitoring Reader` とは別です。
[Prometheus API アクセス](https://learn.microsoft.com/azure/azure-monitor/metrics/prometheus-api-promql)、
[Log Analytics のアクセス管理](https://learn.microsoft.com/azure/azure-monitor/logs/manage-access)、
[Activity Log](https://learn.microsoft.com/azure/azure-monitor/platform/activity-log)
を参照してください。読み取り専用の Watcher コマンドについては
[Network Watcher の概要](https://learn.microsoft.com/azure/network-watcher/network-watcher-overview)
も参照してください。パケットキャプチャや接続テストは開始しません。
403 の場合は ID / テナント、リソースのスコープ、
ロール反映待ち、ネットワーク制限を確認します。これらの CLI はロール付与、
コレクターのデプロイ、診断設定の書き込みを行いません。

### 5 種類の対象を読み取る

利用可能で読み取り権限のある対象だけを実行します。`AzureActivity` の実習には
`features.activity_log` と `features.log_analytics` の両方を有効にして、
選択したワークスペースへのエクスポートを構成する必要があります。
ライブの Activity Log API にはシナリオの機能フラグは不要です。

```shell
# マネージド Prometheus: ワークスペースを確認し、即時クエリを実行
uv run --locked python -m scripts.cli_azure_monitor show-workspace
uv run --locked python -m scripts.cli_azure_monitor query-prometheus --query 'up'

# Log Analytics: 任意のクエリ入力ではなく固定 AzureActivity KQL
uv run --locked python -m scripts.cli_log_analytics query-logs --hours 24 --limit 100
uv run --locked python -m scripts.cli_log_analytics summarize-activity --hours 24 --limit 100

# ワークスペースベース Application Insights: 読み取りに接続文字列は不要
uv run --locked python -m scripts.cli_application_insights query-telemetry \
  --table AppRequests --hours 24 --limit 100

# シナリオのリソースグループを仮定せず、サブスクリプション全体で探索
uv run --locked python -m scripts.cli_network_watcher list-watchers
uv run --locked python -m scripts.cli_network_watcher show-watcher

# サブスクリプションの管理プレーン履歴: Log Analytics クエリとは別
uv run --locked python -m scripts.cli_activity_log list-events --hours 24 --limit 100
uv run --locked python -m scripts.cli_activity_log summarize-events --hours 24 --limit 100
```

`list-watchers`、`list-events`、`summarize-events` は
`--resource-group "<group>"`（または `AZURE_RESOURCE_GROUP`）で対象を絞れます。
サブスクリプション全体で探索する場合は、この環境変数を空にしてください。
たとえば Watcher の設定を明示的な ID で上書きできます。

```shell
uv run --locked python -m scripts.cli_network_watcher show-watcher \
  --resource-id "/subscriptions/<subscription-id>/resourceGroups/<watcher-group>/providers/Microsoft.Network/networkWatchers/<watcher-name>"
```

ログ / テレメトリのクエリと Activity Log コマンドには `--hours 1..168`
（既定 `24`）、`--limit 1..1000`（既定 `100`）を指定できます。
`query-logs` と `query-telemetry` は返す行数を制限します。
Log Analytics の `summarize-activity` は**時間範囲内の一致する全行**を集計後、
返すグループ数を制限します。一方、ライブ Activity Log の `summarize-events`
は最大 `--limit` 件のイベントのみを集計し、その時間範囲内の全イベント数では
ありません。いずれも期間無制限の総数ではありません。
Log Analytics の `AzureActivity` は
**サブスクリプションの診断設定で別途エクスポートされた** Activity Log のみを
含みます。ライブの Activity Log API とは異なります。エクスポート未設定なら、
`list-events` が成功してもテーブルは未作成または空です。操作のない
サブスクリプションではイベント自体がない場合もあります。シナリオの
`activity_log_id` はエクスポート用の診断設定 ID であり、サブスクリプション ID
やクエリ先ワークスペースではありません。
[Activity Log のエクスポート](https://learn.microsoft.com/azure/azure-monitor/platform/activity-log#export-activity-log)
を参照してください。

### Application Insights へ送信して確認する

この実習のみデータを送信し、取り込み料金が発生する場合があります。シナリオは
Application Insights の接続文字列を**出力しません**。リソースの Azure portal
**概要**ページから安全に取得し、ローカルの Git 無視対象 `.env` の
`APPLICATIONINSIGHTS_CONNECTION_STRING` に設定してください。またはローカルの
シークレット管理手順で環境変数を設定します。テンプレートは空のままにします。
ソース、シェルの引数 / 履歴、スクリーンショット、ログ、共有出力へ値を
貼り付けないでください。接続文字列の CLI フラグはありません。
[接続文字列](https://learn.microsoft.com/azure/azure-monitor/app/connection-strings)と
[Python OpenTelemetry クイックスタート](https://learn.microsoft.com/azure/azure-monitor/app/opentelemetry-enable?tabs=python)
を参照してください。

```shell
uv run --locked python -m scripts.cli_application_insights emit-telemetry --count 10
```

`--count` は `1..100`（既定 `10`）です。サンプルの server span、
相関ログ、メトリック増分を送信し、エクスポーターを flush して、一意の `run_id`
を表示します。flush の失敗は明示されますが、成功しても取り込み完了を
**保証しません**。取り込みを待ち、最近のリクエストで実行を探してから、
表示された UUID で各シグナルを絞り込みます。

```shell
uv run --locked python -m scripts.cli_application_insights query-telemetry \
  --table AppRequests --hours 1 --limit 100
RUN_ID="<emit-telemetry-が表示した-run_id-UUID>"
uv run --locked python -m scripts.cli_application_insights query-telemetry \
  --table AppRequests --run-id "$RUN_ID" --hours 1 --limit 100
uv run --locked python -m scripts.cli_application_insights query-telemetry \
  --table AppTraces --run-id "$RUN_ID" --hours 1 --limit 100
uv run --locked python -m scripts.cli_application_insights query-telemetry \
  --table AppMetrics --run-id "$RUN_ID" --hours 1 --limit 100
```

指定できるテーブルは `AppRequests`、`AppTraces`、`AppMetrics`、
`AppDependencies` の 4 種類のみです。最後のテーブルは既存の依存関係テレメトリを
検索できますが、この送信コマンドは dependency span を生成しません。
`--run-id` は省略可能ですが、
指定する場合は UUID が必要です。メトリックは集約されるため、増分との比較には
行数ではなくカウンター値 / 集約値を使います。シナリオの Application Insights
サンプリングは既定 **25%** です。Azure Monitor OpenTelemetry distro の
クライアント側サンプリングは別設定です（この送信コマンドは明示的に
`always_on` を使用します）。サンプリング後の span / ログ行数や
上限付きクエリの結果が `--count` と一致するとは限りません。実行が見つからない
場合は時間範囲内で待って再試行し、サンプリング、送信先とクエリ先ワークスペース、
RBAC、取り込み / ネットワーク障害を確認してください。無制限に再送しないでください。
[サンプリング](https://learn.microsoft.com/azure/azure-monitor/app/opentelemetry-sampling)と
[取り込み遅延](https://learn.microsoft.com/azure/azure-monitor/logs/data-ingestion-time)
も参照してください。終了後はローカルの接続文字列を削除します。
ローカル設定の削除だけでは Azure リソースの課金は停止しません。

## Docker 開発

```shell
# Docker イメージをビルド
make docker-build

# http://127.0.0.1:8000/ で FastAPI を実行（停止は Ctrl+C）
make docker-run

# イメージの起動と HTTP ルートを確認して停止
make docker-smoke-test

# Docker コンテナ内で CI テストを実行
make ci-test-docker
```

Dockerfile は `serve-container-apps` を `0.0.0.0:8000` で起動します。
Container Apps の ingress はポート 8000 を対象にできます。Compose を使用する場合、
未作成であれば `.env.template` から `.env` を作成して次を実行します。

```shell
docker compose up --build
```

Compose はファイルサーバーで上書きせず、イメージと同じ FastAPI 起動方法を使用します。

Docker CI ターゲットは lint、ビルド、スキャンを実行し、起動中のイメージへ HTTP
リクエストを送信します。現在 Trivy スキャンは脆弱性を報告してもビルドを失敗させません。
重大度によるブロックを有効にする前に検出内容を確認してください。

## ドキュメント開発

ドキュメントは Material for MkDocs と `mkdocs-static-i18n` を使用して英語と
日本語のページを公開します。

```shell
# 両言語をビルド
make ci-test-docs

# ライブリロード付きでローカル配信
make docs-serve
```

Zensical へ移行する場合は同等の多言語出力が必要です。Zensical では未対応の
MkDocs プラグインは実行されません。
