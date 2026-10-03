from pydantic import Field
from pydantic_settings import SettingsConfigDict

from template_azure_python.settings.azure._base import AzureServiceSettings


class EventGridSettings(AzureServiceSettings):
    endpoint: str | None = None

    model_config = SettingsConfigDict(env_prefix="AZURE_EVENT_GRID_TOPIC_")


class EventHubsSettings(AzureServiceSettings):
    fully_qualified_namespace: str | None = Field(
        default=None, validation_alias="AZURE_EVENT_HUBS_FULLY_QUALIFIED_NAMESPACE"
    )
    name: str | None = Field(default=None, validation_alias="AZURE_EVENT_HUB_NAME")
    consumer_group: str = Field(default="$Default", validation_alias="AZURE_EVENT_HUB_CONSUMER_GROUP")


class ServiceBusSettings(AzureServiceSettings):
    fully_qualified_namespace: str | None = None
    queue_name: str | None = None

    model_config = SettingsConfigDict(env_prefix="AZURE_SERVICE_BUS_")


class QueueStorageSettings(AzureServiceSettings):
    endpoint: str | None = None
    queue_name: str | None = None

    model_config = SettingsConfigDict(env_prefix="AZURE_QUEUE_STORAGE_")
