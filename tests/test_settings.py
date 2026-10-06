import os
from pathlib import Path

import pytest
from pydantic import SecretStr
from pydantic_settings import BaseSettings

from template_azure_python.settings import (
    AzureSettings,
    ProjectSettings,
    get_azure_settings,
    get_project_settings,
    telemetry_environment,
)
from template_azure_python.settings.azure import (
    ApplicationInsightsSettings,
    AzureMonitorSettings,
    CosmosDBSettings,
    EventGridSettings,
    EventHubsSettings,
    FoundrySettings,
    LogAnalyticsSettings,
    NetworkWatcherSettings,
    QueueStorageSettings,
    ResourceSettings,
    ServiceBusSettings,
)
from template_azure_python.settings.azure._base import AzureServiceSettings
from tests.evaluations.config import EvaluationSettings

AZURE_SERVICE_SETTINGS = (
    ApplicationInsightsSettings,
    AzureMonitorSettings,
    CosmosDBSettings,
    EventGridSettings,
    EventHubsSettings,
    FoundrySettings,
    LogAnalyticsSettings,
    NetworkWatcherSettings,
    QueueStorageSettings,
    ResourceSettings,
    ServiceBusSettings,
)

ALIASED_FIELDS = [
    (settings_type, field_name)
    for settings_type in AZURE_SERVICE_SETTINGS
    for field_name, field in settings_type.model_fields.items()
    if isinstance(field.validation_alias, str)
]


def environment_variable_names(settings_type: type[BaseSettings]) -> set[str]:
    prefix = settings_type.model_config.get("env_prefix", "")
    names = set()
    for field_name, field in settings_type.model_fields.items():
        alias = field.validation_alias
        assert alias is None or isinstance(alias, str)
        names.add((alias or f"{prefix}{field_name}").lower())
    return names


def test_project_settings_from_template():
    settings = ProjectSettings(_env_file=Path(__file__).resolve().parents[1] / ".env.template")
    assert settings.project_name == "template-azure-python"
    assert settings.project_log_level == "INFO"
    assert settings.telemetry_enabled is False
    assert settings.telemetry_traces_per_second == 5
    assert settings.telemetry_live_metrics_enabled is False


