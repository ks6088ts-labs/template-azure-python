# Task 分析プロジェクトをゼロから作る

[入門・最短実行](index.md) の完成版と同じモデルを、自分の作業ディレクトリに組み立てます。
各章は **目的 → 作業 → 確認** の順です。成功ログだけでなく、行数・値・失敗時の挙動を確認してください。

## 1. 作業場所と接続を作る

### 目的

dbt プロジェクトの構成と、DB への接続設定を区別します。
公式 quickstart の `dbt init` は Jaffle Shop などのサンプルを生成します。
ここでは中身を理解するため、Task 用の最小構成を手作業で作ります。

### 作業

以下は macOS / Linux 用です。すべてリポジトリルート、同じターミナルで実行します。
`artifacts/dbt/task_analytics` が既に存在する場合は別名を選んでください。
`mkdir` が「既に存在する」と失敗したら、以降の操作を続けて既存ファイルを上書きしないでください。

```shell
export DBT_TASK_EXAMPLE_DIR="$PWD/docs/dbt/task_analytics"
export DBT_PROJECT_DIR="$PWD/artifacts/dbt/task_analytics"
export DBT_PROFILES_DIR="$DBT_PROJECT_DIR"
export DBT_SEND_ANONYMOUS_USAGE_STATS=false

mkdir -p artifacts/dbt
mkdir "$DBT_PROJECT_DIR"
mkdir -p "$DBT_PROJECT_DIR/models/staging" "$DBT_PROJECT_DIR/models/marts" \
  "$DBT_PROJECT_DIR/seeds" "$DBT_PROJECT_DIR/tests"
```

新しいターミナルを開いたときは、リポジトリルートで上の `export` 4行だけを再実行します。
PowerShell の変数設定は [入門](index.md) を参照し、プロジェクトのパスを作業用パスへ変更します。

エディターで `$DBT_PROJECT_DIR/dbt_project.yml` を作成します。

```yaml
name: task_analytics
version: "1.0.0"
config-version: 2
require-dbt-version: [">=2.0.8", "<3.0.0"]
profile: task_analytics

model-paths: ["models"]
seed-paths: ["seeds"]
test-paths: ["tests"]
clean-targets: ["target", "dbt_packages"]

models:
  task_analytics:
    staging:
      +materialized: view
    marts:
      +materialized: table
```

- `name` はプロジェクト名、`profile` は接続設定を探すキーです。
- `model-paths` / `seed-paths` / `test-paths` は、プロジェクト内のファイルの役割を分けます。
- **materialization** はモデルを DB 内でどのように保存するかです。
  staging は view、mart は table に設定しました。

次に `$DBT_PROJECT_DIR/profiles.yml` を作成します。

```yaml
task_analytics:
  target: dev
  outputs:
    dev:
      type: duckdb
      path: "{{ env_var('DBT_PROJECT_DIR') }}/task_analytics.duckdb"
      schema: main
      threads: 1
```

`target: dev` は `outputs.dev` を選択します。`schema: main` はテーブル等を置く名前空間です。
`threads: 1` は教材を単純にするための実行並列度で、性能チューニングの推奨値ではありません。
`env_var()` は shell の環境変数を読みます。絶対パスで DB を固定し、
実行場所によって別の DB が作られる事故を避けます。未設定ならエラーにします。

```shell
uv run --locked --no-dev --group dbt dbt --version
uv run --locked --no-dev --group dbt dbt debug
```

### 確認

バージョンが 2.x、接続が成功し、表示される DB パスが作業ディレクトリ内であることを確認します。
まだモデルがない段階では、未使用の model 設定について警告が出ることがあります。
この手順は `~/.dbt/profiles.yml` やアプリの DB を変更しません。

## 2. Task を CSV seed として読み込む

### 目的

「入力データを DB に置く」と「入力を変換する」を分離します。
CSV の Task は現在状態のサンプルで、status 変更の履歴ではありません。

### 作業

`$DBT_PROJECT_DIR/seeds/raw_tasks.csv` を作成します。最初の title / description の
前後スペースと、2行目の空 description もそのまま保存してください。

