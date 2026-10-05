# Azure Cosmos DB

Azure Cosmos DB for NoSQL に、サンプルデータを保存・取得します。
使う CLI は `scripts.cli_cosmosdb` です。
[Python クイックスタート](https://learn.microsoft.com/ja-jp/azure/cosmos-db/quickstart-python)の操作を、
コマンドで試せます。

## 1. 接続先とアクセス権を用意する

[開発環境と Azure の共通準備](scripts.md)を済ませ、Cosmos DB for NoSQL の
アカウントを用意します。`.env` に実際のエンドポイントを設定します。

```dotenv
AZURE_COSMOS_DB_ENDPOINT=https://<account-name>.documents.azure.com:443/
AZURE_COSMOS_DB_DATABASE=cosmicworks
AZURE_COSMOS_DB_CONTAINER=products
```

実行 ID には、データベース・コンテナーの作成と、データの書き込み・読み取り・クエリに
必要な Cosmos DB のアクセス権を付与してください。認証には `DefaultAzureCredential` を使います。
Cosmos DB ネイティブのデータプレーン RBAC を使う場合、ロール割り当てのスコープが
設定したデータベースを含むようにしてください。たとえばスコープが `/dbs/playground` なら、
`AZURE_COSMOS_DB_DATABASE=playground` が必要です。一致しない場合、SDK は
`Microsoft.DocumentDB/databaseAccounts/readMetadata` に対する 403 を返します。

**検証用のデータを使ってください。** 各コマンドは必要に応じてデータベースと
コンテナーを作成します。`upsert-item` は、同じ ID とカテゴリのデータを上書きします。

| 項目 | 既定値 |
| --- | --- |
| データベース | `cosmicworks` |
| コンテナー | `products` |
| パーティションキー（データを分けるキー） | `/category` |
| アイテム ID | `aaaaaaaa-0000-1111-2222-bbbbbbbbbbbb` |
| カテゴリ | `gear-surf-surfboards` |

## 2. データを保存する

この Python リポジトリのルートで実行します。

```shell
uv run --locked python -m scripts.cli_cosmosdb upsert-item
```

保存したサーフボードのデータが JSON で表示されます。
内容を指定する場合は、次のように実行します。

```shell
uv run --locked python -m scripts.cli_cosmosdb upsert-item \
  --item-id aaaaaaaa-0000-1111-2222-bbbbbbbbbbbb \
  --category gear-surf-surfboards --name "Yamba Surfboard" \
  --quantity 12 --no-sale
```

## 3. データを読み取る

```shell
uv run --locked python -m scripts.cli_cosmosdb read-item \
  --item-id aaaaaaaa-0000-1111-2222-bbbbbbbbbbbb \
  --category gear-surf-surfboards
```

ID とカテゴリを使って 1 件だけ取得します（ポイント読み取り）。
保存したデータと同じ `id`・`category`・`name` が表示されれば確認完了です。

## 4. カテゴリで検索する

```shell
uv run --locked python -m scripts.cli_cosmosdb query-items \
  --category gear-surf-surfboards
```

指定したカテゴリの結果が JSON 配列で表示されます。
クエリはパラメーター化され、同じパーティション内だけを検索します。

## 設定を変える場合

| 変えたい値 | CLI オプション |
| --- | --- |
| アカウントの URL | `--endpoint` |
| データベース名 | `--database` |
| コンテナー名 | `--container` |
| 新規コンテナーの専用スループット | `--throughput`（RU/s） |

専用スループットは既定では指定しません。サーバーレスや共有スループット構成では、
`--throughput` を省略してください。このオプションは新規コンテナーの作成時だけ使います。

```shell
uv run --locked python -m scripts.cli_cosmosdb --help
uv run --locked python -m scripts.cli_cosmosdb upsert-item --help
```

<a id="task-api"></a>

## Task API の永続化とコンテナー管理

上記の商品 CLI とは別に、Task API は非同期 SDK と **Task 専用の `/id` コンテナー**を使います。
API は database / container を自動作成しません。起動前に以下の管理 CLI で準備します。
account と resource group は作成済みのものを指定してください。
管理コマンドは Azure CLI Core の `az cosmosdb sql` を呼び出すため、Azure CLI と
`az login` 等のサインインが必要です。管理 SDK の追加インストールは不要です。

### 設定と権限

`.env` に非秘密の設定を追加します。

```dotenv
TASK_REPOSITORY=in-memory
AZURE_COSMOS_DB_ENDPOINT=https://<account-name>.documents.azure.com:443/
AZURE_COSMOS_DB_DATABASE=cosmicworks
AZURE_COSMOS_DB_TASK_CONTAINER=tasks
AZURE_COSMOS_DB_ACCOUNT_NAME=<account-name>
AZURE_SUBSCRIPTION_ID=<subscription-uuid>
AZURE_RESOURCE_GROUP=<resource-group-name>
```

- **管理 CLI の実行 ID**: 対象 account の database / container を管理できる Azure RBAC
  （例: Cosmos DB Operator）。データプレーンの Cosmos DB ロールだけでは作成・削除できません。
  Entra ID のデータ SDK で管理すると 403 / substatus 5300 になります。
- **API の実行 ID**: `DefaultAzureCredential` で認証し、対象 database / container の
  メタデータ読み取りと Task CRUD / query を許可する Cosmos DB ネイティブのデータプレーン RBAC
  （例: Cosmos DB Built-in Data Contributor）。API に管理権限は不要です。
- subscription は `--subscription` または `AZURE_SUBSCRIPTION_ID` で必ず指定します。
  `az account set` の既定 subscription へ暗黙に切り替えません。
- 商品用 `AZURE_COSMOS_DB_CONTAINER=products` は Task の保存先・管理先に使いません。
  account 名と endpoint が同じ account を指すことを確認してください。

### 作成・状態確認

```shell
uv run --locked python -m scripts.cli_cosmosdb tasks create-container
uv run --locked python -m scripts.cli_cosmosdb tasks show-container
```

不在の場合だけ database と `/id` コンテナーを作成します。
再実行しても既存の適合するコンテナーは変更せず、
JSON の `database_created` / `container_created` は `false` になります。
partition key が違う場合は失敗し、自動削除・再作成・移行は行いません。
`show-container` は resource ID と partition key 等の管理 metadata を表示し、データは読みません。

`--subscription`、`--resource-group`、`--account-name`、`--database`、`--container` で
設定を上書きできます。専用 RU/s を新規コンテナーに設定する場合だけ
`create-container --throughput 400` 等を指定してください。
省略時は throughput 引数を az に渡さず、serverless / database 共有 throughput を利用できます。
既存コンテナーの throughput は変更しません。リソース作成には料金が発生する場合があります。

### API を起動して確認

```shell
uv run --locked python -m scripts.template serve-container-apps --repository cosmosdb
# Functions の場合:
# uv run --locked python -m scripts.template serve-functions --repository cosmosdb
```

別ターミナルで Task を作成し、同じ保存先で API を停止・再起動しても残ることを確認します。

```shell
curl --fail -H 'Content-Type: application/json' \
  -d '{"title":"Persist this Task"}' http://127.0.0.1:8000/tasks
curl --fail http://127.0.0.1:8000/tasks
```

`TASK_REPOSITORY=cosmosdb` なら起動オプションを省略できます。
明示 CLI 引数が環境変数・dotenv より優先され、既定は `in-memory` です。
API 起動時に接続・コンテナー存在・partition を検証し、失敗した起動を成功に見せません。
API 実行中の保存障害は `{"detail":"Task storage is unavailable"}` と HTTP 503、
ログで通知します。全件一覧は cross-partition query なので RU とメモリーを消費します。
ページング、ETag 競合検出はなく、更新は後勝ちです。HTTP 認証も追加していません。

<a id="task-api-startup-troubleshooting"></a>

### トラブルシュート: Cosmos DB を選ぶと API が起動しない

次の起動コマンドが失敗し、ログに以下が出る場合の確認手順です。
`serve-container-apps` はローカルで Uvicorn を起動するコマンドで、
Azure Container Apps へのデプロイは行いません。

```shell
uv run --locked python -m scripts.template serve-container-apps --repository cosmosdb
```

```text
Task storage lifespan failed (CosmosResourceNotFoundError, status=404)
...
TaskRepositoryError: Task storage is unavailable
ERROR:    Application startup failed. Exiting.
```

この **Cosmos DB の 404** は、起動時に参照した database / container 等のリソースが
見つからないことを示します。HTTP API の `/` が 404 を返すこととは別の問題です。
`Task storage is unavailable` だけでは原因を特定できないため、直前の例外名と status も確認します。
API はリソースを自動作成せず、database と Task コンテナーを読み取ってから起動します。

たとえば `.env` に `AZURE_COSMOS_DB_DATABASE=playground` と
`AZURE_COSMOS_DB_CONTAINER=products` があり、database 内に `products` と `documents` しかない場合、
商品 CLI が動いていても Task API は起動できません。
`AZURE_COSMOS_DB_TASK_CONTAINER` が未指定なら、API は既定の `playground/tasks` を参照します。
`AZURE_COSMOS_DB_CONTAINER` を設定しても Task の保存先は変わりません。

#### 1. API が実際に使う接続先を確認する

リポジトリルートで実行します。以下は接続先の非秘密の項目だけを表示し、
資格情報や他のサービスの設定は出力しません。

```shell
uv run --locked python -c '
from template_azure_python.settings import get_azure_settings
settings = get_azure_settings().cosmos_db
print(f"endpoint={settings.endpoint}")
print(f"database={settings.database}")
print(f"task_container={settings.task_container}")
'
```

| Task API の設定 | 未指定時 |
| --- | --- |
| `AZURE_COSMOS_DB_ENDPOINT` | 必須。未設定なら起動前の入力検証で失敗 |
| `AZURE_COSMOS_DB_DATABASE` | `cosmicworks` |
| `AZURE_COSMOS_DB_TASK_CONTAINER` | `tasks`。パーティションキーは `/id` が必要 |

OS 環境変数は `.env` より優先されます。表示が `.env` と違う場合は、
同名の環境変数が export されていないか確認してください。
既存の `.env` を `.env.template` で上書きせず、必要な設定だけを修正します。

#### 2. Azure 上のアカウント・database・コンテナーを確認する

Azure CLI にサインインし、以下の値を自分の環境に置き換えます。
`COSMOS_ACCOUNT` は手順 1 の endpoint に対応するアカウント名です。
database / container は手順 1 の表示と一致させてください。
以下は `playground/tasks` を調べる例です。
**`az` は `.env` を読み込まない**ため、このシェル変数は別途指定します。

```shell
az login
SUBSCRIPTION_ID="<subscription-uuid>"
COSMOS_ACCOUNT="<account-name>"
COSMOS_DATABASE="playground"
TASK_CONTAINER="tasks"

az cosmosdb list --subscription "$SUBSCRIPTION_ID" \
  --query "[?name=='$COSMOS_ACCOUNT'].{account:name,resourceGroup:resourceGroup,endpoint:documentEndpoint}" \
  --output table
```

表示された endpoint が手順 1 と同じアカウントを指すことを確認し、
その `resourceGroup` を次の変数に設定します。結果が空なら subscription とアカウント名を見直します。
`AZURE_RESOURCE_GROUP` に監視サービス等の別の resource group が設定されていても、
**Task 管理コマンドには Cosmos DB アカウントが所属する resource group が必要**です。

```shell
COSMOS_RESOURCE_GROUP="<cosmos-account-resource-group>"

az cosmosdb sql database show --subscription "$SUBSCRIPTION_ID" \
  --resource-group "$COSMOS_RESOURCE_GROUP" --account-name "$COSMOS_ACCOUNT" \
  --name "$COSMOS_DATABASE" --query "resource.id" --output tsv

az cosmosdb sql container list --subscription "$SUBSCRIPTION_ID" \
  --resource-group "$COSMOS_RESOURCE_GROUP" --account-name "$COSMOS_ACCOUNT" \
  --database-name "$COSMOS_DATABASE" \
  --query "[].{container:resource.id,partition_key:resource.partitionKey.paths}" \
  --output json
```

database の確認が成功してからコンテナーを一覧します。
確認コマンドが失敗した場合は Azure CLI のエラーを読み、
サインイン・権限・接続先の誤りと、リソースの不在を区別してください。
失敗を「リソースが存在しない」と決めつけて作成しないでください。

#### 3. 正しい接続先に不足している Task コンテナーを作成する

対象を確認してから、既存の Task 管理 CLI を使います。
以下の明示オプションは `.env` の管理設定より優先されるため、
account 名が未設定、または resource group が別サービス用でも対象を指定できます。
リソース作成には料金が発生する場合があります。

```shell
uv run --locked python -m scripts.cli_cosmosdb tasks create-container \
  --subscription "$SUBSCRIPTION_ID" --resource-group "$COSMOS_RESOURCE_GROUP" \
  --account-name "$COSMOS_ACCOUNT" \
  --database "$COSMOS_DATABASE" --container "$TASK_CONTAINER"

uv run --locked python -m scripts.cli_cosmosdb tasks show-container \
  --subscription "$SUBSCRIPTION_ID" --resource-group "$COSMOS_RESOURCE_GROUP" \
  --account-name "$COSMOS_ACCOUNT" \
  --database "$COSMOS_DATABASE" --container "$TASK_CONTAINER"
```

既存 database に不足コンテナーだけを作成した場合、
作成結果は `database_created: false`、`container_created: true` です。
`show-container` の `database` / `container` が手順 1 と一致し、
`partition_key` が `["/id"]` であることを確認します。
同じ対象へ再実行すると、既存の適合リソースは変更されず両方の作成フラグが `false` になります。

`products` / `documents` を削除・改名したり、Task API を商品用 `/category` コンテナーへ
向けたりする必要はありません。既存コンテナーの partition key が違う場合、
管理 CLI は失敗します。データを守るため、専用の別コンテナーを用意し、
`AZURE_COSMOS_DB_TASK_CONTAINER` もその名前に合わせてください。

**管理コマンドのオプションは API の起動設定には引き継がれません。**
endpoint / database / Task コンテナーの名前を環境変数または `.env` でも一致させます。
以後、管理オプションを省略したい場合は `AZURE_COSMOS_DB_ACCOUNT_NAME`、
`AZURE_SUBSCRIPTION_ID`、`AZURE_RESOURCE_GROUP` も正しい値に設定してください。
account 名は endpoint から自動補完されません。他のサービスで同じ resource group 設定を
使う場合は、共通設定を変更せず、上記の明示オプションで対象を指定します。

#### 4. 同じ起動コマンドで HTTP 応答を確認する

```shell
uv run --locked python -m scripts.template serve-container-apps --repository cosmosdb
```

`Application startup complete.` が出たら、別ターミナルで確認します。

```shell
curl --fail --silent --show-error --write-out '\nHTTP %{http_code}\n' \
  http://127.0.0.1:8000/tasks
```

HTTP 200 と Task の JSON 配列が返れば確認完了です。
新規の空コンテナーでは `[]`、既存データがある場合はその Task 一覧が返ります。
検証後は起動したターミナルで `Ctrl+C` を押して停止します。
Functions でも同じ保存先を使います。`serve-functions --repository cosmosdb` で起動した場合、
確認 URL のポートは既定の `7071` に変更してください。

#### 別のエラーが出る場合

| 症状 | 次に確認すること |
| --- | --- |
| `Missing option '--account-name'` / `--subscription` / `--resource-group` | 管理 CLI 用の設定が不足。手順 3 の明示オプションを指定する。endpoint だけでは管理先を解決できない |
| 管理 CLI が非ゼロで終了する | `az login`、subscription、Cosmos DB の resource group、管理プレーン RBAC。手順 2 の `az` コマンドで詳細を確認し、失敗を不在と扱わない |
| API 起動ログが status 403 | API の実行 ID、Cosmos DB ネイティブのデータプレーン RBAC と database / container のスコープ。管理 CLI の成功だけでは API の権限を確認できない |
| `Task container must use partition key /id` | 接続先のコンテナーが Task 用ではない。既存データを削除せず、`/id` の専用コンテナーと設定を用意する |
| 作成後も Cosmos DB の 404 が続く | 手順 1 の実効設定と作成結果の account / database / container を再比較。環境変数の上書きや、管理 CLI と API が別アカウントを指していないか確認 |

### 停止後に削除

**すべての Task が削除されます。** API を停止して、表示される対象を確認してください。

```shell
uv run --locked python -m scripts.cli_cosmosdb tasks delete-container
# CI 等の非対話実行では、明示的に承認:
uv run --locked python -m scripts.cli_cosmosdb tasks delete-container --yes
```

確認を拒否すれば `cancelled: true`、削除完了を確認できれば `deleted: true` を返します。
database と account は削除しません。不存在・権限不足・未サインイン・az 未導入・timeout・
不正 JSON は失敗として通知します。入力エラーは終了コード 2、操作失敗は 1 です。
削除前にも `/id` を検証し、商品用の `/category` 等のコンテナーは削除を拒否します。
database 作成後に container 作成が失敗した場合、部分完了を通知して database を残します。
`show-container` と Azure portal で状態を確認し、原因を解消して再実行してください。
この CLI は schema / container / throughput の migrate、database 削除、account 作成を提供しません。

管理操作の背景は Microsoft の
[Entra ID で禁止される非データ操作](https://learn.microsoft.com/azure/cosmos-db/troubleshoot-forbidden#nondata-operations-arent-allowed)
を参照してください。
