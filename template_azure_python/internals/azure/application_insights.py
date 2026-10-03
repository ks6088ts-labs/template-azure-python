import logging
from collections.abc import Generator
from contextlib import closing, contextmanager
from datetime import timedelta
from enum import Enum
from typing import cast
from uuid import uuid4

from azure.identity import DefaultAzureCredential
from azure.monitor.opentelemetry import configure_azure_monitor
from azure.monitor.query import LogsQueryClient
from opentelemetry import metrics, trace
from opentelemetry._logs import get_logger_provider
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.trace import TracerProvider

from template_azure_python.internals.azure._common import (
    InputError,
    azure_errors,
    format_logs_result,
    required_value,
    validate_arm_id,
    validate_guid,
)
from template_azure_python.settings import get_azure_settings, telemetry_environment

FLUSH_TIMEOUT_MILLIS = 5000
INSTRUMENTATIONS = (
    "azure_sdk",
    "django",
    "fastapi",
    "flask",
    "httpx",
    "httpx2",
    "psycopg2",
    "requests",
    "urllib",
    "urllib3",
)


class TelemetryTable(str, Enum):
    REQUESTS = "AppRequests"
    DEPENDENCIES = "AppDependencies"
    TRACES = "AppTraces"
    METRICS = "AppMetrics"

    @property
    def resource_table(self) -> str:
        return {
            TelemetryTable.REQUESTS: "requests",
            TelemetryTable.DEPENDENCIES: "dependencies",
            TelemetryTable.TRACES: "traces",
            TelemetryTable.METRICS: "customMetrics",
        }[self]


def query_telemetry(
    resource_id: str | None, table: TelemetryTable, hours: int, limit: int, run_id: str | None
) -> dict[str, object]:
    resource_id = required_value(resource_id, get_azure_settings().azure_application_insights_id, "--resource-id")
    validate_arm_id(resource_id, "Microsoft.Insights", "components")
    if run_id is not None:
        run_id = validate_guid(run_id)
    query = f"{table.resource_table} | where timestamp >= ago({hours}h)"
    if run_id is not None:
        query += f' | where tostring(customDimensions["run_id"]) == "{run_id}"'
    query += f" | order by timestamp desc | take {limit}"
    with azure_errors("Azure Application Insights query failed."):
        with closing(DefaultAzureCredential()) as credential, closing(LogsQueryClient(credential)) as client:
            result = client.query_resource(resource_id, query, timespan=timedelta(hours=hours), server_timeout=30)
            return format_logs_result(result)


class _Diagnostics(logging.Handler):
    """Count SDK warnings without retaining potentially secret records."""

    failed = False

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno >= logging.WARNING:
            self.failed = True


@contextmanager
def _isolated_logging(logger: logging.Logger) -> Generator[_Diagnostics, None, None]:
    # Exporter workers also log failures; isolate their handlers for this CLI run.
    root = logging.getLogger()
    loggers = [root, *(item for item in root.manager.loggerDict.values() if isinstance(item, logging.Logger))]
    previous = [(item, item.handlers[:], item.propagate, item.level, item.disabled) for item in loggers]
    diagnostics = _Diagnostics()
    try:
        for item in loggers:
            item.handlers = []
            item.propagate = True
            item.disabled = False
        root.handlers = [diagnostics]
        root.setLevel(logging.WARNING)
        logger.propagate = False
        logger.setLevel(logging.INFO)
        yield diagnostics
    finally:
        for item, handlers, propagate, level, disabled in previous:
            item.handlers = handlers
            item.propagate = propagate
            item.setLevel(level)
            item.disabled = disabled
        diagnostics.close()


def emit_telemetry(count: int) -> dict[str, object]:
    secret = get_azure_settings().applicationinsights_connection_string
    if secret is None or not secret.get_secret_value().strip():
        raise InputError("set APPLICATIONINSIGHTS_CONNECTION_STRING in the environment")
    run_id = str(uuid4())
    logger_name = f"quickstart.application_insights.{run_id}"
    logger = logging.getLogger(logger_name)
    failures: list[str] = []
    providers: list[tuple[str, TracerProvider | LoggerProvider | MeterProvider]] = []
    with _isolated_logging(logger) as diagnostics, telemetry_environment():
        try:
            configure_azure_monitor(
                connection_string=secret.get_secret_value(),
                logger_name=logger_name,
                disable_offline_storage=True,
                enable_live_metrics=False,
                enable_performance_counters=False,
                sampling_ratio=1.0,
                instrumentation_options={name: {"enabled": False} for name in INSTRUMENTATIONS},
                timeout=5,
                read_timeout=5,
            )
            providers = [
                ("traces", cast(TracerProvider, trace.get_tracer_provider())),
                ("logs", cast(LoggerProvider, get_logger_provider())),
                ("metrics", cast(MeterProvider, metrics.get_meter_provider())),
            ]
            tracer = trace.get_tracer(logger_name)
            counter = metrics.get_meter(logger_name).create_counter("quickstart.events")
            for sequence in range(1, count + 1):
                attributes = {"run_id": run_id, "sequence": sequence}
                with tracer.start_as_current_span(
                    "quickstart.request", kind=trace.SpanKind.SERVER, attributes=attributes
                ):
                    logger.info("Quickstart telemetry", extra=attributes)
                    counter.add(1, attributes=attributes)
        except Exception:
            failures.append("Telemetry configuration or emission failed.")
        finally:
            # Configuration can fail after installing only some providers.
            if not providers:
                for name, getter in (
                    ("traces", trace.get_tracer_provider),
                    ("logs", get_logger_provider),
                    ("metrics", metrics.get_meter_provider),
                ):
                    try:
                        provider = getter()
                        if hasattr(provider, "force_flush"):
                            providers.append((name, cast(TracerProvider | LoggerProvider | MeterProvider, provider)))
                    except Exception:
                        failures.append(f"{name} provider unavailable.")
            for name, provider in providers:
                try:
                    if not provider.force_flush(timeout_millis=FLUSH_TIMEOUT_MILLIS):
                        failures.append(f"{name} flush failed.")
                except Exception:
                    failures.append(f"{name} flush failed.")
            for name, provider in providers:
                try:
                    if isinstance(provider, MeterProvider):
                        provider.shutdown(timeout_millis=FLUSH_TIMEOUT_MILLIS)
                    else:
                        provider.shutdown()
                except Exception:
                    failures.append(f"{name} shutdown failed.")
        if diagnostics.failed:
            failures.append("Telemetry SDK reported a warning or export failure.")
    output: dict[str, object] = {
        "run_id": run_id,
        "count": count,
        "flushed": not failures,
        "ingestion_guaranteed": False,
    }
    if failures:
        output["failures"] = failures
    return output
