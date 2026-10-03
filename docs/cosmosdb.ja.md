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
