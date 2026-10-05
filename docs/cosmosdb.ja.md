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
