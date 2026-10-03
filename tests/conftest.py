from collections.abc import Generator

import pytest

from template_azure_python.settings import AzureSettings, ProjectSettings, get_azure_settings, get_project_settings


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    for settings_type in (ProjectSettings, AzureSettings):
        config = settings_type.model_config.copy()
        config["env_file"] = None
        monkeypatch.setattr(settings_type, "model_config", config)
        for name in settings_type.model_fields:
            monkeypatch.delenv(name.upper(), raising=False)
    get_project_settings.cache_clear()
    get_azure_settings.cache_clear()
    try:
        yield
    finally:
        get_project_settings.cache_clear()
        get_azure_settings.cache_clear()
