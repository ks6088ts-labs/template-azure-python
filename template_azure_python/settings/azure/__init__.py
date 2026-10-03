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
from template_azure_python.settings.azure.settings import AzureSettings, get_azure_settings

__all__ = [
    "ApplicationInsightsSettings",
    "AzureMonitorSettings",
    "AzureSettings",
    "CosmosDBSettings",
    "EventGridSettings",
    "EventHubsSettings",
    "FoundrySettings",
    "LogAnalyticsSettings",
    "NetworkWatcherSettings",
    "QueueStorageSettings",
    "ResourceSettings",
    "ServiceBusSettings",
    "get_azure_settings",
]
