# Build Task analytics from scratch

Assemble the same project as the [introduction and quick run](index.md) in your own working directory.
Each section follows **purpose → action → verification**. Verify rows, values, and failure behavior,
not just a successful command.

## 1. Create the workspace and connection

### Purpose

Distinguish project configuration from database connection configuration.
The official quickstart's `dbt init` generates a sample such as Jaffle Shop.
Here you create a minimal Task project by hand to understand its parts.

### Action

These are macOS / Linux commands. Run everything in the same terminal, from the repository root.
If `artifacts/dbt/task_analytics` already exists, choose a different name.
If `mkdir` reports that the directory exists, stop rather than continuing and overwriting files.

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

In a new terminal, rerun only the four `export` lines from the repository root.
For PowerShell variables, see the [introduction](index.md) and substitute the working project path.

Use your editor to create `$DBT_PROJECT_DIR/dbt_project.yml`.

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

- `name` identifies the project; `profile` is the key used to find connection settings.
- `model-paths`, `seed-paths`, and `test-paths` distinguish file responsibilities.
- **Materialization** defines how a model is stored in the database.
  Staging uses views and marts use tables.

Create `$DBT_PROJECT_DIR/profiles.yml`.

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

`target: dev` selects `outputs.dev`; `schema: main` is the namespace for database objects.
`threads: 1` keeps the exercise simple; it is not a performance-tuning recommendation.
`env_var()` reads an environment variable. An absolute database path prevents accidental creation
of different databases when the working directory changes. A missing variable is an error.

```shell
uv run --locked --no-dev --group dbt dbt --version
uv run --locked --no-dev --group dbt dbt debug
```

### Verification

Expect version 2.x and a successful connection. Check that the database path is inside your workspace.
Before you add models, dbt may warn about unused model configuration.
These commands do not alter `~/.dbt/profiles.yml` or the application's database.

## 2. Load Task CSV seeds

### Purpose

Separate loading input into the database from transforming it.
The CSV represents current Tasks, not a history of status changes.

### Action

Create `$DBT_PROJECT_DIR/seeds/raw_tasks.csv`, preserving the surrounding spaces
in the first title / description and the second row's empty description.

```csv
id,title,description,status
00000000-0000-0000-0000-000000000001,  Plan ingestion  ,  Define the input columns  ,todo
00000000-0000-0000-0000-000000000002,Write staging SQL,,todo
00000000-0000-0000-0000-000000000003,Build task mart,Join tasks to their status,in_progress
00000000-0000-0000-0000-000000000004,Add data tests,Check keys and domain rules,in_progress
00000000-0000-0000-0000-000000000005,Install dbt,Use the existing uv group,done
00000000-0000-0000-0000-000000000006,Connect DuckDB,Use a local database file,done
```

Create `$DBT_PROJECT_DIR/seeds/task_statuses.csv`.

```csv
status,status_label,status_order,is_completed
todo,To do,1,false
in_progress,In progress,2,false
done,Done,3,true
```

Do not rely only on type inference: UUIDs should remain strings, ordering keys integers,
and completion flags booleans. Read and copy
[seeds/properties.yml](task_analytics/seeds/properties.yml), which defines types, descriptions,
and seed tests. At this point you have two configuration files, two CSV files, and one seed YAML.

```shell
cp "$DBT_TASK_EXAMPLE_DIR/seeds/properties.yml" "$DBT_PROJECT_DIR/seeds/properties.yml"

uv run --locked --no-dev --group dbt dbt seed
uv run --locked --no-dev --group dbt dbt show --inline \
  "select count(*) as task_count from {{ ref('raw_tasks') }}"
```

### Verification

`raw_tasks` has six rows and `task_statuses` has three rows. The query returns `6`.
`seed` loads data; it does not automatically execute data tests.

`ref('raw_tasks')` resolves the seed's database relation and declares a dependency.
It avoids hard-coding database and schema names into SQL.
Externally loaded production tables are normally referenced using `source('name', 'table_name')`.
Do not register this seed as an imaginary external source.

## 3. Normalize input in staging

### Purpose

**Staging** standardizes column names, types, and ordinary surrounding spaces while preserving
the input correspondence. The grain remains **one row per current Task**.
Do not aggregate or filter out invalid input.

### Action

Create `$DBT_PROJECT_DIR/models/staging/stg_tasks.sql`.

```sql
select
    cast(id as varchar) as task_id,
    trim(title) as task_title,
    trim(coalesce(description, '')) as task_description,
    status
from {{ ref('raw_tasks') }}
```

