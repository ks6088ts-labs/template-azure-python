import os
from pathlib import Path

import pytest
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


def test_template_environment_variables_are_declared():
    template = Path(__file__).resolve().parents[1] / ".env.template"
    names = {
        line.split("=", 1)[0].strip().lower()
        for line in template.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    declared_names = ProjectSettings.model_fields.keys() | set().union(
        *(environment_variable_names(settings_type) for settings_type in AZURE_SERVICE_SETTINGS)
    )
    assert names <= declared_names
    settings = AzureSettings(_env_file=template)
    assert settings.event_hubs.consumer_group == "$Default"
    assert settings.application_insights.connection_string is None


def test_settings_defaults_without_dotenv():
    assert get_project_settings().project_name == "default-project"
    settings = get_azure_settings()
    assert settings.cosmos_db.endpoint is None
    assert settings.cosmos_db.database == "cosmicworks"
    assert settings.cosmos_db.container == "products"
    assert settings.event_hubs.consumer_group == "$Default"
    assert settings.resource.resource_group is None


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