```csv
id,title,description,status
00000000-0000-0000-0000-000000000001,  Plan ingestion  ,  Define the input columns  ,todo
00000000-0000-0000-0000-000000000002,Write staging SQL,,todo
00000000-0000-0000-0000-000000000003,Build task mart,Join tasks to their status,in_progress
00000000-0000-0000-0000-000000000004,Add data tests,Check keys and domain rules,in_progress
00000000-0000-0000-0000-000000000005,Install dbt,Use the existing uv group,done
00000000-0000-0000-0000-000000000006,Connect DuckDB,Use a local database file,done
```

`$DBT_PROJECT_DIR/seeds/task_statuses.csv` を作成します。

```csv
status,status_label,status_order,is_completed
todo,To do,1,false
in_progress,In progress,2,false
done,Done,3,true
```

型推論だけに頼らず、UUID を文字列、並び順を整数、完了フラグを boolean にします。
型指定・列説明・seed の品質テストをまとめた
[seeds/properties.yml](task_analytics/seeds/properties.yml) を読み、作業用へコピーします。
この時点の構成は `dbt_project.yml`、`profiles.yml`、CSV 2個、seed の YAML 1個です。

```shell
cp "$DBT_TASK_EXAMPLE_DIR/seeds/properties.yml" "$DBT_PROJECT_DIR/seeds/properties.yml"

uv run --locked --no-dev --group dbt dbt seed
uv run --locked --no-dev --group dbt dbt show --inline \
  "select count(*) as task_count from {{ ref('raw_tasks') }}"
```

### 確認

`raw_tasks` が6行、`task_statuses` が3行の table になります。確認クエリの期待値は `6` です。
`seed` は読み込みを行うコマンドで、data tests まで自動実行するものではありません。

`ref('raw_tasks')` は名前の一致する seed の DB relation を解決します。
DB 名や schema を SQL に直接書くより、依存や接続先を dbt が管理できます。
本番の外部取り込み済み table は一般に `source('名前', 'table名')` で参照します。
この seed を架空の外部 source として登録する必要はありません。

## 3. staging で分析用の形を作る

### 目的

**staging** では入力との対応を維持しながら、列名・型・通常スペースを整えます。
粒度は **1行 = 1つの現在の Task** のままです。集計や不正行の除外はしません。

### 作業

`$DBT_PROJECT_DIR/models/staging/stg_tasks.sql` を作成します。

```sql
select
    cast(id as varchar) as task_id,
    trim(title) as task_title,
    trim(coalesce(description, '')) as task_description,
    status
from {{ ref('raw_tasks') }}
```

空の CSV セルは NULL になるため、description に限ってドメインの既定値 `''` へ変換します。
title や status の NULL / 不正値は補完しません。
`trim()` と Python `strip()` の適用範囲の違いは [入門の境界説明](index.md) を参照してください。

```shell
uv run --locked --no-dev --group dbt dbt run --select stg_tasks
uv run --locked --no-dev --group dbt dbt show --inline \
  "select task_id, task_title, length(task_description) as description_length from {{ ref('stg_tasks') }} order by task_id" \
  --limit 6
```

### 確認

6行のまま、末尾 `001` の title は `Plan ingestion`、
末尾 `002` の description の長さは `0` になります。
view は SQL 定義を保存し、問い合わせ時に入力を読むため、独立したデータのコピーではありません。

## 4. dimension / fact / mart を構築する

### 目的

**dimension** は状態の意味を表す参照データ、**fact** は分析対象の Task です。
fact が必ずイベントや数値だけを表すわけではありません。この教材の fact は現在状態です。
**mart** は特定の分析目的に合わせたモデル群で、集計済み table だけを指すわけではありません。

### 作業

`$DBT_PROJECT_DIR/models/marts/dim_task_status.sql` を作成します。

```sql
select
    status,
    status_label,
    status_order,
    is_completed
from {{ ref('task_statuses') }}
```

`$DBT_PROJECT_DIR/models/marts/fct_tasks.sql` を作成します。

```sql
select
    tasks.task_id,
    tasks.task_title,
    tasks.task_description,
    tasks.status,
    statuses.is_completed
from {{ ref('stg_tasks') }} as tasks
left join {{ ref('dim_task_status') }} as statuses
    on tasks.status = statuses.status
```

