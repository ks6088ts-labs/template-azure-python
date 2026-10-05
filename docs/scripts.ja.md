# ローカル開発

開発環境を整え、API を起動し、変更をテストする手順です。
ローカルの FastAPI アプリは Azure に接続せずに動かせます。
以下のコマンドは、すべてリポジトリのルートで実行します。

## 必要なツール

最初は Python・uv・Make があれば始められます。追加のツールは用途に応じて用意します。

| ツール | 必要になる場面 |
| --- | --- |
| [Python 3.10+](https://www.python.org/downloads/) | すべての Python コマンド。CI は 3.10～3.14 でテスト |
| [uv 0.12.19](https://docs.astral.sh/uv/getting-started/installation/) | 依存関係の管理とコマンド実行 |
| [GNU Make](https://www.gnu.org/software/make/) | `make` コマンド |
| `curl` | API の応答確認 |
| [actionlint](https://github.com/rhysd/actionlint) | `make lint` と `make ci-test`。CI は v1.7.12 を使用 |
| [Docker](https://docs.docker.com/get-docker/) | Docker / Compose の実行 |
| [Azure Functions Core Tools v4](https://learn.microsoft.com/azure/azure-functions/functions-run-local) | Functions のローカル実行 |
| [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) | Azure サンプルの認証とデプロイ |

## 1. 開発環境を整える

```shell
make install-deps-dev
```

開発用の依存関係をすべてインストールし、[prek](https://prek.j178.dev/) の
Git hook を設定します。**既存の pre-commit hook は置き換えられます。**
CI は JupyterLab を含まない依存関係セットを使います。

## 2. FastAPI を動かす

### 起動する

```shell
uv run --locked python -m scripts.template serve-container-apps
```

既定の URL は `http://127.0.0.1:8000` です。
停止するには、起動したターミナルで `Ctrl+C` を押します。

### 応答を確認する

別のターミナルで実行します。

```shell
curl http://127.0.0.1:8000/
curl -I http://127.0.0.1:8000/docs
```

最初のコマンドで `{"Hello":"World"}`、次のコマンドで HTTP 200 が返れば正常です。
ブラウザーで <http://127.0.0.1:8000/docs> を開くと、API を操作できます。

### アドレスやポートを変える場合

既定のサーバーを停止してから実行します。

```shell
uv run --locked python -m scripts.template serve-container-apps --host 0.0.0.0 --port 8080
```

この例はすべてのネットワークインターフェイスで待ち受けます。
自分の端末だけで使う場合は `--host 127.0.0.1` を指定してください。

## 3. Functions で動かす場合

**追加で必要なもの**: Azure Functions Core Tools v4。
FastAPI と同じアプリを、ローカルの Functions ホストで動かします。

### ローカル設定を用意する

未作成の場合だけコピーします。

```shell
test -f local.settings.json || cp local.settings.json.example local.settings.json
```

この HTTP 専用サンプルは `AzureWebJobsStorage` が空でも動きます。
ストレージのヘルス警告を解消するには、Azurite を起動し、この設定を
`UseDevelopmentStorage=true` に変更します。他のトリガーには有効なストレージ接続が必要です。

### 起動して確認する

```shell
uv run --locked python -m scripts.template serve-functions
```

別のターミナルで実行します。

```shell
curl http://127.0.0.1:7071/
curl -I http://127.0.0.1:7071/docs
```

`{"Hello":"World"}` と HTTP 200 が返れば正常です。
別のポートを使う場合は、起動コマンドに `--port 7072` などを付けます。

### 公開時の注意

- `function_app.py` が同じ FastAPI アプリを `AsgiFunctionApp` で読み込みます。
  [Azure のサンプル](https://github.com/Azure-Samples/fastapi-on-azure-functions)と同じ構成です。
- `host.json` で `/api` の接頭辞を外しているため、URL は `/` と `/docs` です。
- HTTP トリガーは**認証なし**です。機密データを扱う前にアクセス制御を追加してください。
- Azure ではランタイムが `function_app.py` を直接読み込みます。この CLI はローカル専用です。
- `.env` と `local.settings.json` は発行・Docker ビルドから除外されます。
  公開手順は[デプロイガイド](deployment.md)を参照してください。

## 4. 変更を確認する

目的に合うコマンドを選びます。すべてを毎回実行する必要はありません。

| 目的 | コマンド |
| --- | --- |
| 利用できる Make コマンドを表示 | `make` |
| テストを実行 | `make test` |
| Git hook のチェックを実行 | `make hooks-check` |
| コード・型・GitHub Actions の設定をチェック | `make lint` |
| 依存関係の準備、書式・lint・テストをまとめて実行 | `make ci-test` |
| JupyterLab を起動 | `make jupyterlab` |

`make lint` は [zizmor](https://zizmor.sh/) をオフラインで実行し、
重大度 high の GitHub Actions の問題を検出すると失敗します。
低い重大度も確認するには `uv run --locked zizmor --offline .` を実行します。

## Docker で動かす場合

Docker を起動してから、イメージをビルドします。

```shell
make docker-build
```

サーバーを起動します。URL は `http://127.0.0.1:8000`、停止は `Ctrl+C` です。

```shell
make docker-run
```

Dockerfile は `serve-container-apps` を `0.0.0.0:8000` で起動します。
`make docker-run` はホスト側のポートを `127.0.0.1` に限定します。

### イメージを検証する

| 確認内容 | コマンド |
| --- | --- |
| コンテナーを起動し、`/` と `/docs` を確認して停止 | `make docker-smoke-test` |
| Dockerfile の lint、ビルド、スキャン、起動確認をまとめて実行 | `make ci-test-docker` |

スモークテストは自分でコンテナーを起動するため、`make docker-run` の実行中でなくても使えます。
Trivy のスキャンは、現在は脆弱性を報告してもビルドを失敗させません。

### Compose を使う

```shell
test -f .env || cp .env.template .env
docker compose up --build
```

Compose も同じ FastAPI アプリを起動します。

ローカルから Azure のライブ監視を確認する場合は、
[Live Metrics の確認手順](monitoring.md#api-live-metrics)を参照してください。
Compose は `.env` をコンテナーへ渡し、`PROJECT_NAME` は `hello` に上書きします。
現在のポート指定は全インターフェースへ公開するため、ローカルだけに限定したい場合は
`compose.yml` のポートを `127.0.0.1:8000:8000` に変更します。

## Azure サンプルの共通準備

ローカルから OpenTelemetry のサンプルを送り、Azure portal で保存データを確認する場合は、
[送信・KQL 実行の手順](monitoring.md#5-cli)を参照してください。API の起動は不要です。

Azure サンプルを試す場合だけ、次の準備をします。

1. Azure CLI と、使うサービスのリソースを用意します。
2. `.env` を未作成の場合だけコピーして、使うサービスの設定値を入力します。

   ```shell
   test -f .env || cp .env.template .env
   ```

3. サインインし、対象のサブスクリプションと ID を確認します。

   ```shell
   az login
   az account show --query "{subscription:name,tenantId:tenantId,user:user.name}" --output table
   ```

   対象が違う場合は `az account set --subscription "<subscription-id>"` で切り替えます。

4. 各ガイドに従い、実際にコマンドを実行する ID にアクセス権を付与します。

Azure サンプルの設定は **CLI オプション → シェルの環境変数 → `.env` → 既定値**
の順で優先されます。既存の `.env` を上書きせず、必要な変数だけ更新してください。
`.env` は Git の無視対象です。秘密情報をコミットしないでください。

認証には `DefaultAzureCredential` を使います。ローカルでは `az login` の認証情報、
Azure ではマネージド ID を利用できます。他の設定済みの認証情報が優先される場合もあります。
マネージド ID にローカルユーザーの権限は引き継がれません。

アプリの設定は `template_azure_python.settings` が Pydantic Settings で読み込みます。
相対パスの `.env` はカレントディレクトリを基準とし、親ディレクトリは探索しません。
SDK 自体の認証用変数は OS またはホスティング環境へ設定してください。
dotenv の値をプロセスの環境変数へ一括注入することはありません。
設定と SDK の境界は[アーキテクチャ](architecture/index.md)を参照してください。

| サンプル | ガイド |
| --- | --- |
| AI モデル・エージェント | [Microsoft Foundry](foundry.md) |
| データの保存・取得 | [Azure Cosmos DB](cosmosdb.md) |
| イベント・メッセージの送受信 | [メッセージング](messaging.md) |
| 監視データ・ログの確認 | [監視とログ](monitoring.md) |

## CLI のヘルプと基本コマンド

CLI はターミナルから実行するコマンドです。オプションは `--help` で確認できます。

```shell
uv run --locked python -m scripts.template --help
uv run --locked python -m scripts.template hello
uv run --locked python -m scripts.template --verbose hello --name Azure
```

基本コマンドも同じ settings パッケージと優先順位を使います。
`.env` があれば読み込み、なければ OS の値と既定値を使います。

## ドキュメントを編集する場合

| 目的 | コマンド |
| --- | --- |
| 英語・日本語のページをビルド | `make ci-test-docs` |
| ライブリロード付きでプレビュー | `make docs-serve` |

Material for MkDocs と `mkdocs-static-i18n` で両言語を公開しています。
Zensical などへ移行する場合も、同じ多言語出力が必要です。
Zensical は未対応の MkDocs プラグインを実行しません。
