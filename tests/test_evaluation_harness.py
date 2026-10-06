import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest
from pydantic import ValidationError

from tests import conftest as hooks
from tests.evaluations.config import EvaluationSettings, Scenario, dataset_revision, load_scenarios
from tests.evaluations.foundry import ResourceScope, create_evaluation_agent


def test_default_pytest_does_not_load_deepeval_plugin(pytestconfig: pytest.Config) -> None:
    assert not pytestconfig.pluginmanager.hasplugin("deepeval")


@pytest.fixture
def gated_suite(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> pytest.Pytester:
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    pytester.makeini("[pytest]\nmarkers = llm_eval: paid evaluation\n")
    pytester.makeconftest(
        "import os\nfrom pathlib import Path\nimport pytest\n"
        + "\n".join(
            inspect.getsource(hook)
            for hook in (hooks.pytest_addoption, hooks.pytest_configure, hooks.pytest_ignore_collect)
        )
    )
    pytester.makepyfile(**{"tests/test_offline": "def test_offline(): pass"})
    return pytester


@pytest.mark.parametrize("arguments", [[], ["-m", "llm_eval"]])
def test_default_collection_never_imports_evaluations(gated_suite: pytest.Pytester, arguments: list[str]) -> None:
    gated_suite.makepyfile(**{"tests/evaluations/test_paid": "raise RuntimeError('PAID_MODULE_IMPORTED')"})
    result = gated_suite.runpytest_subprocess(*arguments)
    assert "PAID_MODULE_IMPORTED" not in result.stdout.str()
    assert result.ret in (pytest.ExitCode.OK, pytest.ExitCode.NO_TESTS_COLLECTED)


@pytest.mark.parametrize(
    "target", ["tests/evaluations", "tests/evaluations/test_paid.py", "tests/evaluations/test_paid.py::test_paid"]
)
def test_direct_evaluation_paths_require_opt_in(gated_suite: pytest.Pytester, target: str) -> None:
    gated_suite.makepyfile(**{"tests/evaluations/test_paid": "raise RuntimeError('PAID_MODULE_IMPORTED')"})
    result = gated_suite.runpytest_subprocess(target)
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert "--run-llm-evals" in result.stderr.str()
    assert "PAID_MODULE_IMPORTED" not in result.stdout.str()


def test_explicit_opt_in_collects_evaluations(gated_suite: pytest.Pytester) -> None:
    gated_suite.makepyfile(**{"tests/evaluations/test_paid": "def test_paid(): pass"})
    result = gated_suite.runpytest_subprocess("tests/evaluations", "--run-llm-evals")
    result.assert_outcomes(passed=1)


@pytest.mark.parametrize("variable", ["CI", "GITHUB_ACTIONS"])
def test_ci_rejects_live_evaluations(
    gated_suite: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, variable: str
) -> None:
    monkeypatch.setenv(variable, "true")
    result = gated_suite.runpytest_subprocess("--run-llm-evals")
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert "local-only" in result.stderr.str()


def test_ci_allows_collection_without_running_fixtures(
    gated_suite: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CI", "true")
    gated_suite.makepyfile(
        **{
            "tests/evaluations/test_paid": (
                "import pytest\n@pytest.fixture\ndef paid(): raise RuntimeError('PAID_FIXTURE_CALLED')\n"
                "def test_paid(paid): pass"
            )
        }
    )
    result = gated_suite.runpytest_subprocess("tests/evaluations", "--run-llm-evals", "--collect-only")
    assert result.ret == pytest.ExitCode.OK
    assert "PAID_FIXTURE_CALLED" not in result.stdout.str()


@pytest.mark.parametrize("invalid_endpoint", [False, True])
def test_live_settings_errors_name_environment_variables_without_exposing_values(
    gated_suite: pytest.Pytester, invalid_endpoint: bool
) -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "tests/evaluations/conftest.py").read_text(encoding="utf-8")
    gated_suite.makefile(
        ".py",
        **{"tests/evaluations/conftest": f"import sys\nsys.path.insert(0, {str(root)!r})\n" + source},
    )
    dotenv = "FOUNDRY_PROJECT_ENDPOINT=https://example.services.ai.azure.com/api/projects/example\n"
    if invalid_endpoint:
        dotenv += (
            "LLM_EVAL_JUDGE_ENDPOINT=https://user:do-not-disclose@example.openai.azure.com\n"
            "LLM_EVAL_JUDGE_DEPLOYMENT=example\n"
        )
    gated_suite.makefile("", **{".env": dotenv})
    gated_suite.makepyfile(**{"tests/evaluations/test_settings": "def test_settings(evaluation_settings): pass"})
    result = gated_suite.runpytest_subprocess("tests/evaluations", "--run-llm-evals")
    result.assert_outcomes(errors=1)
    output = result.stdout.str()
    assert "LLM_EVAL_JUDGE_ENDPOINT" in output
    assert "Configure these nonsecret values in .env" in output
    assert "do-not-disclose" not in output
    assert "pydantic_settings/main.py" not in output
    if not invalid_endpoint:
        assert "LLM_EVAL_JUDGE_DEPLOYMENT" in output


def test_fixed_datasets_cover_basic_patterns() -> None:
    single = load_scenarios("single_turn.json")
    conversations = load_scenarios("conversation.json")
    assert len(single) == 6
    assert len(conversations) == 1
    assert sum(scenario.smoke for scenario in single) == 1
    assert {metric for scenario in single + conversations for metric in scenario.metrics} == {
        "relevancy",
        "correctness",
        "instructions",
        "faithfulness",
        "retention",
    }
    assert len(dataset_revision("single_turn.json")) == 64


@pytest.mark.parametrize(
    "overrides",
    [
        {"metrics": ["correctness"]},
        {"metrics": ["faithfulness"]},
        {"metrics": ["instructions"]},
        {"metrics": ["retention"]},
        {"metrics": ["relevancy", "relevancy"]},
        {"metrics": ["nonexistent"]},
        {"prompts": []},
        {"prompts": ["first", "second"]},
        {"threshold": 0},
        {"threshold": 1.1},
        {"expected_json": {"city": "Paris"}},
    ],
)
def test_scenarios_reject_missing_or_invalid_metric_inputs(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Scenario.model_validate(
            {
                "id": "example",
                "instructions": "Answer briefly",
                "prompts": ["Hello"],
                "metrics": ["relevancy"],
                **overrides,
            }
        )


@pytest.mark.parametrize("output", ["", "```json\n{}\n```", '{"capital": "Berlin", "country": "France"}'])
def test_deterministic_output_contract_rejects_bad_answers(output: str) -> None:
    scenario = next(item for item in load_scenarios("single_turn.json") if item.expected_json is not None)
    with pytest.raises((AssertionError, ValueError)):
        scenario.assert_output(output)


def test_faithfulness_uses_context_supplied_to_the_agent() -> None:
    scenario = next(item for item in load_scenarios("single_turn.json") if item.context)
    prompt = scenario.agent_prompt(scenario.prompts[0])
    assert all(context in prompt for context in scenario.context)


def evaluation_settings(**overrides: object) -> EvaluationSettings:
    return EvaluationSettings.model_validate(
        {
            "FOUNDRY_PROJECT_ENDPOINT": "https://example.services.ai.azure.com/api/projects/example",
            "judge_endpoint": "https://example.openai.azure.com",
            "judge_deployment": "judge-deployment",
            **overrides,
        }
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"judge_endpoint": "http://example.openai.azure.com"},
        {"judge_endpoint": "https://<resource>.openai.azure.com"},
        {"judge_endpoint": "https://example.services.ai.azure.com/api/projects/example"},
        {"judge_endpoint": "https://user:secret@example.openai.azure.com"},
        {"FOUNDRY_PROJECT_ENDPOINT": "https://example.openai.azure.com"},
        {"judge_deployment": " "},
        {"judge_deployment": "<judge-deployment-name>"},
        {"agent_model": "<agent-model>"},
        {"timeout_seconds": 0},
    ],
)
def test_evaluation_settings_fail_before_authentication(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        evaluation_settings(**overrides)


@pytest.fixture
def foundry_clients():
    project = MagicMock()
    project.agents.create_version.return_value = SimpleNamespace(version="1")
    client = project.get_openai_client.return_value
    client.conversations.create.return_value.id = "evaluation-conversation"
    client.responses.create.return_value.output_text = "Paris"
    with (
        patch("tests.evaluations.foundry.DefaultAzureCredential") as credential_type,
        patch("tests.evaluations.foundry.AIProjectClient", return_value=project) as project_type,
    ):
        yield project, client, credential_type, project_type


def test_agent_uses_preview_and_cleans_up_owned_resources(foundry_clients) -> None:
    project, client, credential_type, project_type = foundry_clients
    settings = evaluation_settings()
    scenario = load_scenarios("single_turn.json")[0]
    with create_evaluation_agent(settings, scenario.instructions) as agent:
        turns = agent.run(scenario)
        assert turns[-1].content == "Paris"
        assert agent.name.startswith("deepeval-")
        assert len(agent.name) < 63
        assert agent.version == "1"
    project_type.assert_called_once_with(
        endpoint=settings.project_endpoint, credential=credential_type.return_value, allow_preview=True
    )
    client.conversations.delete.assert_called_once_with("evaluation-conversation")
    project.agents.delete.assert_called_once_with(agent_name=agent.name)
    client.close.assert_called_once_with()
    project.close.assert_called_once_with()
    credential_type.return_value.close.assert_called_once_with()


def test_agent_preserves_conversation_within_each_scenario(foundry_clients) -> None:
    project, client, _, _ = foundry_clients
    scenario = load_scenarios("conversation.json")[0]
    client.responses.create.side_effect = [
        SimpleNamespace(output_text=text) for text in ["Remembered", "Pack", "Kyoto rail"]
    ]
    with create_evaluation_agent(evaluation_settings(), scenario.instructions) as agent:
        turns = agent.run(scenario)
    assert [turn.role for turn in turns] == ["user", "assistant"] * 3
    assert client.responses.create.call_args_list == [
        call(conversation="evaluation-conversation", input=prompt, max_output_tokens=512) for prompt in scenario.prompts
    ]
    scenario.assert_output(turns[-1].content)
    project.agents.delete.assert_called_once()


@pytest.mark.parametrize("error", [RuntimeError("API failed"), KeyboardInterrupt()])
def test_agent_response_failures_still_delete_conversation_and_agent(foundry_clients, error: BaseException) -> None:
    project, client, credential_type, _ = foundry_clients
    client.responses.create.side_effect = error
    with pytest.raises(type(error)):
        with create_evaluation_agent(evaluation_settings(), "Answer briefly") as agent:
            agent.run(load_scenarios("single_turn.json")[0])
    client.conversations.delete.assert_called_once()
    project.agents.delete.assert_called_once()
    client.close.assert_called_once()
    project.close.assert_called_once()
    credential_type.return_value.close.assert_called_once()


@pytest.mark.parametrize("operation", ["create_version", "get_openai_client"])
def test_partial_initialization_closes_every_created_client(foundry_clients, operation: str) -> None:
    project, client, credential_type, _ = foundry_clients
    target = project.agents.create_version if operation == "create_version" else project.get_openai_client
    target.side_effect = RuntimeError("Setup failed")
    with pytest.raises(RuntimeError, match="Setup failed"):
        with create_evaluation_agent(evaluation_settings(), "Answer briefly"):
            pytest.fail("Should not yield a broken agent")
    assert project.agents.delete.call_count == (operation == "get_openai_client")
    client.close.assert_not_called()
    project.close.assert_called_once()
    credential_type.return_value.close.assert_called_once()


def test_cleanup_attempts_all_actions_and_reports_failures() -> None:
    closing = MagicMock()
    broken = MagicMock(side_effect=RuntimeError("Sensitive service details"))
    with pytest.raises(RuntimeError, match="conversation example") as captured:
        with ResourceScope() as resources:
            resources.register_cleanup("client", closing)
            resources.register_cleanup("conversation example", broken)
    closing.assert_called_once()
    assert "Sensitive service details" not in str(captured.value)


def test_cleanup_failure_does_not_hide_primary_failure(caplog: pytest.LogCaptureFixture) -> None:
    broken = MagicMock(side_effect=RuntimeError("Cleanup failed"))
    with pytest.raises(ValueError, match="Original evaluation failure"):
        with ResourceScope() as resources:
            resources.register_cleanup("agent owned-id", broken)
            raise ValueError("Original evaluation failure")
    assert "agent owned-id" in caplog.text
