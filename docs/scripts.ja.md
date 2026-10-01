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
- Microsoft Foundry サンプルと既存 Azure リソースへの発行用の
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
