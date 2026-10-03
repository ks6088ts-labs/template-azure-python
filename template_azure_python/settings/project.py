from functools import lru_cache

from template_azure_python.settings._base import EnvironmentSettings


class ProjectSettings(EnvironmentSettings):
    project_name: str = "default-project"
    project_log_level: str = "INFO"


@lru_cache
def get_project_settings() -> ProjectSettings:
    return ProjectSettings()
