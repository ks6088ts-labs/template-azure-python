from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any, TypeAlias

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

from template_azure_python.settings.azure.cosmos_db import CosmosDBSettings
from template_azure_python.settings.azure.foundry import FoundrySettings
from template_azure_python.settings.azure.messaging import (
    EventGridSettings,
    EventHubsSettings,
    QueueStorageSettings,
    ServiceBusSettings,
)
from template_azure_python.settings.azure.observability import (
    ApplicationInsightsSettings,
    AzureMonitorSettings,
    LogAnalyticsSettings,
    NetworkWatcherSettings,
)
from template_azure_python.settings.azure.resource import ResourceSettings

EnvFile: TypeAlias = str | Path | Sequence[str | Path] | None


class _EnvFileSentinel:
    pass


_ENV_FILE_SENTINEL = _EnvFileSentinel()


def _load_service_settings(
    settings_type: type[BaseSettings],
    value: object,
    env_file: EnvFile,
) -> object:
    if isinstance(value, settings_type):
        return value
    if value is None:
        values: Mapping[str, Any] = {}
    elif isinstance(value, Mapping):
        values = value
    else:
        return value
    return settings_type(_env_file=env_file, **values)


class AzureSettings(BaseSettings):
    foundry: FoundrySettings
    cosmos_db: CosmosDBSettings
    event_grid: EventGridSettings
    event_hubs: EventHubsSettings
    service_bus: ServiceBusSettings
    queue_storage: QueueStorageSettings
    azure_monitor: AzureMonitorSettings
    log_analytics: LogAnalyticsSettings
    application_insights: ApplicationInsightsSettings
    network_watcher: NetworkWatcherSettings
    resource: ResourceSettings

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    def __init__(
        self,
        *,
        _env_file: EnvFile | _EnvFileSentinel = _ENV_FILE_SENTINEL,
        **data: Any,
    ) -> None:
        env_file = self.model_config.get("env_file") if isinstance(_env_file, _EnvFileSentinel) else _env_file
        settings_types = {
            "foundry": FoundrySettings,
            "cosmos_db": CosmosDBSettings,
            "event_grid": EventGridSettings,
            "event_hubs": EventHubsSettings,
            "service_bus": ServiceBusSettings,
            "queue_storage": QueueStorageSettings,
            "azure_monitor": AzureMonitorSettings,
            "log_analytics": LogAnalyticsSettings,
            "application_insights": ApplicationInsightsSettings,
            "network_watcher": NetworkWatcherSettings,
            "resource": ResourceSettings,
        }
        values = {
            name: _load_service_settings(settings_type, data.pop(name, None), env_file)
            for name, settings_type in settings_types.items()
        }
        BaseModel.__init__(self, **values, **data)


@lru_cache
def get_azure_settings() -> AzureSettings:
    return AzureSettings()