Empty CSV cells become NULL, so only description is mapped to the domain default `''`.
Do not invent a title or status for missing or invalid values.
See the [scope discussion](index.md) for the difference between SQL `trim()` and Python `strip()`.

```shell
uv run --locked --no-dev --group dbt dbt run --select stg_tasks
uv run --locked --no-dev --group dbt dbt show --inline \
  "select task_id, task_title, length(task_description) as description_length from {{ ref('stg_tasks') }} order by task_id" \
  --limit 6
```

### Verification

There are still six rows. The title for ID ending in `001` is `Plan ingestion`;
the description length for ID ending in `002` is `0`.
A view stores a SQL definition and reads its input when queried; it is not an independent data copy.

## 4. Build dimensions, facts, and a reporting mart

### Purpose

A **dimension** describes status reference information; a **fact** represents the Tasks being analyzed.
A fact need not contain only events or numeric measurements: this one represents current state.
A **mart** is a set of purpose-oriented analytical models, not necessarily only aggregate tables.

### Action

Create `$DBT_PROJECT_DIR/models/marts/dim_task_status.sql`.

```sql
select
    status,
    status_label,
    status_order,
    is_completed
from {{ ref('task_statuses') }}
```

Create `$DBT_PROJECT_DIR/models/marts/fct_tasks.sql`.

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

The `left join` keeps Tasks with invalid statuses instead of dropping them.
If no dimension row matches, `is_completed` is NULL and a later test detects it.
A duplicate status key in the dimension multiplies fact rows, so uniqueness matters too.

Create `$DBT_PROJECT_DIR/models/marts/task_status_summary.sql`.

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

The aggregate grain is **one row per status**. Starting from the dimension preserves zero-count statuses.
`count(*)` would count the join's unmatched row even when there is no Task;
`count(tasks.task_id)` counts only the non-NULL Task keys.

```shell
uv run --locked --no-dev --group dbt dbt run
uv run --locked --no-dev --group dbt dbt show --inline \
  "select status, task_count from {{ ref('task_status_summary') }} order by status_order"
```

### Verification

Expect `todo=2`, `in_progress=2`, `done=2`. The fact has six rows; dimension and summary each have three.
SQL tables have no guaranteed row order, so reports must specify `order by`.
dbt builds the four models according to the `ref()` DAG, not filename order.
A table stores results and stays stale until rebuilt after input changes.

`dbt show --select task_status_summary` **reruns the model SQL as a preview**.
Use the `show --inline` query above with `ref()` to inspect the persisted table instead.
This distinction matters when investigating updates or failures.

## 5. Test data quality

### Purpose

Executable SQL does not guarantee correct data. Encode constraints and detect broken input
rather than silently removing it.

### Action

Read and copy [models/properties.yml](task_analytics/models/properties.yml).
**The YAML below is an explanatory excerpt; do not register it in a second YAML file.**

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

| Generic test | Assertion |
| --- | --- |
| `not_null` | A required value is not NULL |
| `unique` | The key identifying the grain is not duplicated |
| `accepted_values` | Status contains only allowed values |
| `relationships` | Status has a corresponding dimension row |

`accepted_values` and `relationships` do not replace NULL validation; combine them with `not_null`.
In v2, test inputs belong under `arguments:`.

A **singular test** expresses multi-column rules as SQL.
Here is [assert_task_domain_rules.sql](task_analytics/tests/assert_task_domain_rules.sql):

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

Return **violating rows**: zero rows means success; one or more means failure.
Use generic tests for NULLs rather than relying on these comparisons alone.
SQL length measures characters, not a 200-byte limit.

Copy the three singular tests and read what they check:

- UUID representation and title / description lengths:
  [assert_task_domain_rules.sql](task_analytics/tests/assert_task_domain_rules.sql)
- Three dimension statuses, ordering, and completion flags:
  [assert_status_dimension.sql](task_analytics/tests/assert_status_dimension.sql)
- Per-status and overall count consistency:
  [assert_task_summary_consistent.sql](task_analytics/tests/assert_task_summary_consistent.sql)

```shell
cp "$DBT_TASK_EXAMPLE_DIR/models/properties.yml" "$DBT_PROJECT_DIR/models/properties.yml"
cp "$DBT_TASK_EXAMPLE_DIR/tests/assert_task_domain_rules.sql" "$DBT_PROJECT_DIR/tests/"
cp "$DBT_TASK_EXAMPLE_DIR/tests/assert_status_dimension.sql" "$DBT_PROJECT_DIR/tests/"
cp "$DBT_TASK_EXAMPLE_DIR/tests/assert_task_summary_consistent.sql" "$DBT_PROJECT_DIR/tests/"

uv run --locked --no-dev --group dbt dbt test
uv run --locked --no-dev --group dbt dbt build
```

