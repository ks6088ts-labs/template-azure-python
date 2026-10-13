from enum import StrEnum
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, model_validator

from template_azure_python.settings._base import EnvironmentSettings, FreshSettings


class TaskRepositoryBackend(StrEnum):
    IN_MEMORY = "in-memory"
    COSMOSDB = "cosmosdb"
    DUCKDB = "duckdb"


class ProjectSettings(EnvironmentSettings):
    project_name: str = "default-project"
    project_log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    app_environment: Literal["development", "test", "staging", "production"] = "development"
    app_version: str = "0.0.1"
    app_docs_enabled: bool | None = None
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    forwarded_allow_ips: str = "127.0.0.1"
    auth_mode: Literal["none", "easyauth"] = "none"
    auth_required_role: str | None = None
    cors_allowed_origins: tuple[str, ...] = ()
    telemetry_enabled: bool = False
    telemetry_traces_per_second: float = Field(default=5.0, gt=0)
    telemetry_live_metrics_enabled: bool = False
    telemetry_use_managed_identity: bool = False
    azure_client_id: str | None = None
    task_repository: TaskRepositoryBackend = TaskRepositoryBackend.IN_MEMORY
    duckdb_path: Path | None = None

    @model_validator(mode="after")
    def validate_security(self) -> "ProjectSettings":
        if self.auth_required_role is not None and (
            self.auth_mode != "easyauth" or not self.auth_required_role.strip()
        ):
            raise ValueError("AUTH_REQUIRED_ROLE requires AUTH_MODE=easyauth and a nonempty role")
        for origin in self.cors_allowed_origins:
            try:
                parsed = urlsplit(origin)
                valid_origin = (
                    parsed.scheme in {"http", "https"}
                    and parsed.hostname is not None
                    and parsed.username is None
                    and parsed.password is None
                    and parsed.path == ""
                    and not parsed.query
                    and not parsed.fragment
                    and "*" not in origin
                    and not any(character.isspace() or ord(character) < 32 for character in origin)
                    and (parsed.port is None or 1 <= parsed.port <= 65535)
                )
            except ValueError:
                valid_origin = False
            if not valid_origin:
                raise ValueError("CORS_ALLOWED_ORIGINS must contain explicit HTTP(S) origins, not wildcards or paths")
        return self

    @property
    def docs_enabled(self) -> bool:
        return (
            self.app_docs_enabled
            if self.app_docs_enabled is not None
            else self.app_environment in {"development", "test"}
        )


@FreshSettings
def get_project_settings() -> ProjectSettings:
    return ProjectSettings()
