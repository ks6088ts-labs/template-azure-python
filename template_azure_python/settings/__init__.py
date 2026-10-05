from template_azure_python.settings._server import functions_environment
from template_azure_python.settings._telemetry import telemetry_environment
from template_azure_python.settings.azure import AzureSettings, get_azure_settings
from template_azure_python.settings.project import ProjectSettings, TaskRepositoryBackend, get_project_settings

__all__ = [
    "AzureSettings",
    "ProjectSettings",
    "TaskRepositoryBackend",
    "functions_environment",
    "get_azure_settings",
    "get_project_settings",
    "telemetry_environment",
]
