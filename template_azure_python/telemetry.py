from threading import Lock

from template_azure_python.settings import (
    AzureSettings,
    ProjectSettings,
    get_azure_settings,
    get_project_settings,
)

LOGGER_NAME = "template_azure_python"


class TelemetryConfigurationError(RuntimeError):
    pass


_configure_lock = Lock()
_configured = False


def _configure_azure_monitor(project: ProjectSettings, azure: AzureSettings) -> None:
    connection_string = azure.application_insights.connection_string
    if connection_string is None or not connection_string.get_secret_value().strip():
        raise TelemetryConfigurationError(
            "API telemetry is enabled but APPLICATIONINSIGHTS_CONNECTION_STRING is not configured."
        )

    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource

        configure_azure_monitor(
            connection_string=connection_string.get_secret_value(),
            enable_live_metrics=project.telemetry_live_metrics_enabled,
            logger_name=LOGGER_NAME,
            resource=Resource.create({SERVICE_NAME: project.project_name}),
            traces_per_second=project.telemetry_traces_per_second,
        )
    except ModuleNotFoundError as error:
        if error.name is None or error.name.split(".")[0] not in {"azure", "opentelemetry"}:
            raise
        raise TelemetryConfigurationError("API telemetry requires the 'azure' extra: uv sync --extra azure") from None
    except Exception:
        raise TelemetryConfigurationError("Azure Monitor telemetry initialization failed.") from None


def configure_api_telemetry(
    project: ProjectSettings | None = None,
    azure: AzureSettings | None = None,
) -> bool:
    global _configured

    project = project or get_project_settings()
    if not project.telemetry_enabled:
        return False

    with _configure_lock:
        if _configured:
            return True
        _configure_azure_monitor(project, azure or get_azure_settings())
        _configured = True
    return True
