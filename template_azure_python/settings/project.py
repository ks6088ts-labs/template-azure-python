from functools import lru_cache

from pydantic import Field

from template_azure_python.settings._base import EnvironmentSettings


class ProjectSettings(EnvironmentSettings):
    project_name: str = "default-project"
    project_log_level: str = "INFO"
    telemetry_enabled: bool = False
    telemetry_traces_per_second: float = Field(default=5.0, gt=0)
    telemetry_live_metrics_enabled: bool = False


@lru_cache
def get_project_settings() -> ProjectSettings:
    return ProjectSettings()
