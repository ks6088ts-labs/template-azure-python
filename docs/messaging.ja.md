# メッセージング

Azure の 4 サービスで、イベントやメッセージを送受信します。
**使いたいサービスだけ選んで実行してください。**

| サービス | このサンプルでできること | 受信時の動作 |
| --- | --- | --- |
| Event Grid | Basic Custom Topic にイベントを発行 | 受信コマンドなし |
| Event Hubs | イベントを送受信 | 削除しない。読み取り位置も保存しない |
| Service Bus | Queue にメッセージを送受信 | **表示後に削除する** |
| Queue Storage | キューとメッセージを作成・取得・更新・削除 | 一時的に非表示にする。削除は別操作 |

Service Bus の受信と Queue Storage の削除には、検証用キューを使ってください。
既存アプリのキューで試すと、必要なメッセージを失うおそれがあります。

## 1. 接続先を設定する

[開発環境と Azure の共通準備](scripts.md)を済ませ、使用するサービスのリソースを用意します。
[`azure_messaging` Terraform シナリオ](https://github.com/ks6088ts/template-terraform/tree/main/infra/scenarios/azure_messaging)
を使う場合、サービスはすべて既定で無効です。同リポジトリの手順で必要なものだけ有効にします。
この Python リポジトリで Terraform を変更する必要はありません。

Terraform リポジトリのチェックアウト先で、設定値を取得します。

```shell
terraform -chdir=infra/scenarios/azure_messaging output
terraform -chdir=infra/scenarios/azure_messaging output -raw event_grid_topic_endpoint
```

Python リポジトリの `.env` に、使うサービスの出力を設定します。
無効なサービスの `null` や未表示の値は使いません。

| Terraform 出力 | `.env` 変数 | 上書きする CLI オプション |
| --- | --- | --- |
| `event_grid_topic_endpoint` | `AZURE_EVENT_GRID_TOPIC_ENDPOINT` | `--endpoint` |
| `event_hubs_namespace_fqdn` | `AZURE_EVENT_HUBS_FULLY_QUALIFIED_NAMESPACE` | `--fully-qualified-namespace` |
| `event_hub_name` | `AZURE_EVENT_HUB_NAME` | `--event-hub` |
| `event_hub_consumer_group_name` | `AZURE_EVENT_HUB_CONSUMER_GROUP` | `--consumer-group` |
| `service_bus_namespace_fqdn` | `AZURE_SERVICE_BUS_FULLY_QUALIFIED_NAMESPACE` | `--fully-qualified-namespace` |
| `service_bus_queue_name` | `AZURE_SERVICE_BUS_QUEUE_NAME` | `--queue` |
| `queue_storage_endpoint` | `AZURE_QUEUE_STORAGE_ENDPOINT` | `--endpoint` |
| `queue_storage_queue_name` | `AZURE_QUEUE_STORAGE_QUEUE_NAME` | `--queue` |

- 名前空間には `<namespace>.servicebus.windows.net` のような**ホスト名だけ**を設定します。
- Event Grid と Queue Storage には HTTPS URL を設定します。Storage は Blob / DFS ではなく Queue の URL です。
- `$Default` はそのままの文字列です。シェルでは `'$Default'` と引用します。
- 認証は `DefaultAzureCredential` のみです。接続文字列・共有キー・SAS は使いません。
  Terraform シナリオも共有キーによるデータ操作を無効にしています。

## 2. アクセス権を確認する

シナリオは、`operator_principal_id` の ID に次のロールを付与します。
既定の ID は Terraform 実行者です。実行時の ID が違う場合は、管理者に付与を依頼します。

| サービス | 必要なロール | 付与先（Terraform 出力） |
| --- | --- | --- |
| Event Grid | `EventGrid Data Sender` | Topic (`event_grid_topic_id`) |
| Event Hubs | `Azure Event Hubs Data Sender`, `Azure Event Hubs Data Receiver` | 名前空間 (`event_hubs_namespace_id`) |
| Service Bus | `Azure Service Bus Data Sender`, `Azure Service Bus Data Receiver` | 名前空間 (`service_bus_namespace_id`) |
| Queue Storage | `Storage Queue Data Contributor` | Storage アカウント (`queue_storage_account_id`) |

`Owner` / `Contributor` だけでは、これらのデータ操作の権限を満たしません。
次のプレースホルダーを置き換え、実行 ID の割り当てを確認します。

```shell
az account show --query "{subscription:name,tenantId:tenantId,user:user.name}" --output table
MESSAGING_SCOPE="<resource-ID-from-the-table>"
PRINCIPAL_ID="<calling-principal-object-ID>"
az role assignment list \
  --scope "$MESSAGING_SCOPE" --include-inherited \
  --query "[?principalId=='${PRINCIPAL_ID}'].{role:roleDefinitionName,scope:scope}" \
  --output table
```

Azure で動かす場合は、そのマネージド ID を確認します。
新しいロールの反映には数分かかります。

## 3. 使うサービスのコマンドを実行する

以降の CLI は、この Python リポジトリのルートで実行します。
各コマンドに `--help` を付けると、全オプションと既定値を確認できます。

### Event Grid: イベントを発行する

```shell
uv run --locked python -m scripts.cli_event_grid publish-event
uv run --locked python -m scripts.cli_event_grid publish-events --count 3
```

単一イベント、またはイベントのリストを 1 回の送信で発行します。
結果は `schema`・`count`・`ids` を含む 1 行の JSON です。
発行成功だけでは配信先は作成されません。シナリオはイベントサブスクリプションを作成しません。

#### 入力スキーマを合わせる

| Topic の `inputSchema` | CLI の指定 |
| --- | --- |
| `EventGridSchema`（Terraform の既定値） | 省略、または `--schema event-grid` |
| `CloudEventSchemaV1_0` | `--schema cloud-event` |

スキーマが違うと `BadRequest` になります。CLI で Topic のスキーマは変更できません。
CloudEvent を使う場合は、先にシナリオで
`event_grid_input_schema = "CloudEventSchemaV1_0"` を適用します。
その Topic に対して、次の例を実行します。

```shell
uv run --locked python -m scripts.cli_event_grid publish-event \
  --schema cloud-event --source "/samples/orders" \
  --subject "orders/42" --event-type "Sample.OrderCreated" --data '{"orderId":42}'
```

`--data` は JSON オブジェクトのみです。`--data-version` は Event Grid スキーマ用で、
CloudEvent のバージョン指定ではありません。`CustomEventSchema` と
Namespace の受信・確認・ロック操作は対象外です。

### Event Hubs: イベントを送受信する

```shell
uv run --locked python -m scripts.cli_event_hubs send-events
uv run --locked python -m scripts.cli_event_hubs receive-events \
  --consumer-group '$Default' --starting-position '-1' \
  --max-events 3 --max-wait-time 30
```

既定の送信は 3 イベントを 1 つの SDK batch で送ります。
本文を変えるには `--message "First event" --message '{"orderId":42}'` のように指定します。
送信結果は `{"sent": N}`、受信結果はイベントごとの JSON と最後の `{"received": N}` です。

| 受信オプション | 既定値・意味 |
| --- | --- |
| `--max-events` | 100 件。指定範囲は 1～10,000 |
| `--max-wait-time` | 15 秒。全パーティションでイベントが届かない時間の上限 |
| `--starting-position` | `-1`（保持中のイベントの先頭）。`@latest` は接続後の新しいイベントだけ |
| `--consumer-group` | `$Default` |

受信は上限件数または無受信のタイムアウトで終了します。イベントが届くたびに
タイムアウトをリセットするため、空のパーティションだけを理由に終了しません。
初回の待機時間には認証・接続・パーティション探索も含まれます。

イベントの JSON は `body`・`partition_id`・`offset`・`sequence_number`・
`enqueued_time` を含みます。0 件でも最後に `{"received": 0}` を表示します。
受信は非破壊ですが、**checkpoint（読み取り位置）は保存しません**。
再実行すると同じイベントを読むことがあります。シナリオに Blob container と
`Storage Blob Data Contributor` がないため、Blob checkpoint store は対象外です。

### Service Bus: Queue に送受信する

**受信したメッセージは表示後に complete され、キューから削除されます。**
`.env` の接続先が検証用キューであることを確認してください。

```shell
uv run --locked python -m scripts.cli_service_bus send-message
uv run --locked python -m scripts.cli_service_bus send-message-list
uv run --locked python -m scripts.cli_service_bus send-message-batch
uv run --locked python -m scripts.cli_service_bus receive-messages \
  --max-messages 10 --max-wait-time 5
```

| 送信コマンド | 動作 |
| --- | --- |
| `send-message` | 1 件送信 |
| `send-message-list` | リストを 1 回で送信（既定は 3 件） |
| `send-message-batch` | SDK batch で送信（既定は 3 件） |

`--message` で本文、`--count` で list / batch の件数を変更できます。
batch の容量を超えるとエラーになります。件数または本文サイズを減らしてください。
送信は `{"sent": N}`、受信は各メッセージの `body`・`message_id`・メタデータと、
最後に `{"received": N}` を 1 行ずつ表示します。受信の既定値は最大 10 件・待機 5 秒です。
シナリオの Topic / Subscription は、この Queue 専用 CLI の対象外です。

### Queue Storage: 検証用キューで一連の操作を試す

ここでは一意なキューを作り、すべての操作で `--queue` を指定します。
**Terraform 管理下のキューに置き換えないでください。**
キュー名には小文字英数字とハイフンを使います。

#### 1. 作成・送信・取得

```shell
SCRATCH_QUEUE="messaging-cli-scratch-$(date +%s)"
uv run --locked python -m scripts.cli_queue_storage create-queue --queue "$SCRATCH_QUEUE"
uv run --locked python -m scripts.cli_queue_storage send-message \
  --queue "$SCRATCH_QUEUE" --message "Please update me"
uv run --locked python -m scripts.cli_queue_storage peek-messages --queue "$SCRATCH_QUEUE"
uv run --locked python -m scripts.cli_queue_storage get-queue-length --queue "$SCRATCH_QUEUE"
uv run --locked python -m scripts.cli_queue_storage receive-messages \
  --queue "$SCRATCH_QUEUE" --max-messages 1 --visibility-timeout 120
```

`peek` は表示だけです。`receive` はこの例では 120 秒間非表示にしますが、削除しません。
受信結果は `{"received": N, "messages": [...]}`、空なら `{"received": 0, "messages": []}` です。
キュー長は概算値で、現在見えるメッセージだけの件数ではありません。

#### 2. メッセージを更新

受信結果の**同じメッセージ**から `id` と `pop_receipt` をコピーし、
非表示時間内に実行します。

```shell
MESSAGE_ID="<message-ID-from-receive>"
POP_RECEIPT="<matching-pop-receipt-from-receive>"
uv run --locked python -m scripts.cli_queue_storage update-message \
  --queue "$SCRATCH_QUEUE" --message-id "$MESSAGE_ID" --pop-receipt "$POP_RECEIPT" \
  --message "Updated content" --visibility-timeout 120
```

更新すると新しい `pop_receipt` が返ります。再受信でも値が変わるため、
更新・削除には常に最新の値を使います。

#### 3. メッセージと検証用キューを削除

更新結果の receipt を使ってメッセージを削除し、確認に同意してキューを削除します。
**キュー削除は残りの全メッセージも削除します。**

```shell
POP_RECEIPT="<new-pop-receipt-from-update>"
uv run --locked python -m scripts.cli_queue_storage delete-message \
  --queue "$SCRATCH_QUEUE" --message-id "$MESSAGE_ID" --pop-receipt "$POP_RECEIPT"
uv run --locked python -m scripts.cli_queue_storage delete-queue --queue "$SCRATCH_QUEUE"
```

確認を拒否すると、Azure API を呼ばずにキャンセルします。
非対話実行では `delete-queue --queue "$SCRATCH_QUEUE" --yes` と明示してください。

#### オプションと出力の要点

- peek / receive は既定 1 件、`--max-messages` は 1～32 です。
- receive の既定の非表示時間は 30 秒、send / update は 0 秒です。
  `--visibility-timeout` は残りの有効期間より短くします。メッセージの既定の有効期間は 7 日です。
- send / update は `id` と `pop_receipt` を含む JSON を返します。peek は receipt を含みません。
  各結果は 1 行の JSON です。削除しないメッセージは、非表示時間が過ぎると再び取得できます。

## 困ったとき

| 症状 | 対処 |
| --- | --- |
| 必須オプションがない | 対応する `.env` 変数を設定します。既存ファイルは上書きしません |
| `.env` を直しても値が変わらない | 古いシェルの環境変数を削除するか、CLI オプションで指定します |
| Terraform のプラグイン不足 | Terraform 側で `terraform -chdir=infra/scenarios/azure_messaging init` を実行します |
| unauthorized / forbidden | 実行 ID・テナント・上記ロール・ネットワーク制限を確認します |
| Event Hubs が 0 件を返す | `--max-wait-time 30 --starting-position '-1'` で再実行し、接続先と受信権限を確認します |
| Event Grid がスキーマを拒否する | Topic の `inputSchema` と `--schema` を合わせます |
| Queue Storage の更新・削除に失敗する | 同じメッセージの最新の `pop_receipt` を使います |

## 補足: 設定値を Azure から取得する

Terraform の出力を使えない場合は、次の読み取りコマンドでも設定値を取得できます。
サインインとサブスクリプションの選択を済ませ、**使うサービスのコマンドだけ**実行します。
設定の取得や CLI の検証に `terraform apply` は不要です。

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

名前空間の出力が `https://example.servicebus.windows.net:443/` の場合は、
`example.servicebus.windows.net` だけを設定します。Event Grid / Queue Storage は URL 全体を使います。
キューの一覧取得にもデータ操作のロールが必要です。秘密情報やアカウントキーは不要です。

## 参考資料

- [Event Grid Python SDK](https://learn.microsoft.com/en-us/python/api/overview/azure/eventgrid-readme?view=azure-python)
- [Event Hubs Python クイックスタート](https://learn.microsoft.com/en-us/azure/event-hubs/event-hubs-python-get-started-send?tabs=passwordless%2Croles-azure-portal)
- [Service Bus Queue Python クイックスタート](https://learn.microsoft.com/en-us/azure/service-bus-messaging/service-bus-python-how-to-use-queues?tabs=passwordless)
- [Queue Storage Python クイックスタート](https://learn.microsoft.com/en-us/azure/storage/queues/storage-quickstart-queues-python?tabs=passwordless%2Croles-azure-portal%2Cenvironment-variable-windows%2Csign-in-azure-cli)
