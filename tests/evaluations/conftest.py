import os
from collections.abc import Generator

import pytest

os.environ.update(
    DEEPEVAL_TELEMETRY_OPT_OUT="1",
    DEEPEVAL_DISABLE_DOTENV="1",
    DEEPEVAL_DISABLE_LEGACY_KEYFILE="1",
    DEEPEVAL_EVAL_MODE="llm",
    DEEPEVAL_RETRY_MAX_ATTEMPTS="2",
    DEEPEVAL_PER_ATTEMPT_TIMEOUT_SECONDS_OVERRIDE="60",
)
os.environ.pop("CONFIDENT_API_KEY", None)


@pytest.fixture(autouse=True)
def isolated_settings() -> Generator[None, None, None]:
    from template_azure_python.settings import get_azure_settings, get_project_settings

    get_azure_settings.cache_clear()
    get_project_settings.cache_clear()
    try:
        yield
    finally:
        get_azure_settings.cache_clear()
        get_project_settings.cache_clear()


@pytest.fixture
def evaluation_settings(isolated_settings):
    from pydantic import ValidationError

    from tests.evaluations.config import EvaluationSettings

    try:
        return EvaluationSettings()
    except ValidationError as error:
        messages = []
        for issue in error.errors(include_input=False, include_context=False, include_url=False):
            name = str(issue["loc"][0]) if issue["loc"] else "settings"
            field = EvaluationSettings.model_fields.get(name)
            if field is not None:
                name = (
                    field.validation_alias
                    if isinstance(field.validation_alias, str)
                    else f"{EvaluationSettings.model_config.get('env_prefix', '')}{name}".upper()
                )
            messages.append(f"{name}: {issue['msg']}")
        pytest.fail(
            "Invalid LLM evaluation settings:\n"
            + "\n".join(messages)
            + "\nConfigure these nonsecret values in .env; see docs/evaluation.md (or evaluation.ja.md).",
            pytrace=False,
        )


@pytest.fixture
def evaluation_agent(evaluation_settings, scenario):
    from tests.evaluations.foundry import create_evaluation_agent

    with create_evaluation_agent(evaluation_settings, scenario.instructions) as agent:
        yield agent


@pytest.fixture
def judge(evaluation_settings):
    from tests.evaluations.metrics import create_judge

    with create_judge(evaluation_settings) as model:
        yield model
