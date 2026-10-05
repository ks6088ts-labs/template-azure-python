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

        from azure.monitor.opentelemetry.exporter._generated import AzureMonitorClient
        from azure.monitor.opentelemetry.exporter._generated.exporter.models import TrackResponse
        from fastapi.testclient import TestClient
        from opentelemetry import metrics, trace
        from opentelemetry._logs import get_logger_provider

        uploaded = []

        def track(self, body, **kwargs):
            uploaded.extend(body)
            return TrackResponse(items_received=len(body), items_accepted=len(body), errors=[])

        with (
            patch.object(AzureMonitorClient, "track", track),
            patch("requests.sessions.Session.send", side_effect=AssertionError("Network forbidden")),
        ):
            from template_azure_python.api import app

            with TestClient(app) as client:
                response = client.get("/tasks")
            assert response.status_code == 200
            for provider in (
                trace.get_tracer_provider(),
                get_logger_provider(),
                metrics.get_meter_provider(),
            ):
                provider.force_flush(timeout_millis=5000)

        requests = [item for item in uploaded if item.data.base_type == "RequestData"]
        assert requests
        request = requests[0].data.base_data
        print(json.dumps({"name": request.name, "response_code": request.response_code}))
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
    assert summary["response_code"] == "200"
    assert summary["name"]
