import os
from pathlib import Path

import pytest

from template_azure_python.settings import (
    AzureSettings,
    ProjectSettings,
    get_azure_settings,
    get_project_settings,
    telemetry_environment,
)


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
    assert names <= ProjectSettings.model_fields.keys() | AzureSettings.model_fields.keys()
    settings = AzureSettings(_env_file=template)
    assert settings.azure_event_hub_consumer_group == "$Default"
    assert settings.applicationinsights_connection_string is None


def test_settings_defaults_without_dotenv():
    assert get_project_settings().project_name == "default-project"
    settings = get_azure_settings()
    assert settings.azure_cosmos_db_endpoint is None
    assert settings.azure_cosmos_db_database == "cosmicworks"
    assert settings.azure_cosmos_db_container == "products"
    assert settings.azure_event_hub_consumer_group == "$Default"
    assert settings.azure_resource_group is None


def test_dotenv_from_working_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    config = AzureSettings.model_config.copy()
    config["env_file"] = ".env"
    monkeypatch.setattr(AzureSettings, "model_config", config)
    (tmp_path / ".env").write_text(
        "AZURE_COSMOS_DB_ENDPOINT=https://dotenv.documents.azure.com/\nPROJECT_NAME=unrelated\n",
        encoding="utf-8",
    )
    assert get_azure_settings().azure_cosmos_db_endpoint == "https://dotenv.documents.azure.com/"
    assert "AZURE_COSMOS_DB_ENDPOINT" not in os.environ
    child = tmp_path / "child"
    child.mkdir()
    monkeypatch.chdir(child)
    get_azure_settings.cache_clear()
    assert get_azure_settings().azure_cosmos_db_endpoint is None


def test_settings_priority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    env_file = tmp_path / ".env"
    env_file.write_text("AZURE_COSMOS_DB_DATABASE=dotenv\n", encoding="utf-8")
    assert AzureSettings(_env_file=env_file).azure_cosmos_db_database == "dotenv"
    monkeypatch.setenv("AZURE_COSMOS_DB_DATABASE", "environment")
    assert AzureSettings(_env_file=env_file).azure_cosmos_db_database == "environment"
    assert AzureSettings(azure_cosmos_db_database="explicit", _env_file=env_file).azure_cosmos_db_database == "explicit"


def test_empty_environment_values_use_defaults(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AZURE_RESOURCE_GROUP", "")
    monkeypatch.setenv("AZURE_COSMOS_DB_DATABASE", "")
    assert get_azure_settings().azure_resource_group is None
    assert get_azure_settings().azure_cosmos_db_database == "cosmicworks"


def test_settings_are_cached_and_can_be_reset(monkeypatch: pytest.MonkeyPatch):
    first = get_azure_settings()
    monkeypatch.setenv("AZURE_COSMOS_DB_DATABASE", "changed")
    assert get_azure_settings() is first
    get_azure_settings.cache_clear()
    assert get_azure_settings().azure_cosmos_db_database == "changed"


def test_secret_is_not_in_settings_output(monkeypatch: pytest.MonkeyPatch):
    secret = "InstrumentationKey=do-not-disclose"
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", secret)
    settings = get_azure_settings()
    assert settings.applicationinsights_connection_string is not None
    assert settings.applicationinsights_connection_string.get_secret_value() == secret
    assert secret not in repr(settings)
    assert "applicationinsights_connection_string" not in settings.model_dump()
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
