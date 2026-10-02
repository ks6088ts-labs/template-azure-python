"""Emit one bounded telemetry run or query an Application Insights resource."""

import logging
import os
from collections.abc import Generator
from contextlib import closing, contextmanager
from datetime import timedelta
from enum import Enum
from typing import Annotated, cast
from uuid import uuid4

import typer
from azure.core.exceptions import AzureError
from azure.identity import DefaultAzureCredential
from azure.monitor.opentelemetry import configure_azure_monitor
from azure.monitor.query import LogsQueryClient
from dotenv import load_dotenv
from opentelemetry import metrics, trace
from opentelemetry._logs import get_logger_provider
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.trace import TracerProvider

from scripts._azure_messaging import print_json
from scripts._azure_observability import format_logs_result, validate_arm_id, validate_guid

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


app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=(
        "Query with AZURE_APPLICATION_INSIGHTS_ID and `az login`. "
        "Emit with APPLICATIONINSIGHTS_CONNECTION_STRING from the environment only."
    ),
)
ResourceOption = Annotated[
    str, typer.Option("--resource-id", envvar="AZURE_APPLICATION_INSIGHTS_ID", help="Application Insights ARM ID.")
]
HoursOption = Annotated[int, typer.Option("--hours", min=1, max=168)]
LimitOption = Annotated[int, typer.Option("--limit", min=1, max=1000)]
TableOption = Annotated[TelemetryTable, typer.Option("--table", help="Workspace telemetry table.")]
RunOption = Annotated[str | None, typer.Option("--run-id", help="Filter the generated run UUID.")]
CountOption = Annotated[int, typer.Option("--count", min=1, max=100)]


@app.command()
def query_telemetry(
    resource_id: ResourceOption,
    table: TableOption = TelemetryTable.REQUESTS,
    hours: HoursOption = 24,
    limit: LimitOption = 100,
    run_id: RunOption = None,
) -> None:
    """Run a bounded resource-centric query, optionally filtered to an emitted run."""
    validate_arm_id(resource_id, "Microsoft.Insights", "components")
    if run_id is not None:
        run_id = validate_guid(run_id)
    query = f"{table.value} | where TimeGenerated >= ago({hours}h)"
    if run_id is not None:
        query += f' | where tostring(Properties["run_id"]) == "{run_id}"'
    query += f" | order by TimeGenerated desc | take {limit}"
    try:
        with closing(DefaultAzureCredential()) as credential, closing(LogsQueryClient(credential)) as client:
            result = client.query_resource(resource_id, query, timespan=timedelta(hours=hours), server_timeout=30)
            output = format_logs_result(result)
    except AzureError:
        print_json({"error": "Azure Application Insights query failed."})
        raise typer.Exit(1) from None
    print_json(output)
    if "error" in output:
        raise typer.Exit(1)


class _Diagnostics(logging.Handler):
    """Count SDK warnings without retaining or printing potentially secret records."""

    failed = False

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno >= logging.WARNING:
            self.failed = True


@contextmanager
def _isolated_logging(logger: logging.Logger) -> Generator[_Diagnostics, None, None]:
    # Exporter workers also log exceptions. Isolate all existing handlers for this
    # single CLI run, rather than merely catching exceptions in the calling thread.
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


@contextmanager
def _telemetry_environment() -> Generator[None, None, None]:
    settings = {
        "APPLICATIONINSIGHTS_STATSBEAT_DISABLED_ALL": "true",
        "APPLICATIONINSIGHTS_SDKSTATS_DISABLED": "true",
        "APPLICATIONINSIGHTS_CONTROLPLANE_DISABLED": "true",
        "OTEL_TRACES_SAMPLER": "always_on",
    }
    previous = {name: os.environ.get(name) for name in settings}
    try:
        os.environ.update(settings)
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


@app.command()
def emit_telemetry(count: CountOption = 10) -> None:
    """Emit once. Provider flushing does not guarantee acceptance, persistence or ingestion."""
    connection_string = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if not connection_string or not connection_string.strip():
        raise typer.BadParameter("set APPLICATIONINSIGHTS_CONNECTION_STRING in the environment")
    run_id = str(uuid4())
    logger_name = f"quickstart.application_insights.{run_id}"
    logger = logging.getLogger(logger_name)
    failures: list[str] = []
    providers: list[tuple[str, TracerProvider | LoggerProvider | MeterProvider]] = []
    with _isolated_logging(logger) as diagnostics, _telemetry_environment():
        try:
            configure_azure_monitor(
                connection_string=connection_string,
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
    output: dict = {
        "run_id": run_id,
        "count": count,
        "flushed": not failures,
        "ingestion_guaranteed": False,
    }
    if failures:
        output["failures"] = failures
    print_json(output)
    if failures:
        raise typer.Exit(1)


if __name__ == "__main__":
    load_dotenv(override=False)
    app()
