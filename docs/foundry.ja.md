# Microsoft Foundry

AI モデルへの質問と、エージェントの作成・会話を試します。
使う CLI は `scripts.cli_foundry` です。

## 1. 接続先を設定する

[開発環境と Azure の共通準備](scripts.md)を済ませてから、次を用意します。

- Microsoft Foundry のアカウントとプロジェクト
- Responses API に対応したモデル。既定のモデル名は `gpt-5-mini`
- コマンドを実行する ID と、プロジェクトのマネージド ID のアクセス権

`.env` の次の値を、実際のプロジェクト URL に変更します。

```dotenv
FOUNDRY_PROJECT_ENDPOINT=https://<account>.services.ai.azure.com/api/projects/<project>
```

**`/api/projects/` を含む HTTPS URL が必要です。**
URL の形式が不正な場合は、認証前に入力エラーを表示し、終了コード 2 で終了します。
以降のコマンドは、この Python リポジトリのルートで実行します。

## 2. アクセス権を確認する

Foundry アカウントに、次の両方の ID の
[Foundry User ロール](https://learn.microsoft.com/ja-jp/azure/foundry/concepts/rbac-foundry)を付与します。

| 付与する相手 | 用途 |
| --- | --- |
| CLI を実行するユーザーまたはサービスプリンシパル | API の呼び出し |
| プロジェクトのマネージド ID | プロジェクトからのアクセス |

`Foundry User` の旧名称は `Azure AI User` です。旧名称が表示される場合もあります。
`Owner` や `Contributor` だけでは、このデータ操作の権限を満たしません。
Foundry ポータルで作成したプロジェクトでは、作成者の権限に応じて自動付与されることがあります。

### ロールが未設定の場合

ロールを付与できる管理者が実行します。以下は **Azure CLI にユーザーとして
サインインした場合**の例です。プレースホルダーを置き換えます。

```shell
SUBSCRIPTION_ID="$(az account show --query id --output tsv)"
RESOURCE_GROUP="<foundry-resource-group>"
FOUNDRY_ACCOUNT="<foundry-account-name>"
FOUNDRY_PROJECT="<foundry-project-name>"
FOUNDRY_SCOPE="/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.CognitiveServices/accounts/${FOUNDRY_ACCOUNT}"
PROJECT_SCOPE="${FOUNDRY_SCOPE}/projects/${FOUNDRY_PROJECT}"

USER_OBJECT_ID="$(az ad signed-in-user show --query id --output tsv)"
PROJECT_PRINCIPAL_ID="$(az resource show --ids "$PROJECT_SCOPE" --query identity.principalId --output tsv)"
printf '%s\n' "$PROJECT_PRINCIPAL_ID"
```

`PROJECT_PRINCIPAL_ID` が空なら、先にプロジェクトのマネージド ID を設定します。
ID を取得できてから、両方にロールを付与します。

```shell
az role assignment create \
  --assignee-object-id "$USER_OBJECT_ID" --assignee-principal-type User \
  --role "Foundry User" --scope "$FOUNDRY_SCOPE"
az role assignment create \
  --assignee-object-id "$PROJECT_PRINCIPAL_ID" --assignee-principal-type ServicePrincipal \
  --role "Foundry User" --scope "$FOUNDRY_SCOPE"
```

サービスプリンシパルで CLI を実行する場合は、最初の割り当てにそのオブジェクト ID と
`--assignee-principal-type ServicePrincipal` を使います。

### 設定結果を確認する

```shell
az role assignment list \
  --scope "$FOUNDRY_SCOPE" --include-inherited \
  --query "[?principalId=='${USER_OBJECT_ID}' || principalId=='${PROJECT_PRINCIPAL_ID}'].{principalType:principalType,role:roleDefinitionName,scope:scope}" \
  --output table
```

両方の ID に `Foundry User`（または旧名称）があることを確認します。
付与直後は、反映まで数分待ってください。

## 3. 使いたいコマンドを実行する

3 種類の操作は独立して試せます。

### モデルに質問する

```shell
uv run --locked python -m scripts.cli_foundry chat-model
```

モデルの回答がテキストで表示されます。質問やモデルを変える例です。

```shell
uv run --locked python -m scripts.cli_foundry chat-model \
  --model gpt-5-mini --prompt "What is the size of France in square miles?"
```

### エージェントを作成する

```shell
uv run --locked python -m scripts.cli_foundry create-agent \
  --agent-name MyAgent --model gpt-5-mini \
  --instructions "You are a helpful assistant."
```

エージェントの ID・名前・バージョンが表示されます。
同じ名前で再実行すると、新しいバージョンを作成します。

### エージェントと会話する

```shell
uv run --locked python -m scripts.cli_foundry chat-agent \
  --agent-name MyAgent \
  --prompt "What is the size of France in square miles?" \
  --follow-up-prompt "And what is the capital city?"
```

エージェントを作成または更新して、同じ会話で 2 回質問します。
**先に `create-agent` を実行する必要はありません。**

## オプションを確認する

`--endpoint` で `.env` の接続先を上書きできます。
既定値と全オプションは `--help` で確認します。

```shell
uv run --locked python -m scripts.cli_foundry --help
uv run --locked python -m scripts.cli_foundry chat-model --help
uv run --locked python -m scripts.cli_foundry create-agent --help
uv run --locked python -m scripts.cli_foundry chat-agent --help
```

## 403 エラーが出る場合

`PermissionDeniedError: Error code: 403` が出たら、コードを変える前に次の順で確認します。

1. `az account show` でサブスクリプション・テナント・実行 ID を確認します。
2. `FOUNDRY_PROJECT_ENDPOINT` がプロジェクト URL であることを確認します。
3. モデルの状態と Responses API 対応を確認します。上で設定したリソース名を使います。

   ```shell
   az cognitiveservices account deployment show \
     --resource-group "$RESOURCE_GROUP" --name "$FOUNDRY_ACCOUNT" \
     --deployment-name "gpt-5-mini" \
     --query "{state:properties.provisioningState,responses:properties.capabilities.responses,model:properties.model.name,version:properties.model.version}" \
     --output table
   ```

   別のデプロイ名を使う場合は `--deployment-name` を変更します。
4. 実行 ID とプロジェクトのマネージド ID の両方に、前述のロールがあるか確認します。
5. ロールの反映を待ち、`chat-model` を再実行します。

解消しない場合は、アカウントのファイアウォール・仮想ネットワーク・
プライベートエンドポイントを確認します。
[HTTP エラーの確認方法](https://learn.microsoft.com/ja-jp/azure/foundry/openai/how-to/troubleshoot-errors)も参照してください。

`create-agent` と `chat-agent` の接続先を、リソースレベルの OpenAI URL に
置き換えないでください。プロジェクトのアクセス権の問題は解消せず、必要な機能も使えなくなります。