`left join` によって、不正 status の Task も消さずに残します。
参照先がなければ `is_completed` が NULL になり、後のテストで検出します。
dimension の status が重複すると fact の行が増えるため、主キーの一意性も重要です。

`$DBT_PROJECT_DIR/models/marts/task_status_summary.sql` を作成します。

```sql
select
    statuses.status,
    statuses.status_label,
    statuses.status_order,
    count(tasks.task_id) as task_count
from {{ ref('dim_task_status') }} as statuses
left join {{ ref('fct_tasks') }} as tasks
    on statuses.status = tasks.status
group by
    statuses.status,
    statuses.status_label,
    statuses.status_order
```

集計の粒度は **1行 = 1 status** です。dimension を左側にして、0件の状態も残します。
ここで `count(*)` にすると、Task がないときの JOIN の1行まで数えるため、
NULL にならない Task キーに対する `count(tasks.task_id)` を使います。

```shell
uv run --locked --no-dev --group dbt dbt run
uv run --locked --no-dev --group dbt dbt show --inline \
  "select status, task_count from {{ ref('task_status_summary') }} order by status_order"
```

### 確認

`todo=2`、`in_progress=2`、`done=2`。`fct_tasks` は6行、dimension / summary は各3行です。
SQL table の行順は保証されないため、レポート側で `order by` を指定します。
dbt はファイル名順ではなく `ref()` の DAG に従って4モデルを構築します。
table は結果を保存するため、入力変更後は再構築するまで古い値が残ります。

`dbt show --select task_status_summary` は **モデル SQL を再実行するプレビュー** です。
保存済み table の状態を確かめたいときは、上の `show --inline` と `ref()` を使います。
この違いは更新・障害調査で重要です。

## 5. データ品質をテストする

### 目的

SQL が実行できることと、正しいデータが得られることは別です。
制約をコードにし、壊れた入力を黙って捨てずに検出します。

### 作業

[models/properties.yml](task_analytics/models/properties.yml) を読み、作業用へコピーします。
**下の YAML はその一部の説明用であり、別の YAML として重複登録しないでください。**

```yaml
version: 2
models:
  - name: fct_tasks
    columns:
      - name: task_id
        data_tests: [not_null, unique]
      - name: status
        data_tests:
          - not_null
          - relationships:
              arguments:
                to: ref('dim_task_status')
                field: status
```

| generic test | 検証すること |
| --- | --- |
| `not_null` | 必須値が NULL でない |
| `unique` | grain を識別するキーが重複しない |
| `accepted_values` | status が許可された値だけである |
| `relationships` | status の参照先が dimension に存在する |

`accepted_values` と `relationships` は NULL を別途検証しないため、`not_null` と併用します。
v2 の引数は `arguments:` の下に書きます。

複数列にまたがる条件は **singular test** の SQL で表します。
[assert_task_domain_rules.sql](task_analytics/tests/assert_task_domain_rules.sql) の本体は次です。

```sql
select task_id
from {{ ref('stg_tasks') }}
where
    not regexp_full_match(
        task_id,
        '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'
    )
    or length(task_title) = 0
    or length(task_title) > 200
    or length(task_description) > 2000
```

**違反した行を返す SQL** です。結果が0行なら成功、1行以上なら失敗します。
NULL はこの SQL の比較だけで検出しようとせず、generic test で検証します。
SQL における長さは文字数です。200バイトではありません。

次の3つの singular tests をコピーします。内容も読んでください。

- UUID 表記・title / description の長さ:
  [assert_task_domain_rules.sql](task_analytics/tests/assert_task_domain_rules.sql)
- dimension の3状態・並び順・完了フラグ:
  [assert_status_dimension.sql](task_analytics/tests/assert_status_dimension.sql)
- 状態別件数と総件数の整合性:
  [assert_task_summary_consistent.sql](task_analytics/tests/assert_task_summary_consistent.sql)

```shell
cp "$DBT_TASK_EXAMPLE_DIR/models/properties.yml" "$DBT_PROJECT_DIR/models/properties.yml"
cp "$DBT_TASK_EXAMPLE_DIR/tests/assert_task_domain_rules.sql" "$DBT_PROJECT_DIR/tests/"
cp "$DBT_TASK_EXAMPLE_DIR/tests/assert_status_dimension.sql" "$DBT_PROJECT_DIR/tests/"
cp "$DBT_TASK_EXAMPLE_DIR/tests/assert_task_summary_consistent.sql" "$DBT_PROJECT_DIR/tests/"

uv run --locked --no-dev --group dbt dbt test
uv run --locked --no-dev --group dbt dbt build
```

