import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator
from pydantic_settings import SettingsConfigDict

from template_azure_python.settings._base import EnvironmentSettings

NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
MetricName = Literal["relevancy", "correctness", "instructions", "faithfulness", "retention"]
DATASETS = Path(__file__).parent / "datasets"
RUBRIC_VERSION = "1"


class EvaluationSettings(EnvironmentSettings):
    model_config = SettingsConfigDict(env_prefix="LLM_EVAL_")

    project_endpoint: NonEmpty = Field(validation_alias="FOUNDRY_PROJECT_ENDPOINT")
    agent_model: NonEmpty = "gpt-5-mini"
    judge_endpoint: NonEmpty
    judge_deployment: NonEmpty
    judge_model: NonEmpty = "gpt-4.1-mini"
    judge_api_version: NonEmpty = "2024-10-21"
    timeout_seconds: float = Field(default=60, gt=0, le=300)
    max_output_tokens: int = Field(default=512, ge=64, le=4096)

    @field_validator("agent_model", "judge_deployment", "judge_model", "judge_api_version")
    @classmethod
    def reject_placeholders(cls, value: str) -> str:
        if "<" in value or ">" in value:
            raise ValueError("Replace model, deployment and API-version placeholders before evaluation")
        return value

    @field_validator("project_endpoint", "judge_endpoint")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        parsed = urlparse(value)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or "<" in value
            or ">" in value
        ):
            raise ValueError("Use a real HTTPS endpoint without credentials, query parameters or placeholders")
        return value.rstrip("/")

    @model_validator(mode="after")
    def validate_endpoint_types(self) -> "EvaluationSettings":
        if "/api/projects/" not in urlparse(self.project_endpoint).path:
            raise ValueError("FOUNDRY_PROJECT_ENDPOINT must contain /api/projects/")
        if urlparse(self.judge_endpoint).path:
            raise ValueError("LLM_EVAL_JUDGE_ENDPOINT must be the Azure OpenAI resource root, not a project URL")
        return self


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    instructions: NonEmpty
    prompts: list[NonEmpty] = Field(min_length=1, max_length=3)
    metrics: list[MetricName] = Field(min_length=1, max_length=2)
    expected_output: NonEmpty | None = None
    context: list[NonEmpty] = Field(default_factory=list)
    requirements: list[NonEmpty] = Field(default_factory=list)
    expected_json: dict[str, str] | None = None
    required_substrings: list[NonEmpty] = Field(default_factory=list)
    threshold: float = Field(default=0.7, gt=0, le=1)
    smoke: bool = False

    @model_validator(mode="after")
    def validate_metric_inputs(self) -> "Scenario":
        if len(set(self.metrics)) != len(self.metrics):
            raise ValueError("Metric names must be unique")
        if "correctness" in self.metrics and self.expected_output is None:
            raise ValueError("Correctness requires an independently authored expected_output")
        if "instructions" in self.metrics and not self.requirements:
            raise ValueError("Instruction adherence requires requirements")
        if "faithfulness" in self.metrics and not self.context:
            raise ValueError("Faithfulness requires the context actually supplied to the agent")
        if len(self.prompts) > 1 and self.metrics != ["retention"]:
            raise ValueError("Multi-turn scenarios use retention; single-turn metrics cannot score a conversation")
        if "retention" in self.metrics and len(self.prompts) < 2:
            raise ValueError("Retention requires multiple user turns")
        if self.expected_json is not None and "instructions" not in self.metrics:
            raise ValueError("Structured-output scenarios require the instructions metric")
        if self.smoke and len(self.prompts) != 1:
            raise ValueError("Smoke scenarios must be single-turn")
        return self

    def agent_prompt(self, prompt: str) -> str:
        if not self.context:
            return prompt
        return "Reference material:\n" + "\n\n".join(self.context) + "\n\nQuestion:\n" + prompt

    def assert_output(self, output: str) -> None:
        assert output.strip(), "The agent returned empty text"
        for value in self.required_substrings:
            assert value.casefold() in output.casefold(), f"Missing required value: {value}"
        if self.expected_json is not None:
            actual = json.loads(output)
            assert actual == self.expected_json, "JSON output does not match the required object"


def load_scenarios(filename: str) -> list[Scenario]:
    document = json.loads((DATASETS / filename).read_text(encoding="utf-8"))
    scenarios = [Scenario.model_validate(item) for item in document]
    if not scenarios or len({scenario.id for scenario in scenarios}) != len(scenarios):
        raise ValueError("Datasets must be nonempty and contain unique scenario IDs")
    return scenarios


def dataset_revision(filename: str) -> str:
    return hashlib.sha256((DATASETS / filename).read_bytes()).hexdigest()