### Verification

`test` checks already-built data: expect 42 successful tests.
`build` combines seeds, models, and tests in dependency order, skipping related downstream
builds if upstream tests fail. `run` alone does not provide that quality gate.

### Exercise: break, investigate, recover

In your **working** `seeds/raw_tasks.csv`, change only the status of ID ending in `001` to `blocked`.

```shell
uv run --locked --no-dev --group dbt dbt build
```

Expect `accepted_values_raw_tasks_status...` to fail and a nonzero exit code.
Failure is the exercise's goal; do not silently turn the value into `todo`.
Inspect `target/run_results.json` and the failed test SQL.
`build` does not roll back the whole project atomically: the seed can change while downstream
tables retain earlier results. Do not present a stale mart as a healthy, up-to-date result.

Restore the input and rerun:

```shell
cp "$DBT_TASK_EXAMPLE_DIR/seeds/raw_tasks.csv" "$DBT_PROJECT_DIR/seeds/raw_tasks.csv"
uv run --locked --no-dev --group dbt dbt build
```

Next, duplicate one row with the same ID and verify that `unique_raw_tasks_id` fails.
Then try a space-only title and verify that `assert_task_domain_rules` fails.
**Restore and successfully rebuild before and after each exercise; finish with the original six rows.**

## 6. Update status and verify reproducibility

### Purpose

Distinguish replacing current state from retaining history.
Verify that full rebuilds do not accumulate duplicate rows.

### Action

Change only the working CSV row ending in `001` from `todo` to `done`.
Leave every other column and row unchanged.

```csv
00000000-0000-0000-0000-000000000001,  Plan ingestion  ,  Define the input columns  ,done
```

First run **only transformations**:

```shell
uv run --locked --no-dev --group dbt dbt run
uv run --locked --no-dev --group dbt dbt show --inline \
  "select status, task_count from {{ ref('task_status_summary') }} order by status_order"
```

Counts are still `2 / 2 / 2`: `run` does not execute `seed` to load the modified CSV.
Now build including the input:

```shell
uv run --locked --no-dev --group dbt dbt build
uv run --locked --no-dev --group dbt dbt show --inline \
  "select status, task_count from {{ ref('task_status_summary') }} order by status_order"
uv run --locked --no-dev --group dbt dbt show --inline \
  "select count(*) as total_tasks, sum(case when is_completed then 1 else 0 end) as completed_tasks, round(100.0 * sum(case when is_completed then 1 else 0 end) / nullif(count(*), 0), 2) as completion_rate_pct from {{ ref('fct_tasks') }}"
```

### Verification

Expect `todo=1`, `in_progress=2`, `done=3`, total six, and 50% completion.
Repeat `build` and the queries: results should not change. This is the example's rerun reproducibility.

This project rebuilds tables / views; it does not use incremental materialization.
An ordinary CSV content change does not need `--full-refresh`.
For seed column type changes requiring table recreation, use `dbt seed --full-refresh`.
For an incremental model, `--full-refresh` means recomputing all rows, a different use case.

**Extra exercise:** restore the original CSV, change both `todo` Tasks to `done`, and build.
Expect `todo=0`, `in_progress=2`, `done=4`. Explain why the zero-count status remains using
the join and `count(tasks.task_id)`. Restore the original CSV and build afterwards.

## 7. Explore local Docs and lineage

### Purpose

Make model meanings and data provenance discoverable by other people.
**dbt Docs** describes the analytics project; the repository's **MkDocs** publishes this tutorial.
They are different sites.

### Action

Generate column information and lineage through v2 static analysis, then export the Docs site:

```shell
uv run --locked --no-dev --group dbt dbt build --static-analysis strict --generate-info-schema
uv run --locked --no-dev --group dbt dbt docs generate --no-compile
uv run --locked --no-dev --group dbt dbt docs serve --target-path "$DBT_PROJECT_DIR/target" --host 127.0.0.1 --port 8580 --no-open
```

Open <http://127.0.0.1:8580>. `--no-compile` exports the index just generated, avoiding an additional
compile replacing the static-analysis results. Missing index data causes an error.
For ordinary site generation, `dbt docs generate` also works on its own.
v2 `docs serve` defaults to `target/` in the current directory, so this repository-root
workflow explicitly sets `--target-path` to the project's generated artifacts.