### 確認

`test` は構築済みデータを検証し、42 tests が成功します。
`build` は seeds → models → tests を依存関係に沿って組み合わせ、
上流のテストに失敗すると関連する下流の構築をスキップします。
`run` 単体にはこの品質ゲートはありません。

### 演習: 壊して、調べて、戻す

**作業用** `seeds/raw_tasks.csv` の末尾 `001` の status だけを `blocked` へ変更し、実行します。

```shell
uv run --locked --no-dev --group dbt dbt build
```

期待するのは `accepted_values_raw_tasks_status...` の失敗と非ゼロ終了です。
失敗は学習目標で、入力を勝手に `todo` へ補正してはいけません。
`target/run_results.json` と失敗した test の SQL を確認します。
`build` はプロジェクト全体をまとめてロールバックする仕組みではなく、
入力の seed が変わり、下流 table が前回のまま残ることがあります。古い mart を正常な最新結果と解釈しないでください。

元の入力に戻して再実行します。

```shell
cp "$DBT_TASK_EXAMPLE_DIR/seeds/raw_tasks.csv" "$DBT_PROJECT_DIR/seeds/raw_tasks.csv"
uv run --locked --no-dev --group dbt dbt build
```

次に同じ ID の行を1行複製し、`unique_raw_tasks_id` が失敗することを確認します。
さらに title をスペースだけにして、`assert_task_domain_rules` が失敗することを確認します。
**各演習の前後に上の復旧を行い、最後は正常な6件に戻してください。**

## 6. 状態を更新し、再現性を確かめる

### 目的

現在状態の置き換えと、履歴の保存を区別します。全件再構築の再実行で重複が増えないことを確かめます。

### 作業

作業用 CSV の末尾 `001` の行だけ、status を `todo` から `done` に変えます。
それ以外の列・行は変更しません。

```csv
00000000-0000-0000-0000-000000000001,  Plan ingestion  ,  Define the input columns  ,done
```

まず **変換だけ** を実行してみます。

```shell
uv run --locked --no-dev --group dbt dbt run
uv run --locked --no-dev --group dbt dbt show --inline \
  "select status, task_count from {{ ref('task_status_summary') }} order by status_order"
```

まだ `2 / 2 / 2` です。`run` は CSV の変更を読み込む `seed` を実行しません。
次に入力も含めて構築します。

```shell
uv run --locked --no-dev --group dbt dbt build
uv run --locked --no-dev --group dbt dbt show --inline \
  "select status, task_count from {{ ref('task_status_summary') }} order by status_order"
uv run --locked --no-dev --group dbt dbt show --inline \
  "select count(*) as total_tasks, sum(case when is_completed then 1 else 0 end) as completed_tasks, round(100.0 * sum(case when is_completed then 1 else 0 end) / nullif(count(*), 0), 2) as completion_rate_pct from {{ ref('fct_tasks') }}"
```

### 確認

更新後は `todo=1`、`in_progress=2`、`done=3`、総数6件、完了率50%。
もう一度 `build` と確認クエリを実行しても同じ値になります。これがこの教材での再実行の再現性です。

このプロジェクトは incremental ではなく、table / view の再構築です。
通常の CSV 内容変更に `--full-refresh` は不要です。seed の列型を変更する場合など、
既存 table を作り直す必要があるときは `dbt seed --full-refresh` を使います。
incremental モデルの `--full-refresh` は全件再計算で、別の用途です。

**追加演習:** 初期 CSV に戻した後、2つの `todo` をどちらも `done` に変えて `build`。
期待値は `todo=0`、`in_progress=2`、`done=4` です。0件の状態も summary に残る理由を
JOIN と `count(tasks.task_id)` から説明してください。終わったら初期 CSV に戻して `build` します。

## 7. ローカル Docs と lineage を見る

### 目的

モデル・列の意味とデータの由来を、他の人が追える形にします。
この **dbt Docs** は分析プロジェクトのドキュメントであり、
チュートリアルを公開するリポジトリの **MkDocs** とは別です。

