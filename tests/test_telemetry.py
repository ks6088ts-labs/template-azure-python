import json
import os
import subprocess
import sys
import textwrap
from unittest.mock import patch

import pytest
from opentelemetry.sdk.resources import SERVICE_NAME

from template_azure_python.settings import AzureSettings, ProjectSettings
from template_azure_python.telemetry import (
    LOGGER_NAME,
    TelemetryConfigurationError,
    configure_api_telemetry,
)

CONNECTION_STRING = "InstrumentationKey=00000000-0000-0000-0000-000000000000"


@pytest.fixture(autouse=True)
def reset_telemetry_configuration(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("template_azure_python.telemetry._configured", False)


def project(
    *,
    project_name: str = "default-project",
    telemetry_enabled: bool = False,
    telemetry_traces_per_second: float = 5.0,
    telemetry_live_metrics_enabled: bool = False,
) -> ProjectSettings:
    return ProjectSettings(
        _env_file=None,
        project_name=project_name,
        telemetry_enabled=telemetry_enabled,
        telemetry_traces_per_second=telemetry_traces_per_second,
        telemetry_live_metrics_enabled=telemetry_live_metrics_enabled,
    )


def azure(connection_string: str | None = CONNECTION_STRING) -> AzureSettings:
    return AzureSettings(
        _env_file=None,
        application_insights={"connection_string": connection_string},
    )


def test_disabled_telemetry_does_not_configure_provider():
    with patch("template_azure_python.telemetry.configure_azure_monitor") as configure:
        assert configure_api_telemetry(project=project(), azure=azure()) is False

    configure.assert_not_called()


def test_enabled_telemetry_requires_connection_string():
    with pytest.raises(TelemetryConfigurationError, match="APPLICATIONINSIGHTS_CONNECTION_STRING"):
        configure_api_telemetry(project=project(telemetry_enabled=True), azure=azure(None))


def test_enabled_telemetry_configures_azure_monitor_once():
    settings = project(
        project_name="orders-api",
        telemetry_enabled=True,
        telemetry_traces_per_second=3.5,
        telemetry_live_metrics_enabled=True,
    )
    with patch("template_azure_python.telemetry.configure_azure_monitor") as configure:
        assert configure_api_telemetry(project=settings, azure=azure()) is True
        assert configure_api_telemetry(project=settings, azure=azure()) is True

    configure.assert_called_once()
    options = configure.call_args.kwargs
    assert options["connection_string"] == CONNECTION_STRING
    assert options["enable_live_metrics"] is True
    assert options["logger_name"] == LOGGER_NAME
    assert options["traces_per_second"] == 3.5
    assert options["resource"].attributes[SERVICE_NAME] == "orders-api"


def test_initialization_failure_is_sanitized():
    secret = "InstrumentationKey=do-not-disclose"
    with (
        patch(
            "template_azure_python.telemetry.configure_azure_monitor",
            side_effect=RuntimeError(f"failed for {secret}"),
        ),
        pytest.raises(TelemetryConfigurationError, match="initialization failed") as error,
    ):
        configure_api_telemetry(
            project=project(telemetry_enabled=True),
            azure=azure(secret),
        )

    assert secret not in str(error.value)
    assert error.value.__cause__ is None


def test_fastapi_request_is_instrumented_offline():
    script = textwrap.dedent(
        """
        import json
        from unittest.mock import patch

        from azure.monitor.opentelemetry.exporter import (
            AzureMonitorLogExporter, AzureMonitorMetricExporter, AzureMonitorTraceExporter,
        )
        from fastapi.testclient import TestClient
        from opentelemetry import metrics, trace
        from opentelemetry._logs import get_logger_provider
        from opentelemetry.sdk.trace.export import SpanExportResult
        from opentelemetry.sdk.metrics.export import MetricExportResult
        from opentelemetry.sdk._logs.export import LogRecordExportResult
        from opentelemetry.trace import SpanKind

        uploaded = []

        def export(self, spans, **kwargs):
            uploaded.extend(spans)
            return SpanExportResult.SUCCESS

        with (
            patch.object(AzureMonitorTraceExporter, "export", export),
            patch.object(AzureMonitorLogExporter, "export", return_value=LogRecordExportResult.SUCCESS),
            patch.object(AzureMonitorMetricExporter, "export", return_value=MetricExportResult.SUCCESS),
            patch("requests.sessions.Session.send", side_effect=AssertionError("Network forbidden")),
        ):
            from template_azure_python.api import create_app

            with TestClient(create_app()) as client:
                response = client.get("/tasks")
                assert client.get("/healthz").status_code == 200
                assert client.get("/readyz").status_code == 200
            assert response.status_code == 200
            for provider in (
                trace.get_tracer_provider(),
                get_logger_provider(),
                metrics.get_meter_provider(),
            ):
                provider.force_flush(timeout_millis=5000)

        requests = [span for span in uploaded if span.kind == SpanKind.SERVER]
        assert len(requests) == 1, [span.name for span in uploaded]
        request = requests[0]
        print(json.dumps({"name": request.name, "status": request.attributes["http.response.status_code"]}))
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        env={
            **os.environ,
            "APPLICATIONINSIGHTS_CONNECTION_STRING": CONNECTION_STRING,
            "APPLICATIONINSIGHTS_STATSBEAT_DISABLED_ALL": "true",
            "APPLICATIONINSIGHTS_SDKSTATS_DISABLED": "true",
            "APPLICATIONINSIGHTS_CONTROLPLANE_DISABLED": "true",
            "OTEL_EXPERIMENTAL_RESOURCE_DETECTORS": "",
            "PROJECT_NAME": "offline-api",
            "TELEMETRY_ENABLED": "true",
            "TELEMETRY_TRACES_PER_SECOND": "100",
            "TELEMETRY_LIVE_METRICS_ENABLED": "false",
        },
    )

    assert result.returncode == 0, result.stdout + result.stderr
    summary = json.loads(result.stdout)
    assert summary["status"] == 200
    assert summary["name"]


def test_managed_identity_and_resource_attributes():
    settings = ProjectSettings(
        _env_file=None,
        telemetry_enabled=True,
        telemetry_use_managed_identity=True,
        azure_client_id="runtime-identity",
        app_environment="production",
        app_version="1.2.3",
    )
    with (
        patch("azure.identity.ManagedIdentityCredential") as credential,
        patch("template_azure_python.telemetry.configure_azure_monitor") as configure,
    ):
        assert configure_api_telemetry(project=settings, azure=azure())
    credential.assert_called_once_with(client_id="runtime-identity")
    options = configure.call_args.kwargs
    assert options["credential"] is credential.return_value
    assert options["instrumentation_options"]["fastapi"]["enabled"] is False
    assert options["resource"].attributes["service.version"] == "1.2.3"
    assert options["resource"].attributes["deployment.environment.name"] == "production"


def test_parallel_startups_only_initialize_one_provider():
    from concurrent.futures import ThreadPoolExecutor

    settings = project(telemetry_enabled=True)
    azure_settings = azure()
    with patch("template_azure_python.telemetry.configure_azure_monitor") as configure, ThreadPoolExecutor(4) as pool:
        results = list(pool.map(lambda _: configure_api_telemetry(settings, azure_settings), range(16)))
    assert all(results)
    configure.assert_called_once()


def test_api_import_has_no_telemetry_or_logging_side_effects():
    script = """
import logging
root = logging.getLogger()
before = (root.level, tuple(root.handlers))
import template_azure_python.api
assert before == (root.level, tuple(root.handlers))
assert not hasattr(template_azure_python.api, "app")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "TELEMETRY_ENABLED": "true", "APPLICATIONINSIGHTS_CONNECTION_STRING": ""},
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_core_api_does_not_import_optional_storage_or_sample_sdks():
    script = """
import importlib.abc
import sys
from fastapi.testclient import TestClient

class BlockOptional(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == name or fullname.startswith(name + ".") for name in (
            "azure.cosmos", "duckdb", "azure.monitor.query", "azure.functions", "typer",
        )):
            raise ModuleNotFoundError("Optional SDK forbidden: " + fullname)

sys.meta_path.insert(0, BlockOptional())
from template_azure_python.api import create_app
from template_azure_python.settings import ProjectSettings
with TestClient(create_app(settings=ProjectSettings(_env_file=None))) as client:
    assert client.get("/tasks").json() == []
    assert client.get("/readyz").status_code == 200
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "TELEMETRY_ENABLED": "false"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