def test_template_environment_variables_are_declared():
    template = Path(__file__).resolve().parents[1] / ".env.template"
    names = {
        line.split("=", 1)[0].strip().lower()
        for line in template.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    declared_names = ProjectSettings.model_fields.keys() | set().union(
        *(environment_variable_names(settings_type) for settings_type in (*AZURE_SERVICE_SETTINGS, EvaluationSettings))
    )
    assert names <= declared_names
    settings = AzureSettings(_env_file=template)
    assert settings.event_hubs.consumer_group == "$Default"
    assert settings.application_insights.connection_string is None


def test_settings_defaults_without_dotenv():
    assert get_project_settings().project_name == "default-project"
    assert get_project_settings().telemetry_enabled is False
    assert get_project_settings().telemetry_traces_per_second == 5
    assert get_project_settings().telemetry_live_metrics_enabled is False
    settings = get_azure_settings()
    assert settings.cosmos_db.endpoint is None
    assert settings.cosmos_db.database == "cosmicworks"
    assert settings.cosmos_db.container == "products"
    assert settings.event_hubs.consumer_group == "$Default"
    assert settings.resource.resource_group is None


def test_telemetry_project_settings_from_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TELEMETRY_ENABLED", "true")
    monkeypatch.setenv("TELEMETRY_TRACES_PER_SECOND", "2.5")
    monkeypatch.setenv("TELEMETRY_LIVE_METRICS_ENABLED", "true")

    settings = ProjectSettings(_env_file=None)

    assert settings.telemetry_enabled is True
    assert settings.telemetry_traces_per_second == 2.5
    assert settings.telemetry_live_metrics_enabled is True


@pytest.mark.parametrize("value", ["0", "-1"])
def test_telemetry_traces_per_second_must_be_positive(monkeypatch: pytest.MonkeyPatch, value: str):
    monkeypatch.setenv("TELEMETRY_TRACES_PER_SECOND", value)

    with pytest.raises(ValueError, match="greater than 0"):
        ProjectSettings(_env_file=None)


def test_dotenv_from_working_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    config = AzureSettings.model_config.copy()
    config["env_file"] = ".env"
    monkeypatch.setattr(AzureSettings, "model_config", config)
    (tmp_path / ".env").write_text(
        "AZURE_COSMOS_DB_ENDPOINT=https://dotenv.documents.azure.com/\nPROJECT_NAME=unrelated\n",
        encoding="utf-8",
    )
    assert get_azure_settings().cosmos_db.endpoint == "https://dotenv.documents.azure.com/"
    assert "AZURE_COSMOS_DB_ENDPOINT" not in os.environ
    child = tmp_path / "child"
    child.mkdir()
    monkeypatch.chdir(child)
    get_azure_settings.cache_clear()
    assert get_azure_settings().cosmos_db.endpoint is None


def test_settings_priority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    env_file = tmp_path / ".env"
    env_file.write_text("AZURE_COSMOS_DB_DATABASE=dotenv\n", encoding="utf-8")
    assert AzureSettings(_env_file=env_file).cosmos_db.database == "dotenv"
    monkeypatch.setenv("AZURE_COSMOS_DB_DATABASE", "environment")
    assert AzureSettings(_env_file=env_file).cosmos_db.database == "environment"
    settings = AzureSettings(cosmos_db={"database": "explicit"}, _env_file=env_file)
    assert settings.cosmos_db.database == "explicit"
    assert settings.cosmos_db.endpoint is None


@pytest.mark.parametrize("source", ["environment", "dotenv"])
def test_alias_settings_ignore_unrelated_names(source: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    values = {field_name.upper(): "unrelated-value" for _, field_name in ALIASED_FIELDS}
    env_file = None
    if source == "environment":
        for name, value in values.items():
            monkeypatch.setenv(name, value)
    else:
        env_file = tmp_path / ".env"
        env_file.write_text("\n".join(f"{name}={value}" for name, value in values.items()), encoding="utf-8")

    for settings_type, field_name in ALIASED_FIELDS:
        settings = settings_type(_env_file=env_file)
        assert getattr(settings, field_name) == settings_type.model_fields[field_name].default


@pytest.mark.parametrize(("settings_type", "field_name"), ALIASED_FIELDS)
def test_alias_settings_accept_explicit_field_names(
    settings_type: type[AzureServiceSettings], field_name: str, monkeypatch: pytest.MonkeyPatch
):
    alias = settings_type.model_fields[field_name].validation_alias
    assert isinstance(alias, str)
    monkeypatch.setenv(alias, "environment-value")

    settings = settings_type(_env_file=None, **{field_name: "explicit-value"})
    value = getattr(settings, field_name)
    if isinstance(value, SecretStr):
        value = value.get_secret_value()
    assert value == "explicit-value"


def test_empty_environment_values_use_defaults(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AZURE_RESOURCE_GROUP", "")
    monkeypatch.setenv("AZURE_COSMOS_DB_DATABASE", "")
    assert get_azure_settings().resource.resource_group is None
    assert get_azure_settings().cosmos_db.database == "cosmicworks"


def test_settings_are_cached_and_can_be_reset(monkeypatch: pytest.MonkeyPatch):
    first = get_azure_settings()
    monkeypatch.setenv("AZURE_COSMOS_DB_DATABASE", "changed")
    assert get_azure_settings() is first
    get_azure_settings.cache_clear()
    assert get_azure_settings().cosmos_db.database == "changed"


def test_secret_is_not_in_settings_output(monkeypatch: pytest.MonkeyPatch):
    secret = "InstrumentationKey=do-not-disclose"
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", secret)
    settings = get_azure_settings()
    assert settings.application_insights.connection_string is not None
    assert settings.application_insights.connection_string.get_secret_value() == secret
    assert secret not in repr(settings)
    assert "connection_string" not in settings.model_dump()["application_insights"]
    assert secret not in settings.model_dump_json()


def test_repository_setting_precedence_and_functions_environment(tmp_path, monkeypatch):
    from template_azure_python.settings import TaskRepositoryBackend, functions_environment

    env_file = tmp_path / ".env"
    env_file.write_text("TASK_REPOSITORY=cosmosdb\n", encoding="utf-8")
    assert ProjectSettings(_env_file=None).task_repository is TaskRepositoryBackend.IN_MEMORY
    assert ProjectSettings(_env_file=env_file).task_repository is TaskRepositoryBackend.COSMOSDB
    monkeypatch.setenv("TASK_REPOSITORY", "in-memory")
    assert ProjectSettings(_env_file=env_file).task_repository is TaskRepositoryBackend.IN_MEMORY
    assert (
        ProjectSettings(_env_file=env_file, task_repository=TaskRepositoryBackend.COSMOSDB).task_repository
        is TaskRepositoryBackend.COSMOSDB
    )
    child = functions_environment(TaskRepositoryBackend.COSMOSDB)
    assert child["TASK_REPOSITORY"] == "cosmosdb"
    assert os.environ["TASK_REPOSITORY"] == "in-memory"
    with pytest.raises(ValueError):
        ProjectSettings(_env_file=None, task_repository="invalid")


@pytest.mark.parametrize("fail", [False, True])
def test_telemetry_environment_restored(monkeypatch: pytest.MonkeyPatch, fail: bool):
    monkeypatch.setenv("OTEL_TRACES_SAMPLER", "always_off")
    monkeypatch.delenv("APPLICATIONINSIGHTS_STATSBEAT_DISABLED_ALL", raising=False)

    def emit():
        with telemetry_environment():
            assert os.environ["OTEL_TRACES_SAMPLER"] == "always_on"
            assert os.environ["APPLICATIONINSIGHTS_STATSBEAT_DISABLED_ALL"] == "true"
            if fail:
                raise RuntimeError("emission failed")

    if fail:
        with pytest.raises(RuntimeError, match="emission failed"):
            emit()
    else:
        emit()
    assert os.environ["OTEL_TRACES_SAMPLER"] == "always_off"
    assert "APPLICATIONINSIGHTS_STATSBEAT_DISABLED_ALL" not in os.environ