### 作業

v2 の静的解析で列の情報と lineage を生成し、その情報から Docs サイトを作ります。

```shell
uv run --locked --no-dev --group dbt dbt build --static-analysis strict --generate-info-schema
uv run --locked --no-dev --group dbt dbt docs generate --no-compile
uv run --locked --no-dev --group dbt dbt docs serve --target-path "$DBT_PROJECT_DIR/target" --host 127.0.0.1 --port 8580 --no-open
```

ブラウザーで <http://127.0.0.1:8580> を開きます。`--no-compile` は直前に生成した index を使い、
追加の compile で静的解析の結果を置き換えないためです。index がなければエラーになります。
通常のサイト生成には `dbt docs generate` 単独も利用できます。
v2 の `docs serve` は既定で現在のディレクトリの `target/` を探すため、
リポジトリルートから起動する本教材では `--target-path` も明示します。

`--write-catalog` は catalog metadata の生成であり、閲覧可能なサイト生成とは別です。
dbt v2 の Docs / static analysis の詳細は [公式コマンド説明](https://docs.getdbt.com/reference/commands/cmd-docs?version=2.0) を参照してください。

### 確認と演習

1. `stg_tasks` のモデル説明と `task_title` の列説明を探す。
2. `fct_tasks` の主キーと `status` の参照テストを確認する。
3. `task_status_summary` から上流の2モデル、さらに seed までたどる。
4. `task_count` の元になる Task キーと、status がどこから来るかを列情報で確かめる。
5. 作業用モデルの description を変更し、build → generate で表示を更新する。

終了するときはサーバーのターミナルで `Ctrl+C`。
Docs は `target/` 内に生成されます。compiled SQL やテスト失敗の情報も入り得るため、
実データで利用する場合は `target/` 全体を無条件に公開しないでください。

### 任意: VS Code から確認

公式 quickstart に沿って、dbt Labs の
[公式拡張](https://marketplace.visualstudio.com/items?itemName=dbtLabsInc.dbt) をインストールします。
**dbt プロジェクトのフォルダー自体** を VS Code の workspace に追加してください。
リポジトリルートだけを開いていると、ネストしたプロジェクトを LSP が検出できない場合があります。

CLI と同じ絶対パスの `DBT_PROJECT_DIR` / `DBT_PROFILES_DIR` を VS Code の起動環境にも設定し、
拡張が使う dbt 実行ファイルをリポジトリの `.venv/bin/dbt` に合わせます
（Windows は `.venv/Scripts/dbt.exe`）。ターミナル内だけの `export` は、起動済み VS Code 全体には伝わりません。
拡張の接続設定でこの profile と DB パスを確認し、モデルを開いて Lineage / Query Results を確認します。
拡張の利用・アカウント機能は任意で、CLI とローカル Docs だけでも教材を完了できます。

## 8. Task API を接続し、永続性を確かめる

### 目的

**同じ Repository 契約**で dbt 生成 Task を扱い、実際の永続性と、
業務 CRUD / 再構築可能な分析の境界を検証します。
列変換・エラー・接続寿命と将来の Cosmos / warehouse 拡張は [実装・拡張ガイド](backends.md)で説明します。

この演習は意図的に dbt 管理 fact を編集します。CSV・raw・集計表は同期しません。
API 再起動では変更が残りますが、**dbt build では上書きされます**。
自分の作業 project だけを使い、完成サンプルや重要なデータは更新しないでください。

### 作業: ターミナル A で準備・起動

前節の dbt Docs・エディター・Python の DB 接続を停止します。
リポジトリルートで、第1節と同じ絶対パスの DBT_PROJECT_DIR / DBT_PROFILES_DIR を使います。
新しいターミナルから再開するなら、先に export を再実行してください。
前節で戻した場合も初期 CSV に復旧し、以降の期待値を元の6件に揃えます。

```shell
cp "$DBT_TASK_EXAMPLE_DIR/seeds/raw_tasks.csv" "$DBT_PROJECT_DIR/seeds/raw_tasks.csv"
uv run --locked --no-dev --group dbt dbt build
export DUCKDB_PATH="$DBT_PROJECT_DIR/task_analytics.duckdb"
export TELEMETRY_ENABLED=false
uv run --locked python -m scripts.template serve-container-apps --repository duckdb
```

A は起動したままにします。Azure の account・サインイン・dbt platform account・jq・DB サーバーは不要です。
Python duckdb driver は通常のアプリ依存であり、dbt 内蔵 driver とは別です。
ポート8000を使用中なら --port を指定し、B の URL も合わせます。

### 作業: ターミナル B で HTTP の確認と更新

B も**リポジトリルート**で開きます。A の export は B に継承されません。
B は HTTP だけを使い、A の稼働中は別プロセスから DuckDB を開かないでください。
各 assert / test は成功する必要があります。非ゼロ終了なら、先へ進む前に原因を調べます。

```shell
export TASK_API_URL=http://127.0.0.1:8000
TASK_HTTP_DIR=$(mktemp -d)
curl --fail --silent --show-error "$TASK_API_URL/tasks" -o "$TASK_HTTP_DIR/tasks.json"
uv run --locked python -c 'import json,sys; rows=json.load(sys.stdin); by_id={t["id"]:t for t in rows}; assert len(rows)==6; assert all(set(t)=={"id","title","description","status"} for t in rows); assert by_id["00000000-0000-0000-0000-000000000001"]["title"]=="Plan ingestion"; assert by_id["00000000-0000-0000-0000-000000000002"]["description"]==""; print("Initial 6 Tasks, normalized fields")' < "$TASK_HTTP_DIR/tasks.json"

test "$(curl --silent --show-error "$TASK_API_URL/tasks" \
  -H 'Content-Type: application/json' -d '{"title":"API exercise","description":"Temporary"}' \
  -o "$TASK_HTTP_DIR/created.json" -w '%{http_code}')" = 201
TASK_ID=$(uv run --locked python -c 'import json,sys; t=json.load(sys.stdin); assert t["status"]=="todo"; print(t["id"])' < "$TASK_HTTP_DIR/created.json")
curl --fail --silent --show-error "$TASK_API_URL/tasks/$TASK_ID"

test "$(curl --silent --show-error -X PUT \
  "$TASK_API_URL/tasks/00000000-0000-0000-0000-000000000001" \
  -H 'Content-Type: application/json' \
  -d '{"title":"Plan ingestion","description":"Define the input columns","status":"done"}' \
  -o /dev/null -w '%{http_code}')" = 200
```

PUT は Task 全体の置換です。存在しない PATCH を使わず title / description / status を指定します。
TASK_ID は固定値ではなく、実際の POST 応答から取得した UUID です。

### 確認: A を再起動して B で読み取る

A で Ctrl+C を押し、shutdown 完了後に同じパスで再起動します。

```shell
uv run --locked python -m scripts.template serve-container-apps --repository duckdb
```

B で、生成 UUID が残り、総数7件・done 3件であることを確認します。

```shell
curl --fail --silent --show-error "$TASK_API_URL/tasks" -o "$TASK_HTTP_DIR/tasks.json"
uv run --locked python -c 'import json,sys; rows=json.load(sys.stdin); assert len(rows)==7; assert sum(t["status"]=="done" for t in rows)==3; assert any(t["id"]==sys.argv[1] for t in rows); print("Restart retained 7 Tasks, 3 done")' "$TASK_ID" < "$TASK_HTTP_DIR/tasks.json"

test "$(curl --silent --show-error -X DELETE "$TASK_API_URL/tasks/$TASK_ID" \
  -o /dev/null -w '%{http_code}')" = 204
test "$(curl --silent --show-error "$TASK_API_URL/tasks/$TASK_ID" \
  -o "$TASK_HTTP_DIR/missing.json" -w '%{http_code}')" = 404
test "$(curl --silent --show-error "$TASK_API_URL/tasks" \
  -H 'Content-Type: application/json' -d '{"title":" "}' \
  -o "$TASK_HTTP_DIR/invalid.json" -w '%{http_code}')" = 422
curl --fail --silent --show-error "$TASK_API_URL/tasks" -o "$TASK_HTTP_DIR/tasks.json"
uv run --locked python -c 'import json,sys; rows=json.load(sys.stdin); assert len(rows)==6; assert sum(t["status"]=="done" for t in rows)==3; print("Deleted exercise Task; 6 Tasks, 3 done")' < "$TASK_HTTP_DIR/tasks.json"
```

### 確認: A を停止して保存済み分析結果を読む

SQL / dbt の実行**前**に A を Ctrl+C で停止し、shutdown を待ちます。
A で、同じ project の export を維持して実行します。

```shell
uv run --locked --no-dev --group dbt dbt show --inline \
  "select task_id, status, is_completed from {{ ref('fct_tasks') }} where task_id = '00000000-0000-0000-0000-000000000001'"
uv run --locked --no-dev --group dbt dbt show --inline \
  "select status, count(*) as task_count from {{ ref('raw_tasks') }} group by status order by status"
uv run --locked --no-dev --group dbt dbt show --inline \
  "select status, task_count from {{ ref('task_status_summary') }} order by status_order"
uv run --locked --no-dev --group dbt dbt test
```

fact の末尾001は **done / true**、raw・保存済み summary は各状態2件のままです。
fact は todo=1 / in_progress=2 / done=3、summary は 2 / 2 / 2 なので、
assert_task_summary_consistent が**非ゼロ終了で失敗**することを確認します。
これは意図した失敗です。test を削除せず、他の失敗があれば別途調査してください。
保存済み表を見るには show --inline と ref() を使います。show --select は model SQL の preview です。

### 作業と確認: 再構築して復旧する

API を停止したまま A で実行します。

```shell
uv run --locked --no-dev --group dbt dbt build
uv run --locked --no-dev --group dbt dbt show --inline \
  "select count(*) as total_tasks, sum(case when is_completed then 1 else 0 end) as completed_tasks from {{ ref('fct_tasks') }}"
uv run --locked python -m scripts.template serve-container-apps --repository duckdb
```

期待値は data tests 42件成功、total_tasks=6 / completed_tasks=2 です。
再構築は変更していない CSV を読み、**API からの状態更新を破棄**します。
B で確認します。

```shell
curl --fail --silent --show-error "$TASK_API_URL/tasks" -o "$TASK_HTTP_DIR/tasks.json"
uv run --locked python -c 'import json,sys; rows=json.load(sys.stdin); assert len(rows)==6; assert sum(t["status"]=="done" for t in rows)==2; assert next(t for t in rows if t["id"]=="00000000-0000-0000-0000-000000000001")["status"]=="todo"; assert all(t["id"]!=sys.argv[1] for t in rows); print("Rebuild restored 6 Tasks, 2 done; API mutation overwritten")' "$TASK_ID" < "$TASK_HTTP_DIR/tasks.json"
```

| 段階 | Fact の件数 | done の件数 | 保存済み summary |
| --- | --- | --- | --- |
| 初期 build | 6 | 2 | 2 / 2 / 2 |
| POST | 7 | 2 | 変更なし |
| 既存001の PUT | 7 | 3 | 変更なし |
| API 再起動 | 7 | 3 | 変更なし |
| 演習 UUID の DELETE | 6 | 3 | 2 / 2 / 2 のまま。test が不整合を検知 |
| dbt 再構築 | 6 | 2 | 2 / 2 / 2 に復旧 |

再起動でデータが残ることと、自動同期を混同しないでください。
業務 Cosmos と別の分析基盤の設計は [拡張ガイド](backends.md)で説明します。

### 後片付け

A を再度停止します。B で自分が作成した4つの HTTP 応答だけを削除します。

```shell
rm "$TASK_HTTP_DIR/created.json" "$TASK_HTTP_DIR/tasks.json" \
  "$TASK_HTTP_DIR/missing.json" "$TASK_HTTP_DIR/invalid.json"
rmdir "$TASK_HTTP_DIR"
unset TASK_ID TASK_HTTP_DIR TASK_API_URL
```

A で演習用の DUCKDB_PATH / TELEMETRY_ENABLED を解除し、元の値があれば復元します。
DB の削除は API と他の接続を停止してから行ってください。

## 9. トラブルシューティング・復習・後片付け

| 症状 | 確認すること |
| --- | --- |
| `dbt` が v1 / 別ツールになっている | bare `dbt` ではなく、このガイドの `uv run --locked --no-dev --group dbt dbt --version` を使う |
| profile / 環境変数が見つからない | リポジトリルートで `export` を再設定。YAML の `profile: task_analytics` とトップレベルのキーを一致させる |
| table が見つからない | 同じ DB パスで seed / build 済みか。別のターミナルでも同じ環境変数か |
| CSV を変えても結果が変わらない | `run` だけでは Load しない。`build` または `seed` → `run` → `test` を使う |
| DuckDB の file lock エラー | 別の dbt / Python / DuckDB プロセスの接続を閉じる。同じ DB を複数プロセスで同時に書き込まない |
| API で DUCKDB_PATH の不備 | 起動ターミナルで既存ファイルの絶対パスを export する。ディレクトリを指定しない |
| API 起動時に table / column がない | 同じ DBT_PROJECT_DIR で build し、main.fct_tasks がサンプル列を持つ実テーブルか確認 |
| API と dbt の Task が違う | DUCKDB_PATH と profile の path を照合。ターミナル間で export は独立 |
| API CRUD 後に summary test が失敗 | fact だけが変化した場合の想定動作。API を停止し、演習の復旧を実行 |
| dbt build で API 更新が消える | 想定動作。dbt は API 更新ではなく上流入力から fact を再構築 |
| Functions がファイルを参照できない | 起動元 / host へ DUCKDB_PATH を渡し、filesystem のパスを確認。自動 mount はない |
| Docs に列の lineage がない | strict static analysis と `--generate-info-schema` 付きで build し、`docs generate --no-compile` で生成したか |
| Docs が `no data to serve` になる | `--target-path "$DBT_PROJECT_DIR/target"` で対象プロジェクトの生成物を指定したか |
| Docs のポートが使用中 | 自分の Docs を停止するか、`--port 8581` にして対応する URL を開く |
| seed 型変更後にエラー | 教材の seed に限定して `seed --full-refresh`、その後 `build` |

答えられれば基礎編の完了です。

- Task が6行なのに summary が3行なのはなぜか。
- `ref()`、`seed`、`source()`、SQL モデルはそれぞれ何を担うか。
- `run` / `test` / `build` の違いは何か。
- `unique` と `relationships` がない JOIN は、どんな誤った集計を作り得るか。
- 現在の完了率から、今週の処理時間や生産性を説明できないのはなぜか。

初期状態へ戻すには、作業用 CSV を復旧して `build` します。

```shell
cp "$DBT_TASK_EXAMPLE_DIR/seeds/raw_tasks.csv" "$DBT_PROJECT_DIR/seeds/raw_tasks.csv"
uv run --locked --no-dev --group dbt dbt build
```

生成物を消したい場合は、サーバーと DB 接続を閉じてから、
エディター / ファイルマネージャーで **自分が作った作業ディレクトリ内だけ** の
`task_analytics.duckdb`、あれば `task_analytics.duckdb.wal`、`target/`、`logs/` を削除します。
作業用 SQL・CSV を残せば `build` で DB を再生成できます。
`dbt clean` は設定された clean targets を消すコマンドで、DB 本体まで消すものではありません。
リポジトリ、グローバル profile、アプリの永続データは削除しません。

この shell での設定が不要になったら解除します。もともと設定していた変数がある場合は、その値へ戻してください。

```shell
unset DBT_PROJECT_DIR DBT_PROFILES_DIR DBT_SEND_ANONYMOUS_USAGE_STATS DBT_TASK_EXAMPLE_DIR
```

### 発展課題

| 次にやりたいこと | 追加で必要な設計 |
| --- | --- |
| 既存 API の Task を分析 | 別プロセスのアプリから export する取り込み処理、UUID / status の検証、取得時点の定義 |
| 外部 raw table を使う | dbt とは別の Load と、`sources:` / `source()` による参照・lineage |
| 大量データの incremental | 更新検知、安定した unique key、遅延・削除・再処理の方針 |
| 状態の履歴や日別推移 | 取得時刻・変更時刻、snapshot / event / CDC の選択と履歴粒度 |
| 処理時間・期限超過 | 開始・完了・期限の日時と、指標の分母・期間・タイムゾーン |
| 継続的な実行 | 取り込みと dbt の orchestration、失敗通知、権限、CI / scheduler |

これらの値や挙動を現在の4項目から推測で補うことはしません。
