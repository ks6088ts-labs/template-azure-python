from pydantic_settings import SettingsConfigDict

from template_azure_python.settings.azure._base import AzureServiceSettings


class CosmosDBSettings(AzureServiceSettings):
    endpoint: str | None = None
    database: str = "cosmicworks"
    container: str = "products"
    task_container: str = "tasks"
    account_name: str | None = None

    model_config = SettingsConfigDict(env_prefix="AZURE_COSMOS_DB_")
