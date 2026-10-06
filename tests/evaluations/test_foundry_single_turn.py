import pytest

from tests.evaluations.config import load_scenarios

pytestmark = pytest.mark.llm_eval


@pytest.mark.parametrize(
    "scenario",
    [
        pytest.param(scenario, id=scenario.id, marks=pytest.mark.llm_eval_smoke if scenario.smoke else [])
        for scenario in load_scenarios("single_turn.json")
    ],
)
def test_foundry_single_turn(scenario, evaluation_agent, judge) -> None:
    from deepeval import assert_test

    from tests.evaluations.metrics import run_metadata, single_turn_case, single_turn_metrics

    turns = evaluation_agent.run(scenario)
    scenario.assert_output(turns[-1].content)
    test_case = single_turn_case(scenario, turns, run_metadata(evaluation_agent, scenario, "single_turn.json"))
    assert_test(test_case=test_case, metrics=single_turn_metrics(scenario, judge), run_async=False)
