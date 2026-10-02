# 監視とログ

Azure の監視データやログを、CLI で読み取ります。
最後の「テレメトリを送って確認する」以外は読み取り専用です。
CLI はアクセス権の付与、診断設定の変更、コレクターの作成を行いません。

## 1. 読み取り先を設定する

[開発環境と Azure の共通準備](scripts.md)を済ませ、使うリソースを用意します。
[`azure_observability` Terraform シナリオ](https://github.com/ks6088ts/template-terraform/tree/main/infra/scenarios/azure_observability)
の機能はすべて既定で無効です。必要な機能だけ、同リポジトリで有効にしてください。

| 見たいもの | シナリオで必要な機能 |
| --- | --- |
| マネージド Prometheus | `features.azure_monitor` |
| Log Analytics の `AzureActivity` | `features.log_analytics` と `features.activity_log` |
| Application Insights | `features.application_insights` と `features.log_analytics` |
| Network Watcher | `features.network_watcher` |
| サブスクリプションの Activity Log API | 機能フラグ不要。ワークスペースとは独立 |

`features.activity_log` はログのエクスポート設定です。Activity Log API の有効化ではありません。
Azure Monitor Workspace は Prometheus 用で、Log Analytics とは別のリソースです。

Terraform リポジトリのチェックアウト先で、秘密情報を含まない出力を取得します。

```shell
terraform -chdir=infra/scenarios/azure_observability output
terraform -chdir=infra/scenarios/azure_observability output -raw azure_monitor_id
```

Python リポジトリの既存の `.env` に、使う対象の値だけ設定します。

| 取得元 | `.env` 変数 | 値の形式 |
| --- | --- | --- |
| `azure_monitor_id` | `AZURE_MONITOR_ID` | Azure Monitor Workspace の ARM ID |
| `log_analytics_workspace_id` | `AZURE_LOG_ANALYTICS_WORKSPACE_ID` | ワークスペースの GUID |
| `application_insights_id` | `AZURE_APPLICATION_INSIGHTS_ID` | Application Insights の ARM ID |
| `network_watcher_id` | `AZURE_NETWORK_WATCHER_ID` | Watcher の ARM ID |
| `az account show --query id --output tsv` | `AZURE_SUBSCRIPTION_ID` | サブスクリプションの GUID |
| `resource_group_name` または実際の Watcher のグループ | `AZURE_RESOURCE_GROUP` | 任意の絞り込み。全体を読む場合は空 |

ARM ID は `/subscriptions/<id>/resourceGroups/<group>/providers/` で始まるパスです。
GUID は `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` 形式です。
**Log Analytics には `log_analytics_id`（ARM ID）ではなく GUID を使います。**
`activity_log_id` はエクスポート設定の ID で、サブスクリプション ID ではありません。
無効な機能の `null` は設定せず、その実習を省略します。

CLI で上書きする場合、Monitor / Application Insights / Watcher は `--resource-id`、
Log Analytics は `--workspace-id`、Activity Log は `--subscription-id` を使います。

## 2. 読み取り権限を確認する

実際にコマンドを実行する ID に、管理者が次の権限を付与します。

| 操作 | ロール | 付与先 |
| --- | --- | --- |
| ワークスペース・Watcher の情報取得 | `Reader` | 対象リソース。一覧取得は対象グループまたはサブスクリプション |
| PromQL クエリ | `Monitoring Data Reader` | Azure Monitor Workspace |
| Log Analytics クエリ | `Log Analytics Reader` | Log Analytics ワークスペース |
| Application Insights クエリ | `Reader` またはワークスペースのクエリ権限 | Application Insights または保存先ワークスペース |
| Activity Log API | `Reader`（Activity Log 読み取りを含む） | サブスクリプション |

PromQL の `Monitoring Data Reader` は `Monitoring Reader` とは別です。
Application Insights は、ワークスペースがリソースの権限による読み取りを許可していれば
コンポーネントの `Reader` を使えます。それ以外は保存先の `Log Analytics Reader` などが必要です。

詳細は [Prometheus API](https://learn.microsoft.com/azure/azure-monitor/metrics/prometheus-api-promql)と
[Log Analytics のアクセス管理](https://learn.microsoft.com/azure/azure-monitor/logs/manage-access)を参照してください。

## 3. 必要なデータを読み取る

以降は、この Python リポジトリのルートで実行します。
使える対象のコマンドだけ選び、全オプションは各コマンドの `--help` で確認します。

### Prometheus: ワークスペースとメトリック

```shell
uv run --locked python -m scripts.cli_azure_monitor show-workspace
uv run --locked python -m scripts.cli_azure_monitor query-prometheus --query 'up'
```

シナリオはコレクターを作成しません。収集を別途設定していなければ、
`status: success` でも `result` が空なのは正常です。

### Log Analytics: エクスポート済みの Activity Log

```shell
uv run --locked python -m scripts.cli_log_analytics query-logs --hours 24 --limit 100
uv run --locked python -m scripts.cli_log_analytics summarize-activity --hours 24 --limit 100
```

固定の `AzureActivity` クエリを実行します。任意の KQL を渡す CLI ではありません。
対象ワークスペースへの[診断エクスポート](https://learn.microsoft.com/azure/azure-monitor/platform/activity-log#export-activity-log)と
取り込み待ちが必要です。未設定なら、テーブルが未作成または空になります。

### Application Insights: リクエストなどのテレメトリ

```shell
uv run --locked python -m scripts.cli_application_insights query-telemetry \
  --table AppRequests --hours 24 --limit 100
```

読み取りに接続文字列は不要です。`--table` は `AppRequests`・`AppTraces`・
`AppMetrics`・`AppDependencies` の 4 種類です。

### Network Watcher: 配置と設定

```shell
uv run --locked python -m scripts.cli_network_watcher list-watchers
uv run --locked python -m scripts.cli_network_watcher show-watcher
```

Watcher はシナリオとは別のリソースグループにある場合があります。
全体を探す場合は `AZURE_RESOURCE_GROUP` を空にします。個別の対象は
`show-watcher --resource-id "<watcher-ARM-ID>"` で指定できます。
これらは[読み取り専用](https://learn.microsoft.com/azure/network-watcher/network-watcher-overview)で、
パケットキャプチャや接続テストは開始しません。

### Activity Log API: サブスクリプションの操作履歴

```shell
uv run --locked python -m scripts.cli_activity_log list-events --hours 24 --limit 100
uv run --locked python -m scripts.cli_activity_log summarize-events --hours 24 --limit 100
```

ワークスペースへのエクスポートがなくても読めます。
操作がなければ結果は空です。[Activity Log の概要](https://learn.microsoft.com/azure/azure-monitor/platform/activity-log)も参照してください。

### 絞り込みと集計の違い

- ログ・テレメトリ・Activity Log は `--hours` が 1～168（既定 24）、
  `--limit` が 1～1,000（既定 100）です。
- `list-watchers`・`list-events`・`summarize-events` は
  `--resource-group "<group>"` または `AZURE_RESOURCE_GROUP` で絞れます。

| コマンド | `--limit` が制限するもの |
| --- | --- |
| `query-logs`, `query-telemetry` | 返す行数 |
| Log Analytics の `summarize-activity` | 時間範囲内の全一致行を集計した後のグループ数 |
| Activity Log の `summarize-events` | 取得・集計するイベント数。期間内の総数ではない |

## 4. テレメトリを送って確認する（任意）

**この手順だけデータを送信します。取り込み料金が発生する場合があります。**

### 接続文字列をローカルに設定する

シナリオは接続文字列を出力しません。Azure portal の Application Insights の
**概要**から取得し、Git の無視対象 `.env` の `APPLICATIONINSIGHTS_CONNECTION_STRING` に設定します。
ローカルのシークレット管理で環境変数を設定しても構いません。

テンプレートの値は空のままにします。ソース・シェルの引数や履歴・ログ・
スクリーンショット・共有出力に値を貼り付けないでください。接続文字列用の CLI オプションはありません。
[接続文字列](https://learn.microsoft.com/azure/azure-monitor/app/connection-strings)と
[Python OpenTelemetry](https://learn.microsoft.com/azure/azure-monitor/app/opentelemetry-enable?tabs=python)も参照してください。

### サンプルを送信する

```shell
uv run --locked python -m scripts.cli_application_insights emit-telemetry --count 10
```

`--count` は 1～100（既定 10）です。server span・相関ログ・メトリック増分を送信し、
一意の `run_id` を表示します。dependency span は生成しません。
flush の失敗や検知した SDK 警告は報告されます。
**`flushed: true` はローカルの送信処理完了だけを示し、Azure の受理・取り込みを保証しません。**

### 同じ実行のデータを検索する

取り込みを待ち、最近のリクエストと、表示された UUID の各データを確認します。

```shell
uv run --locked python -m scripts.cli_application_insights query-telemetry \
  --table AppRequests --hours 1 --limit 100
RUN_ID="<run_id-UUID-printed-by-emit-telemetry>"
uv run --locked python -m scripts.cli_application_insights query-telemetry \
  --table AppRequests --run-id "$RUN_ID" --hours 1 --limit 100
uv run --locked python -m scripts.cli_application_insights query-telemetry \
  --table AppTraces --run-id "$RUN_ID" --hours 1 --limit 100
uv run --locked python -m scripts.cli_application_insights query-telemetry \
  --table AppMetrics --run-id "$RUN_ID" --hours 1 --limit 100
```

`--run-id` は省略可能ですが、指定する場合は UUID を使います。

| 確認するもの | 見る値 |
| --- | --- |
| 時刻 | `timestamp` |
| 実行 ID | `customDimensions.run_id` |
| `quickstart.events` のメトリック | 対象実行の `valueSum` の合計を `--count` と比較 |

CLI はテーブル名をリソース用 API の `requests`・`traces`・`customMetrics`・
`dependencies` に変換し、JSON の列名は API の形式を保ちます。
メトリックは集約されるため、行数ではなく値で比較してください。

シナリオのサンプリングは既定 25% です。送信 CLI のクライアント側設定は別で、
`always_on` を使います。ログや span の行数は `--count` と一致するとは限りません。
各データの到着時刻も異なる場合があります。
[サンプリング](https://learn.microsoft.com/azure/azure-monitor/app/opentelemetry-sampling)と
[取り込み遅延](https://learn.microsoft.com/azure/azure-monitor/logs/data-ingestion-time)を確認し、
見つからない場合は同じ `run_id` で待って再検索します。無制限に再送しないでください。

終了後はローカルの接続文字列を削除します。**ローカル設定の削除だけでは Azure の課金は止まりません。**

## 困ったとき

| 症状 | 対処 |
| --- | --- |
| `Missing option` | 対応表の ID を `.env` に追加するか、CLI で指定します。`az login` は ID を設定しません |
| 古い `.env` に変数がない | 既存ファイルに不足する変数を追記します。テンプレートの更新は自動反映されません |
| 一部のグループしか表示されない | `AZURE_RESOURCE_GROUP` の絞り込みを確認します |
| 403 | 実行 ID・テナント・ロールの付与先・反映待ち・ネットワーク制限を確認します |
| `AzureActivity` がない | 対象ワークスペースへの診断エクスポートと取り込みを確認します |
| Application Insights のテーブルエラー | CLI を更新します。リソース用 API とワークスペース用のスキーマは異なります |
| 送信したデータが見つからない | 同じ `run_id` で再検索し、送信先・検索先・サンプリング・SDK 警告・ネットワークを確認します |

CLI オプションや一時的な環境変数は、後から開くターミナルに保存されません。
設定後は通常のターミナルでコマンドを再実行してください。
Application Insights の[スキーマ](https://learn.microsoft.com/azure/azure-monitor/app/data-model-complete)では、
リソース用 API の `timestamp`・`customDimensions` と、ワークスペース用の
`TimeGenerated`・`Properties` を混同しないようにします。
