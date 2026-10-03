from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import SettingsConfigDict

from template_azure_python.settings._base import EnvironmentSettings


class AzureSettings(EnvironmentSettings):
    foundry_project_endpoint: str | None = None
    azure_cosmos_db_endpoint: str | None = None
    azure_cosmos_db_database: str = "cosmicworks"
    azure_cosmos_db_container: str = "products"
    azure_event_grid_topic_endpoint: str | None = None
    azure_event_hubs_fully_qualified_namespace: str | None = None
    azure_event_hub_name: str | None = None
    azure_event_hub_consumer_group: str = "$Default"
    azure_service_bus_fully_qualified_namespace: str | None = None
    azure_service_bus_queue_name: str | None = None
    azure_queue_storage_endpoint: str | None = None
    azure_queue_storage_queue_name: str | None = None
    azure_monitor_id: str | None = None
    azure_log_analytics_workspace_id: str | None = None
    azure_application_insights_id: str | None = None
    azure_network_watcher_id: str | None = None
    azure_subscription_id: str | None = None
    azure_resource_group: str | None = None
    applicationinsights_connection_string: SecretStr | None = Field(default=None, exclude=True)

    model_config = SettingsConfigDict(env_ignore_empty=True)


@lru_cache
def get_azure_settings() -> AzureSettings:
    return AzureSettings()