`--write-catalog` writes catalog metadata; it does not create the browsable site.
See the [official command reference](https://docs.getdbt.com/reference/commands/cmd-docs?version=2.0)
for v2 Docs and static-analysis details.

### Verification and exercises

1. Find the `stg_tasks` model description and the description of `task_title`.
2. Inspect `fct_tasks`' primary key and the status relationship test.
3. Trace `task_status_summary` to its two upstream models, then to the seeds.
4. Use column information to identify the Task key counted by `task_count` and the source of status.
5. Edit a working model description, rebuild, and regenerate to refresh its display.

Stop the server with `Ctrl+C` in its terminal.
Docs are generated under `target/`, which can also contain compiled SQL and test-failure data.
When using real data, do not publish all of `target/` indiscriminately.

### Optional: VS Code

Following the quickstart, install dbt Labs' [official extension](https://marketplace.visualstudio.com/items?itemName=dbtLabsInc.dbt).
Add the **dbt project folder itself** to the VS Code workspace.
Opening only the repository root may prevent the LSP from discovering the nested project.

Provide the same absolute `DBT_PROJECT_DIR` / `DBT_PROFILES_DIR` in VS Code's launch environment
and point the extension's dbt executable setting at the repository's `.venv/bin/dbt`
(`.venv/Scripts/dbt.exe` on Windows).
An `export` in the integrated terminal alone does not update an already-running VS Code process.
Confirm the profile and database path in the extension's connection setup, then open a model
and inspect Lineage / Query Results.
The extension and account features are optional; the CLI and local Docs are sufficient for this tutorial.

## 8. Troubleshooting, recap, and cleanup

| Symptom | Check |
| --- | --- |
| `dbt` runs v1 or another tool | Use this guide's `uv run --locked --no-dev --group dbt dbt --version`, not bare `dbt` |
| Missing profile / environment variable | Reset exports from the repository root; match `profile: task_analytics` to the YAML's top-level key |
| Missing table | Check whether seed / build ran on the same database path, including in other terminals |
| CSV changes have no effect | `run` does not Load; use `build` or `seed` → `run` → `test` |
| DuckDB file-lock error | Close other dbt / Python / DuckDB connections; do not write the same file concurrently from multiple processes |
| Missing column lineage | Build with strict static analysis and `--generate-info-schema`, then use `docs generate --no-compile` |
| Docs reports `no data to serve` | Set `--target-path "$DBT_PROJECT_DIR/target"` to the intended project's artifacts |
| Docs port is occupied | Stop your server or choose `--port 8581` and use the matching URL |
| Seed type change fails | Use `seed --full-refresh` for this learning dataset, then `build` |

You have completed the basics if you can explain:

- Why six Tasks produce three summary rows.
- The different roles of `ref()`, `seed`, `source()`, and SQL models.
- How `run`, `test`, and `build` differ.
- How a join without `unique` / `relationships` checks can produce misleading counts.
- Why current completion rate cannot establish this week's processing time or productivity.

Restore the initial working input and rebuild:

```shell
cp "$DBT_TASK_EXAMPLE_DIR/seeds/raw_tasks.csv" "$DBT_PROJECT_DIR/seeds/raw_tasks.csv"
uv run --locked --no-dev --group dbt dbt build
```

To remove generated artifacts, stop the server and close database connections first.
Using your editor / file manager, delete only `task_analytics.duckdb`, any `task_analytics.duckdb.wal`,
`target/`, and `logs/` **inside the working directory you created**.
Retain SQL / CSV and `build` can regenerate the database.
`dbt clean` removes configured clean targets, not the database file itself.
Do not delete the repository, global profiles, or application data.

Unset this shell's variables when finished. If any were set before the tutorial, restore their previous values instead.

```shell
unset DBT_PROJECT_DIR DBT_PROFILES_DIR DBT_SEND_ANONYMOUS_USAGE_STATS DBT_TASK_EXAMPLE_DIR
```

### Further learning

| Next goal | Additional design needed |
| --- | --- |
| Analyze Tasks from the existing API | Export from the running app process, validate UUID / status, and define extraction time |
| Use an external raw table | Separate Load plus `sources:` / `source()` references and lineage |
| Incremental processing at scale | Change detection, stable unique key, late arrivals, deletion, and replay policy |
| Status history and daily trends | Observation / change timestamps, snapshot / event / CDC choice, and history grain |
| Duration and overdue work | Start / completion / due timestamps, metric denominator, time window, and timezone |
| Regular execution | Orchestration of ingestion and dbt, failure notification, permissions, CI / scheduling |

Do not invent these values or behaviors from Task's current four fields.
