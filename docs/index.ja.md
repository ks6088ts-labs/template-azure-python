# はじめに

Python の開発と Azure SDK のサンプル実行を始めるためのテンプレートです。
同じ FastAPI アプリを、ローカル・Azure Functions・Azure Container Apps で動かせます。

## まずローカルで動かす

Azure のリソースやサインインは不要です。
[Python・uv・Make を用意](scripts.md)し、リポジトリのルートで実行します。

```shell
make install-deps-dev
uv run --locked python -m scripts.template serve-container-apps
```

別のターミナルで API を確認します。

```shell
curl http://127.0.0.1:8000/tasks
```

初期状態で `[]` が返れば起動完了です。既定の保存先は InMemory です。
Cosmos 永続化と管理 CLI は [Cosmos DB](cosmosdb.md) を参照してください。
ブラウザーで <http://127.0.0.1:8000/docs> を開くと、API を操作できます。
サーバーを止めるには、起動したターミナルで `Ctrl+C` を押します。

## 目的からガイドを選ぶ

| やりたいこと | 読むガイド |
| --- | --- |
| 開発環境を整え、API・テスト・Docker を動かす | [ローカル開発](scripts.md) |
| Task・dbt・ローカル DuckDB でデータエンジニアリングを学ぶ | [Data engineering 入門](dbt/index.md) |
| AI モデルやエージェントを試す | [Microsoft Foundry](foundry.md) |
| データを保存・取得する | [Azure Cosmos DB](cosmosdb.md) |
| イベントやメッセージを送受信する | [メッセージング](messaging.md) |
| Azure の監視データやログを確認する | [監視とログ](monitoring.md) |
| アプリ・イメージ・ドキュメントを公開する | [デプロイ](deployment.md) |

## おすすめの進め方

1. **ローカルで確認する**: 上の手順で API を起動し、開発ガイドでテスト方法を確認します。
2. **必要な Azure サンプルだけ試す**: 各ガイドで設定値とアクセス権を確認します。
3. **公開する**: デプロイ先を選び、公開後に API またはサイトの応答を確認します。

Azure サンプルは既存のリソースを使います。リソースの準備方法、料金や削除に関する
注意点は各ガイドを参照してください。すべてのサンプルを順番に実行する必要はありません。
