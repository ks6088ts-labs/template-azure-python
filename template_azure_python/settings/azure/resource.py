from pydantic_settings import SettingsConfigDict

from template_azure_python.settings.azure._base import AzureServiceSettings


class ResourceSettings(AzureServiceSettings):
    subscription_id: str | None = None
    resource_group: str | None = None

    model_config = SettingsConfigDict(env_prefix="AZURE_")
