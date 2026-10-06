# LLM 評価

Microsoft Foundry の Prompt Agent を [DeepEval](https://deepeval.com/docs/introduction) で評価します。
アプリの実行時依存や既存 unit test の配置は変更しません。
**通常の pytest と CI では、課金される評価を実行しません。** `eval` グループをインストールしても有効にはなりません。

## テストの階層

| 配置 | 対象 | 外部 LLM 呼び出し |
| --- | --- | --- |
| 既存の `tests/test_*.py` | unit test とアーキテクチャ | なし |
| `tests/test_evaluation_harness.py` | 収集ゲート、設定、データ、Foundry の寿命管理のモック検証 | なし |
| `tests/test_evaluation_deepeval.py` | fake metric を使った実際の DeepEval API の検証。接続禁止、未インストール時は skip | なし |
| `tests/evaluations/test_*.py` | Foundry の実回答を Azure OpenAI judge で評価 | ローカルで明示した場合のみ |

評価用 helper はテストの隣に置きます。`config.py` は設定とシナリオ検証、
`foundry.py` は Azure リソースと会話、`metrics.py` は judge と指標を担当します。
本番パッケージは DeepEval を import しません。既存 unit test の設定隔離を維持し、
評価ディレクトリ内だけで実際の環境変数と `.env` を読み込みます。

## アクセス権と設定

[Foundry の準備](foundry.md)に従い、アカウント、プロジェクト、Responses API 対応モデル、Entra ID を用意します。
実行者には評価用 Agent と会話を作成・実行・削除できる権限が必要です。
本番ではなく開発用プロジェクトを使用します。評価クライアントでは SDK の Agent endpoint の preview を明示的に有効化します。

judge 用には、構造化出力をサポートする `gpt-4.1-mini` などを Azure OpenAI にデプロイします。
そのリソースで実行者に **Cognitive Services OpenAI User** を付与してください。
両方とも `DefaultAzureCredential` を使います。ローカルのサインインは [Azure サンプルの共通準備](scripts.md#azure) を参照してください。
API key や Confident AI のアカウントは不要です。

Git 管理外の `.env` に次の非 secret 設定を記載し、実行前にプレースホルダーを置き換えます。

```dotenv
FOUNDRY_PROJECT_ENDPOINT=https://<account>.services.ai.azure.com/api/projects/<project>
LLM_EVAL_AGENT_MODEL=gpt-5-mini
LLM_EVAL_JUDGE_ENDPOINT=https://<judge-resource>.openai.azure.com
LLM_EVAL_JUDGE_DEPLOYMENT=<judge-deployment-name>
LLM_EVAL_JUDGE_MODEL=gpt-4.1-mini
LLM_EVAL_JUDGE_API_VERSION=2024-10-21
```

Agent のモデル設定はデプロイ済みモデル名です。judge の deployment 名と元のモデル名は別々に設定します。
judge endpoint は Azure OpenAI リソースのルートであり、Foundry の project URL や `/openai/v1/` URL ではありません。
標準の DeepEval モデルは API version を指定する Azure OpenAI API と
`https://cognitiveservices.azure.com/.default` を使用し、Foundry SDK は `https://ai.azure.com/.default` を使用します。
設定の優先順位は環境変数、`.env`、既定値です。必須設定の不足や不正は skip せず失敗として扱います。

起動時に `LLM_EVAL_JUDGE_ENDPOINT` または `LLM_EVAL_JUDGE_DEPLOYMENT` が表示される場合は、
その非 secret 値が未設定です。`.env` に追加してください。`eval` のインストールだけでは設定されません。
実際に存在する deployment を選び、`LLM_EVAL_JUDGE_MODEL` には元のモデル名を指定します。
たとえば `gpt-4o` の deployment には `gpt-4o` を指定します。
Foundry アカウントのルート `https://<account>.services.ai.azure.com` も、API version を指定する Azure OpenAI API に利用できます。
judge endpoint に `/api/projects/<project>` は含めません。
設定エラーは必要な環境変数名を示し、値や設定ライブラリの長い traceback は表示しません。

任意設定は `LLM_EVAL_TIMEOUT_SECONDS=60` と `LLM_EVAL_MAX_OUTPUT_TOKENS=512` です。
judge は temperature 0、指標の逐次実行、リクエストごとの出力上限 2048 token を使います。

## 評価を実行する

```shell
# 通常のテスト。課金される呼び出しなし
make test

# 評価依存のインストールだけでは実評価は有効にならない
uv sync --locked --no-dev --group eval

# 認証・LLM 呼び出しなしで7ケースを列挙
make test-eval EVAL_ARGS=--collect-only

# 課金あり。まず1ケースだけ確認
make test-eval EVAL_ARGS='-m llm_eval_smoke'

# 課金あり。全ケース
make test-eval

# 課金あり。pytest のフィルターでケースを選択
make test-eval EVAL_ARGS='-k provided-context'
```

`make test-eval` は公式の `deepeval test run` を実行し、pytest に `--run-llm-evals` を渡します。
ファイルの直接指定でもこのフラグは必要で、`-m llm_eval` だけでは許可されません。
通常の pytest は DeepEval プラグインを無効化し、評価モジュールを import 前に除外します。
専用コマンドだけがプラグインを有効化し、unit test 用 coverage を外します。
匿名 telemetry、DeepEval の dotenv・旧 key 設定の自動読み込み、Confident AI への送信は無効です。
リポジトリ自身の設定は引き続き `.env` を読み込みます。グローバルな `deepeval set-*` 設定は不要です。

## 評価パターン

| パターン | 指標・assertion | 必要な根拠 |
| --- | --- | --- |
| 単一ターンの関連性 | `AnswerRelevancyMetric` | 実際の入力と回答 |
| 正しさ・不明な情報への回答 | `GEval` | 人が独立して記述した期待回答 |
| 指示遵守 | 固定 evaluation steps の `GEval` | 言語・形式などの要件 |
| 構造化出力 | judge 前の JSON 解析と厳密な object contract | 期待するキーと値 |
| 提供した資料への忠実性 | `FaithfulnessMetric` と correctness | Agent に実際に渡した同じ資料 |
| 複数ターンの情報保持 | `ConversationalTestCase`、`KnowledgeRetentionMetric`、必須値 assertion | 固定 user prompt と同一会話の実 assistant 回答 |

単一ターン6ケースと、user が3回発言する会話1ケースを用意しています。
各ケースには必要な指標だけを1〜2個適用し、初期 threshold は `0.7` です。
期待回答は評価する回答から生成せず、レビューした入力として JSON データに版管理します。
ID、要件、threshold もデータに置きます。JSON と必須値の契約は judge token を使う前に通常の assert で検証します。

資料を提供するケースは生成側の評価であり、実 retriever の品質を検証したものではありません。
初期スイートにはツール付き Agent や trajectory の計装は含みません。

## 費用・結果・校正

Agent と judge の両方が token を消費します。全ケースでは Agent の回答を9回取得し、
それに加えて各指標が複数の judge request を実行する場合があります。1指標が1 request とは限りません。
ケースと指標は逐次実行し、SDK・provider の retry は有限にします。
repeat・並列実行・ignore-errors を既定には追加しません。timeout と出力上限は費用を抑えますが、総額の厳密な上限ではありません。
judge cache は既定で無効です。明示的に使っても Agent の推論費用は残ります。
prompt、Agent version、judge の deployment・モデル、rubric、dataset が変わった結果を再利用しないでください。

標準の JSON report と `junit.xml` は Git 管理外の `artifacts/evaluations/` に保存します。
DeepEval の `.deepeval/` も管理外です。score、threshold、reason に加え、Agent の name・version・モデル、
judge のモデル・deployment・API version、instructions、dataset の SHA-256、rubric の版を記録します。
指標の不合格は非0の終了コードになります。
収集だけの実行では、列挙後に `No test cases found` と表示される場合があります。assertion を実行していないためです。

temperature 0 でも完全な決定性はありません。良い回答・悪い回答を人手で確認して rubric と threshold を校正し、
境界付近のケースは理由と変動を確認してください。デプロイしたモデルの版も記録します。
合格するまで再実行したり、threshold を自動的に下げたりしません。judge の score は安全性や正しさの証明ではありません。
offline test は評価基盤の接続を確認するもので、モデル品質の実測ではありません。

初期データは合成データだけです。入力と回答は Azure judge に送信され、ローカル report にも残る場合があります。
機密・個人情報を除去してからシナリオを追加し、report を非公開で扱ってください。

ケースごとに `deepeval-<uuid>` という一意の Agent と会話を作り、自分で作成したリソースだけを削除します。
失敗時も client と資格情報の解放を試みます。cleanup の失敗は SDK の生情報を出さずに resource ID を報告し、
残りの cleanup を続行します。評価の元の例外は保持します。
プロセスを強制終了した場合は、開発プロジェクトで報告された評価用 Agent・会話を確認し、
自分で作ったものだけを Foundry ポータルまたは SDK で削除してください。強制終了時の cleanup は保証できません。

## CI と拡張

通常 CI は決定的なテストを実行します。別の compatibility job が Python 3.10・3.14 で任意依存をインストールし、
fake Agent・metric、DeepEval の assertion と CLI report を接続禁止下で検証します。
専用の型検査と実スイートの収集も行いますが、Azure の資格情報は渡しません。
`CI` または `GITHUB_ACTIONS` が設定されている場合、ゲートは実評価を拒否し、収集だけを許可します。

```shell
uv run --locked --group eval pytest tests/test_evaluation_harness.py tests/test_evaluation_deepeval.py --no-cov
make lint-eval
```

既存 Agent を対象にする場合は明示的な name・version モードを追加し、その Agent を作成・削除しないようにします。
実際の instructions と version を記録してください。
実 RAG には実際に取得した chunk、ツール評価には実際の tool call と期待 tool call が必要です。
Task Completion・Step Efficiency には十分な実 trace が必要です。クライアント側 wrapper だけでは hosted Agent の内部手順は取得できません。
評価入力を架空の履歴で補わないでください。

将来の課金される CI は、承認付き `workflow_dispatch`、OIDC、保護された environment、少数 smoke ケース、
費用の明示承認を組み合わせます。その時点で専用の CI 許可 option を追加し、既定無効のゲートは維持します。
現状では課金される workflow、定期評価、会話シミュレーションは追加しません。

参考: [pytest と CI](https://deepeval.com/docs/evaluation-unit-testing-in-ci-cd)、
[指標の選定](https://deepeval.com/docs/metrics-introduction)、
[Azure OpenAI](https://deepeval.com/integrations/models/azure-openai)、
[設定](https://deepeval.com/docs/environment-variables)。
