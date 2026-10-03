from collections.abc import Generator
from pathlib import Path

import pytest

from template_azure_python.settings import AzureSettings, ProjectSettings, get_azure_settings, get_project_settings


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    for settings_type in (ProjectSettings, AzureSettings):
        config = settings_type.model_config.copy()
        config["env_file"] = None
        monkeypatch.setattr(settings_type, "model_config", config)
    template = Path(__file__).resolve().parents[1] / ".env.template"
    for line in template.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            monkeypatch.delenv(line.split("=", 1)[0].strip(), raising=False)
    get_project_settings.cache_clear()
    get_azure_settings.cache_clear()
    try:
        yield
    finally:
        get_project_settings.cache_clear()
        get_azure_settings.cache_clear()
