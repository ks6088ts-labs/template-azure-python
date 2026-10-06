import json
import socket
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tests.evaluations.config import load_scenarios
from tests.evaluations.foundry import AgentTurn, FoundryAgent
from tests.test_evaluation_harness import evaluation_settings


@pytest.fixture(autouse=True)
def offline_deepeval(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setenv("DEEPEVAL_TELEMETRY_OPT_OUT", "1")
    monkeypatch.setenv("DEEPEVAL_DISABLE_DOTENV", "1")
    monkeypatch.setenv("DEEPEVAL_DISABLE_LEGACY_KEYFILE", "1")
    monkeypatch.delenv("CONFIDENT_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)

    def deny_network(*args, **kwargs):
        raise AssertionError("Offline evaluation tests must not access the network")

    monkeypatch.setattr(socket.socket, "connect", deny_network)
    monkeypatch.setattr(socket.socket, "connect_ex", deny_network)
    return pytest.importorskip("deepeval")


def test_native_judge_accepts_entra_provider_and_closes_transport() -> None:
    from httpx import Client

    from tests.evaluations.metrics import create_judge

    transport = Client()
    with (
        patch("tests.evaluations.metrics.DefaultAzureCredential") as credential_type,
        patch("tests.evaluations.metrics.get_bearer_token_provider") as provider,
        patch("tests.evaluations.metrics.Client", return_value=transport),
    ):
        with create_judge(evaluation_settings()) as judge:
            assert judge.deployment_name == "judge-deployment"
            assert judge.azure_ad_token_provider is provider.return_value
            credential_type.return_value.get_token.assert_not_called()
        provider.assert_called_once_with(credential_type.return_value, "https://cognitiveservices.azure.com/.default")
        assert transport.is_closed
        credential_type.return_value.close.assert_called_once()


def test_all_metric_factories_and_test_case_types_are_compatible() -> None:
    from deepeval.models import AzureOpenAIModel

    from tests.evaluations.metrics import conversation_case, conversation_metric, single_turn_case, single_turn_metrics

    judge = AzureOpenAIModel(
        model="gpt-4.1-mini",
        deployment_name="offline",
        base_url="https://example.openai.azure.com",
        api_version="2024-10-21",
        azure_ad_token_provider=lambda: "unused-offline-token",
    )
    for scenario in load_scenarios("single_turn.json"):
        turns = [
            AgentTurn("user", scenario.agent_prompt(scenario.prompts[0])),
            AgentTurn("assistant", "Example answer"),
        ]
        test_case = single_turn_case(scenario, turns, {"run": "offline"})
        assert test_case.name == scenario.id
        assert test_case.retrieval_context == (scenario.context or None)
        metrics = single_turn_metrics(scenario, judge)
        assert len(metrics) == len(scenario.metrics)
        assert all(metric.model is judge and not metric.async_mode for metric in metrics)
        assert all(metric.threshold == scenario.threshold for metric in metrics)
    scenario = load_scenarios("conversation.json")[0]
    turns = [AgentTurn("user", "Remember Kyoto"), AgentTurn("assistant", "Kyoto")]
    assert len(conversation_case(scenario, turns, {}).turns) == 2
    assert conversation_metric(scenario, judge).model is judge


def offline_metric(score: float):
    from deepeval.metrics import BaseMetric

    class OfflineMetric(BaseMetric):
        threshold = 0.7
        async_mode = False
        verbose_mode = False
        evaluation_model = "offline"

        def measure(self, test_case, *args, **kwargs):
            self.score = score
            self.reason = "Offline assertion wiring check, not a quality evaluation"
            return score

        async def a_measure(self, test_case, *args, **kwargs):
            raise AssertionError("The suite must evaluate sequentially")

    return OfflineMetric()


@pytest.mark.parametrize("score", [0.69, 0.7, 0.9])
def test_assert_test_enforces_threshold_without_an_llm(offline_deepeval, score: float) -> None:
    from deepeval.test_case import LLMTestCase

    test_case = LLMTestCase(input="Question", actual_output="Answer")
    if score < 0.7:
        with pytest.raises(AssertionError):
            offline_deepeval.assert_test(test_case=test_case, metrics=[offline_metric(score)], run_async=False)
    else:
        offline_deepeval.assert_test(test_case=test_case, metrics=[offline_metric(score)], run_async=False)


def test_metadata_records_agent_judge_dataset_and_rubric() -> None:
    from tests.evaluations.metrics import run_metadata

    scenario = load_scenarios("single_turn.json")[0]
    agent = FoundryAgent(client=MagicMock(), name="owned-agent", version="7", settings=evaluation_settings())
    metadata = run_metadata(agent, scenario, "single_turn.json")
    assert metadata["agent_version"] == "7"
    assert metadata["judge_model"] == "gpt-4.1-mini"
    assert metadata["rubric_version"] == "1"
    assert len(metadata["dataset_sha256"]) == 64


def test_single_turn_test_functions_run_with_fake_agent_and_metrics() -> None:
    from tests.evaluations.test_foundry_single_turn import test_foundry_single_turn

    for scenario in load_scenarios("single_turn.json"):
        answer = json.dumps(scenario.expected_json) if scenario.expected_json else (scenario.expected_output or "Paris")
        agent = MagicMock(spec=FoundryAgent)
        agent.name = "offline-agent"
        agent.version = "1"
        agent.settings = evaluation_settings()
        agent.run.return_value = [
            AgentTurn("user", scenario.agent_prompt(scenario.prompts[0])),
            AgentTurn("assistant", answer),
        ]
        with patch("tests.evaluations.metrics.single_turn_metrics", return_value=[offline_metric(0.9)]):
            test_foundry_single_turn(scenario, agent, MagicMock())
        agent.run.assert_called_once_with(scenario)


def test_conversation_test_function_runs_with_fake_agent_and_metric() -> None:
    from deepeval.metrics import BaseConversationalMetric

    from tests.evaluations.test_foundry_conversation import test_foundry_conversation

    class OfflineConversationMetric(BaseConversationalMetric):
        threshold = 0.7
        async_mode = False
        verbose_mode = False

        def measure(self, test_case, *args, **kwargs):
            self.score = 0.9
            self.reason = "Offline conversation wiring check"
            return self.score

        async def a_measure(self, test_case, *args, **kwargs):
            raise AssertionError("The suite must evaluate sequentially")

    scenario = load_scenarios("conversation.json")[0]
    agent = MagicMock(spec=FoundryAgent)
    agent.name = "offline-agent"
    agent.version = "1"
    agent.settings = evaluation_settings()
    agent.run.return_value = [
        turn
        for prompt in scenario.prompts
        for turn in [AgentTurn("user", prompt), AgentTurn("assistant", "Kyoto rail")]
    ]
    with patch("tests.evaluations.metrics.conversation_metric", return_value=OfflineConversationMetric()):
        test_foundry_conversation(scenario, agent, MagicMock())
    agent.run.assert_called_once_with(scenario)


@pytest.mark.parametrize("score,exit_code", [(0.9, 0), (0.69, 1)])
def test_official_cli_saves_results_and_propagates_failure(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, score: float, exit_code: int
) -> None:
    root = Path(__file__).resolve().parents[1]
    monkeypatch.chdir(pytester.path)
    monkeypatch.setenv("DEEPEVAL_RESULTS_FOLDER", str(pytester.path / "results"))
    pytester.makeini("[pytest]\n")
    pytester.makeconftest(
        "import socket\ndef deny_network(*args, **kwargs):\n"
        "    raise AssertionError('Offline CLI test attempted a network connection')\n"
        "socket.socket.connect = deny_network\nsocket.socket.connect_ex = deny_network\n"
    )
    pytester.makepyfile(
        test_offline_eval=(
            f"import sys\nsys.path.insert(0, {str(root)!r})\n"
            "from deepeval import assert_test\nfrom deepeval.test_case import LLMTestCase\n"
            "from tests.test_evaluation_deepeval import offline_metric\n"
            "def test_offline():\n"
            f"    assert_test(test_case=LLMTestCase(input='Question', actual_output='Answer'), "
            f"metrics=[offline_metric({score})], run_async=False)\n"
        )
    )
    result = pytester.run(
        sys.executable,
        "-c",
        "from deepeval.cli.main import app; app()",
        "test",
        "run",
        "test_offline_eval.py",
        "--override-ini=addopts=-ra --strict-markers",
        "--capture=fd",
        "--junitxml=result.xml",
        timeout=60,
    )
    assert result.ret == exit_code, result.stdout.str() + result.stderr.str()
    assert (pytester.path / "result.xml").exists()
    assert list((pytester.path / "results").glob("*.json"))
