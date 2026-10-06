# LLM evaluation

Evaluate a Microsoft Foundry Prompt Agent with [DeepEval](https://deepeval.com/docs/introduction)
without changing the application's runtime dependencies or the existing unit-test layout.
**Normal pytest and CI never run paid evaluations.** Installing the `eval` dependency group does not enable them.

## Test layers

| Location | Purpose | External LLM calls |
| --- | --- | --- |
| Existing `tests/test_*.py` | Deterministic unit and architecture tests | None |
| `tests/test_evaluation_harness.py` | Collection gate, settings, datasets, mocked Foundry lifecycle | None |
| `tests/test_evaluation_deepeval.py` | Real DeepEval APIs with fake metrics and network access prohibited; skips without DeepEval | None |
| `tests/evaluations/test_*.py` | Real Foundry responses evaluated by an Azure OpenAI judge | Explicit local opt-in only |

The evaluation helpers live beside their tests: `config.py` owns settings and scenario validation,
`foundry.py` owns Azure resources and conversations, and `metrics.py` owns the judge and scoring.
Nothing in the production package imports DeepEval. The existing unit-test settings isolation remains intact;
only the evaluation subtree preserves the real environment and `.env`.

## Prepare access and settings

Complete the [Foundry setup](foundry.md) for an account, project, deployed Responses-compatible model and Entra identity.
The caller needs permission to create, invoke and delete evaluation agents and conversations.
Use a development project, not production. The evaluation client explicitly enables the SDK's preview Agent endpoint.

Separately deploy an Azure OpenAI judge supporting structured output, such as `gpt-4.1-mini`.
Grant the caller **Cognitive Services OpenAI User** on that resource.
Both clients use `DefaultAzureCredential`; local sign-in is described in [common Azure setup](scripts.md#common-setup-for-azure-samples).
No API key or Confident AI account is required.

Set these nonsecret values in the repository's ignored `.env`. Replace the placeholders before execution:

```dotenv
FOUNDRY_PROJECT_ENDPOINT=https://<account>.services.ai.azure.com/api/projects/<project>
LLM_EVAL_AGENT_MODEL=gpt-5-mini
LLM_EVAL_JUDGE_ENDPOINT=https://<judge-resource>.openai.azure.com
LLM_EVAL_JUDGE_DEPLOYMENT=<judge-deployment-name>
LLM_EVAL_JUDGE_MODEL=gpt-4.1-mini
LLM_EVAL_JUDGE_API_VERSION=2024-10-21
```

The Agent model setting is the deployed model name. The judge's deployment name and underlying model name
are separate settings. The judge endpoint is the Azure OpenAI resource root, **not** the Foundry project URL
or an `/openai/v1/` URL. This native DeepEval model uses the versioned Azure OpenAI API and
`https://cognitiveservices.azure.com/.default`; the Foundry SDK uses `https://ai.azure.com/.default`.
Settings resolve from environment variables before `.env` before defaults. Missing or invalid settings fail rather than skip.

If startup reports `LLM_EVAL_JUDGE_ENDPOINT` or `LLM_EVAL_JUDGE_DEPLOYMENT`, those nonsecret values are missing.
Add them to `.env`; installing `eval` does not populate them. Choose a deployment that actually exists,
and set `LLM_EVAL_JUDGE_MODEL` to its underlying model, for example `gpt-4o` for a `gpt-4o` deployment.
A Foundry account's resource-root endpoint `https://<account>.services.ai.azure.com` also works for the
versioned Azure OpenAI API. Do not include `/api/projects/<project>` in the judge endpoint.
Configuration errors identify the required environment variables without displaying their values or a settings-library traceback.

Optional settings are `LLM_EVAL_TIMEOUT_SECONDS=60` and `LLM_EVAL_MAX_OUTPUT_TOKENS=512`.
The judge uses temperature zero, sequential metrics and a 2048-token completion limit per request.

## Run evaluations

```shell
# Ordinary tests, no paid calls
make test

# Install the optional evaluation dependencies, without enabling evaluations
uv sync --locked --no-dev --group eval

# List the seven evaluation cases without authentication or LLM calls
make test-eval EVAL_ARGS=--collect-only

# Paid: one small case first
make test-eval EVAL_ARGS='-m llm_eval_smoke'

# Paid: all cases
make test-eval

# Paid: select a scenario with pytest's usual filter
make test-eval EVAL_ARGS='-k provided-context'
```

`make test-eval` runs the official `deepeval test run` command and passes `--run-llm-evals` to pytest.
The flag is required even when selecting a test file directly; `-m llm_eval` alone does not authorize calls.
The ordinary pytest configuration disables the DeepEval plugin and excludes evaluation modules before import.
The dedicated command enables the plugin, removes unit-test coverage options, disables anonymous telemetry,
dotenv/legacy-key autoload in DeepEval and Confident AI uploads, and evaluates locally.
The repository's own settings still read `.env`. No global `deepeval set-*` configuration is needed.

## Evaluation patterns

| Pattern | Metric or assertion | Required evidence |
| --- | --- | --- |
| Single-turn relevance | `AnswerRelevancyMetric` | Actual input and answer |
| Reference correctness, including unknown information | `GEval` | Independently authored expected answer |
| Instruction adherence | `GEval` with fixed evaluation steps | Explicit language and format requirements |
| Structured output | JSON parsing and exact object contract before the judge | Expected keys and values |
| Faithfulness to provided material | `FaithfulnessMetric` and correctness | The same fixed reference material supplied to the Agent |
| Multi-turn retention | `ConversationalTestCase`, `KnowledgeRetentionMetric`, required-value assertions | Fixed user prompts and real assistant turns in one conversation |

The datasets contain six single-turn cases and one three-turn conversation. Each case uses only one or two
relevant metrics, with an initial threshold of `0.7`. Fixed references are reviewed inputs, never generated
from the answer being scored. Scenario IDs, requirements and thresholds belong in the version-controlled JSON datasets.
Pure JSON and required-value contracts are checked with ordinary assertions before spending judge tokens.

The provided-context case evaluates generation, not an actual retriever. It does not establish RAG retrieval quality.
The initial suite has no tool-using Agent or trajectory instrumentation.

## Cost, results and calibration

Both the Agent and the judge consume tokens. A full run makes nine Agent response calls, plus multiple judge
requests per metric; a single metric does not necessarily mean a single request. Cases and metrics run sequentially.
SDK/provider retries are bounded; do not add repeat, parallel or ignore-errors flags as a default.
Timeouts and output limits reduce exposure, but are not a hard total spending cap.
DeepEval caching is off by default. An explicitly enabled judge cache still does not avoid Agent inference costs.
Do not reuse results across prompt, Agent version, judge deployment/model, rubric or dataset changes.

The standard JSON reports and `junit.xml` are written under ignored `artifacts/evaluations/`.
DeepEval's local state in `.deepeval/` is also ignored. Reports include score, threshold, reason and metadata:
Agent name/version/model, judge model/deployment/API version, instructions, dataset SHA-256 and rubric version.
Metric failures produce a nonzero exit code. The collection-only command may print "No test cases found" after
listing the cases because it did not execute any assertions; that is expected.

Temperature zero does not make LLM judging deterministic. Review known-good and known-bad answers manually
to calibrate the rubric and thresholds, inspect borderline cases, and record the deployed model versions.
Never rerun until a case passes or lower a threshold automatically. A judge score is not a security or correctness proof.
The offline tests verify plumbing, not model quality.

Only synthetic data ships in these datasets. Inputs and answers are sent to the configured Azure judge and
may appear in local reports; remove secrets and personal data before adding scenarios. Keep reports private.

Each case creates an isolated `deepeval-<uuid>` Agent and its own conversation. The suite deletes only resources it
created and closes clients and credentials even on failures. Cleanup failures report the resource ID without raw SDK details;
other cleanup actions still run, and an existing evaluation exception is preserved. After a forced process termination,
check the development project for the reported evaluation Agent or conversation and delete only those owned resources
through the Foundry portal or the SDK. Process termination cannot guarantee cleanup.

## CI and extension points

Default CI runs deterministic tests. A separate compatibility job on Python 3.10 and 3.14 installs the optional
group, verifies fake Agent/metric flows, real DeepEval assertions and CLI reports with network access prohibited,
type-checks the evaluation subtree, and collects the real suite. No Azure credentials are supplied.
The gate rejects live execution when `CI` or `GITHUB_ACTIONS` is set; collection-only is allowed.

```shell
uv run --locked --group eval pytest tests/test_evaluation_harness.py tests/test_evaluation_deepeval.py --no-cov
make lint-eval
```

For an existing Agent, add an explicit name/version mode that does not create or delete that Agent, and record
its exact instructions/version. For real RAG, capture the actual retrieved chunks before adding contextual
precision/recall. For tools, capture actual and expected tool calls before adding tool/argument correctness.
Task completion and efficiency metrics require sufficient actual traces; a client-side wrapper does not reveal
the hosted Agent's internal steps. Never fabricate these inputs.

A future paid CI path should use an approved `workflow_dispatch`, OIDC, a protected environment, a small smoke
dataset and an explicit cost gate. Add a separate CI authorization option then; do not remove the default-off gate.
This template deliberately does not provide a paid workflow, scheduled evaluations or conversation simulation.

References: [pytest and CI](https://deepeval.com/docs/evaluation-unit-testing-in-ci-cd),
[metric selection](https://deepeval.com/docs/metrics-introduction),
[Azure OpenAI](https://deepeval.com/integrations/models/azure-openai),
[settings](https://deepeval.com/docs/environment-variables).
