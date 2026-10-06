import pytest

from tests.evaluations.config import load_scenarios

pytestmark = pytest.mark.llm_eval


@pytest.mark.parametrize("scenario", load_scenarios("conversation.json"), ids=lambda scenario: scenario.id)
def test_foundry_conversation(scenario, evaluation_agent, judge) -> None:
    from deepeval import assert_test

    from tests.evaluations.metrics import conversation_case, conversation_metric, run_metadata

    turns = evaluation_agent.run(scenario)
    scenario.assert_output(turns[-1].content)
    test_case = conversation_case(scenario, turns, run_metadata(evaluation_agent, scenario, "conversation.json"))
    assert_test(test_case=test_case, metrics=[conversation_metric(scenario, judge)], run_async=False)
