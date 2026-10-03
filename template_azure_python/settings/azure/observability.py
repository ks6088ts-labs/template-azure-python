from pydantic import Field, SecretStr

from template_azure_python.settings.azure._base import AzureServiceSettings


class AzureMonitorSettings(AzureServiceSettings):
    resource_id: str | None = Field(default=None, validation_alias="AZURE_MONITOR_ID")


class LogAnalyticsSettings(AzureServiceSettings):
    workspace_id: str | None = Field(default=None, validation_alias="AZURE_LOG_ANALYTICS_WORKSPACE_ID")


class ApplicationInsightsSettings(AzureServiceSettings):
    resource_id: str | None = Field(default=None, validation_alias="AZURE_APPLICATION_INSIGHTS_ID")
    connection_string: SecretStr | None = Field(
        default=None,
        validation_alias="APPLICATIONINSIGHTS_CONNECTION_STRING",
        exclude=True,
    )


class NetworkWatcherSettings(AzureServiceSettings):
    resource_id: str | None = Field(default=None, validation_alias="AZURE_NETWORK_WATCHER_ID")
