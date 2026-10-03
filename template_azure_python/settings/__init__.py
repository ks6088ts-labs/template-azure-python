from template_azure_python.settings._telemetry import telemetry_environment
from template_azure_python.settings.azure import AzureSettings, get_azure_settings
from template_azure_python.settings.project import ProjectSettings, get_project_settings

__all__ = ["AzureSettings", "ProjectSettings", "get_azure_settings", "get_project_settings", "telemetry_environment"]
