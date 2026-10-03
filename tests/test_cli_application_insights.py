import json
import logging
import os
import runpy
import subprocess
import sys
import textwrap
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from azure.core.exceptions import AzureError
from azure.monitor.query import LogsQueryPartialResult, LogsQueryResult, LogsTable
from opentelemetry.trace import SpanKind
from typer.testing import CliRunner

from scripts.cli_application_insights import app
from template_azure_python.internals.azure.application_insights import FLUSH_TIMEOUT_MILLIS, INSTRUMENTATIONS

GUID = "01234567-89ab-cdef-0123-456789abcdef"
RESOURCE_ID = f"/subscriptions/{GUID}/resourceGroups/rg/providers/Microsoft.Insights/components/app"
CONNECTION = "InstrumentationKey=secret-do-not-print"


@pytest.fixture
def clients():
    credential, client = MagicMock(), MagicMock()
    client.query_resource.return_value = LogsQueryResult()
    with (
        patch(
            "template_azure_python.internals.azure.application_insights.DefaultAzureCredential", return_value=credential
        ) as auth,
        patch(
            "template_azure_python.internals.azure.application_insights.LogsQueryClient", return_value=client
        ) as factory,
    ):
        yield SimpleNamespace(credential=credential, client=client, auth=auth, factory=factory)


@pytest.mark.parametrize(
    ("table", "resource_table"),
    [
        ("AppRequests", "requests"),
        ("AppDependencies", "dependencies"),
        ("AppTraces", "traces"),
        ("AppMetrics", "customMetrics"),
    ],
)
@pytest.mark.parametrize("filtered", [False, True])
def test_query(table: str, resource_table: str, filtered: bool, clients: SimpleNamespace):
    args = ["query-telemetry", "--resource-id", RESOURCE_ID, "--table", table, "--hours", "168", "--limit", "1000"]
    if filtered:
        args += ["--run-id", GUID]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"tables": []}
    args, kwargs = clients.client.query_resource.call_args
    assert args[0] == RESOURCE_ID
    expected_query = f"{resource_table} | where timestamp >= ago(168h)"
    if filtered:
        expected_query += f' | where tostring(customDimensions["run_id"]) == "{GUID}"'
    expected_query += " | order by timestamp desc | take 1000"
    assert args[1] == expected_query
    assert kwargs == {"timespan": timedelta(hours=168), "server_timeout": 30}
    clients.factory.assert_called_once_with(clients.credential)
    clients.client.close.assert_called_once()
    clients.credential.close.assert_called_once()


@pytest.mark.parametrize("explicit", [False, True])
def test_query_defaults_environment_and_override(explicit: bool, clients: SimpleNamespace):
    other = RESOURCE_ID.replace("/app", "/other")
    args = ["query-telemetry", "--resource-id", RESOURCE_ID] if explicit else ["query-telemetry"]
    result = CliRunner().invoke(app, args, env={"AZURE_APPLICATION_INSIGHTS_ID": other})
    assert result.exit_code == 0
    args, kwargs = clients.client.query_resource.call_args
    assert args[0] == (RESOURCE_ID if explicit else other)
    assert args[1] == "requests | where timestamp >= ago(24h) | order by timestamp desc | take 100"
    assert kwargs["timespan"] == timedelta(hours=24)


@pytest.mark.parametrize(
    "options",
    [
        ["--hours", "0"],
        ["--hours", "169"],
        ["--limit", "0"],
        ["--limit", "1001"],
        ["--table", "AzureActivity"],
        ["--run-id", 'secret" | take 99'],
        ["--resource-id", "secret"],
        ["--resource-id", RESOURCE_ID.replace("components", "workspaces")],
        ["--query", "arbitrary"],
    ],
)
def test_query_validation(options: list[str], clients: SimpleNamespace):
    result = CliRunner().invoke(app, ["query-telemetry", "--resource-id", RESOURCE_ID, *options])
    assert result.exit_code == 2
    assert "secret" not in result.output
    clients.auth.assert_not_called()


def test_missing_resource(clients: SimpleNamespace):
    result = CliRunner().invoke(app, ["query-telemetry"], env={"AZURE_APPLICATION_INSIGHTS_ID": ""})
    assert result.exit_code == 2
    clients.auth.assert_not_called()


def test_partial_query(clients: SimpleNamespace):
    clients.client.query_resource.return_value = LogsQueryPartialResult(
        partial_data=[LogsTable(name="result", columns=["Count"], columns_types=["long"], rows=[[3]])],
        partial_error={"message": CONNECTION},
    )
    result = CliRunner().invoke(app, ["query-telemetry", "--resource-id", RESOURCE_ID])
    assert result.exit_code == 1
    assert CONNECTION not in result.output
    assert json.loads(result.output)["tables"][0]["rows"] == [[3]]
    assert json.loads(result.output)["error"]


@pytest.mark.parametrize("stage", ["auth", "factory", "query", "client_close", "credential_close"])
def test_query_errors(stage: str, clients: SimpleNamespace):
    {
        "auth": clients.auth,
        "factory": clients.factory,
        "query": clients.client.query_resource,
        "client_close": clients.client.close,
        "credential_close": clients.credential.close,
    }[stage].side_effect = AzureError(CONNECTION)
    result = CliRunner().invoke(app, ["query-telemetry", "--resource-id", RESOURCE_ID])
    assert result.exit_code == 1
    assert json.loads(result.output) == {"error": "Azure Application Insights query failed."}
    assert clients.credential.close.call_count == (stage != "auth")
    assert clients.client.close.call_count == (stage not in ("auth", "factory"))


@pytest.fixture
def telemetry(clients: SimpleNamespace):
    providers = [MagicMock() for _ in range(3)]
    for provider in providers:
        provider.force_flush.return_value = True
    handler = MagicMock(spec=logging.Handler)
    handler.level = logging.NOTSET

    def configure(**kwargs):
        logging.getLogger(kwargs["logger_name"]).addHandler(handler)

    with (
        patch(
            "template_azure_python.internals.azure.application_insights.configure_azure_monitor", side_effect=configure
        ) as config,
        patch(
            "template_azure_python.internals.azure.application_insights.trace.get_tracer_provider",
            return_value=providers[0],
        ),
        patch(
            "template_azure_python.internals.azure.application_insights.get_logger_provider", return_value=providers[1]
        ),
        patch(
            "template_azure_python.internals.azure.application_insights.metrics.get_meter_provider",
            return_value=providers[2],
        ),
        patch("template_azure_python.internals.azure.application_insights.trace.get_tracer") as get_tracer,
        patch("template_azure_python.internals.azure.application_insights.metrics.get_meter") as get_meter,
    ):
        yield SimpleNamespace(
            providers=providers,
            config=config,
            tracer=get_tracer.return_value,
            counter=get_meter.return_value.create_counter.return_value,
            handler=handler,
            clients=clients,
        )


@pytest.mark.parametrize("count", [None, 1, 4, 100])
def test_emit_all_signals(count: int | None, telemetry: SimpleNamespace):
    args = ["emit-telemetry"] + (["--count", str(count)] if count is not None else [])
    result = CliRunner().invoke(app, args, env={"APPLICATIONINSIGHTS_CONNECTION_STRING": CONNECTION})
    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    count = 10 if count is None else count
    run_id = output["run_id"]
    assert str(UUID(run_id)) == run_id
    assert output == {"run_id": run_id, "count": count, "flushed": True, "ingestion_guaranteed": False}
    assert telemetry.tracer.start_as_current_span.call_count == count
    assert telemetry.counter.add.call_count == count
    assert telemetry.handler.handle.call_count == count
    for sequence in range(1, count + 1):
        attributes = {"run_id": run_id, "sequence": sequence}
        span = telemetry.tracer.start_as_current_span.call_args_list[sequence - 1]
        assert span.kwargs == {"kind": SpanKind.SERVER, "attributes": attributes}
        metric = telemetry.counter.add.call_args_list[sequence - 1]
        assert metric.args == (1,)
        assert metric.kwargs == {"attributes": attributes}
        log_record = telemetry.handler.handle.call_args_list[sequence - 1].args[0]
        assert log_record.run_id == run_id
        assert log_record.sequence == sequence
    options = telemetry.config.call_args.kwargs
    assert options["connection_string"] == CONNECTION
    assert options["logger_name"].endswith(run_id)
    assert options["disable_offline_storage"] is True
    assert options["enable_live_metrics"] is False
    assert options["enable_performance_counters"] is False
    assert options["timeout"] == 5
    assert options["read_timeout"] == 5
    assert "connection_timeout" not in options
    assert options["instrumentation_options"] == {name: {"enabled": False} for name in INSTRUMENTATIONS}
    assert "credential" not in options
    telemetry.clients.auth.assert_not_called()
    for provider in telemetry.providers:
        provider.force_flush.assert_called_once_with(timeout_millis=FLUSH_TIMEOUT_MILLIS)
        provider.shutdown.assert_called_once()
    assert "secret" not in result.output


@pytest.mark.parametrize(
    "args",
    [
        ["--count", "0"],
        ["--count", "101"],
        ["--count", "invalid"],
        ["--connection-string", "not-accepted"],
        ["--key", "not-accepted"],
    ],
)
def test_emit_invalid_options(args: list[str], telemetry: SimpleNamespace):
    result = CliRunner().invoke(
        app, ["emit-telemetry", *args], env={"APPLICATIONINSIGHTS_CONNECTION_STRING": CONNECTION}
    )
    assert result.exit_code == 2
    telemetry.config.assert_not_called()
    telemetry.clients.auth.assert_not_called()


@pytest.mark.parametrize("connection", ["", " "])
def test_emit_missing_connection(connection: str, telemetry: SimpleNamespace):
    result = CliRunner().invoke(app, ["emit-telemetry"], env={"APPLICATIONINSIGHTS_CONNECTION_STRING": connection})
    assert result.exit_code == 2
    telemetry.config.assert_not_called()
    telemetry.clients.auth.assert_not_called()


@pytest.mark.parametrize("index", [0, 1, 2])
@pytest.mark.parametrize("mode", ["false", "exception", "log", "shutdown"])
def test_emit_flush_failures_are_independent_and_sanitized(index: int, mode: str, telemetry: SimpleNamespace):
    provider = telemetry.providers[index]
    if mode == "false":
        provider.force_flush.return_value = False
    elif mode == "exception":
        provider.force_flush.side_effect = RuntimeError(CONNECTION)
    elif mode == "shutdown":
        provider.shutdown.side_effect = RuntimeError(CONNECTION)
    else:

        def log_failure(**kwargs):
            try:
                raise RuntimeError(CONNECTION)
            except RuntimeError:
                logging.getLogger("azure.monitor.exporter.secret").exception(CONNECTION)
            return True

        provider.force_flush.side_effect = log_failure
    result = CliRunner().invoke(app, ["emit-telemetry"], env={"APPLICATIONINSIGHTS_CONNECTION_STRING": CONNECTION})
    assert result.exit_code == 1, result.output
    output = json.loads(result.output)
    assert output["flushed"] is False
    assert output["failures"]
    assert "secret" not in result.output
    for provider in telemetry.providers:
        provider.force_flush.assert_called_once_with(timeout_millis=FLUSH_TIMEOUT_MILLIS)
        provider.shutdown.assert_called_once()


@pytest.mark.parametrize("stage", ["configuration", "emission"])
def test_emit_exception_still_flushes(stage: str, telemetry: SimpleNamespace):
    if stage == "configuration":
        telemetry.config.side_effect = ValueError(CONNECTION)
    else:
        telemetry.counter.add.side_effect = RuntimeError(CONNECTION)
    result = CliRunner().invoke(app, ["emit-telemetry"], env={"APPLICATIONINSIGHTS_CONNECTION_STRING": CONNECTION})
    assert result.exit_code == 1
    assert "secret" not in result.output
    assert json.loads(result.output)["flushed"] is False
    for provider in telemetry.providers:
        provider.force_flush.assert_called_once()
        provider.shutdown.assert_called_once()


def test_unique_runs_and_logging_restored(telemetry: SimpleNamespace):
    root = logging.getLogger()
    handlers = root.handlers[:]
    results = [
        CliRunner().invoke(app, ["emit-telemetry"], env={"APPLICATIONINSIGHTS_CONNECTION_STRING": CONNECTION})
        for _ in range(2)
    ]
    assert all(result.exit_code == 0 for result in results)
    assert json.loads(results[0].output)["run_id"] != json.loads(results[1].output)["run_id"]
    assert root.handlers == handlers


def test_disable_auxiliary_telemetry_and_restore_environment(
    telemetry: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("OTEL_TRACES_SAMPLER", "always_off")
    monkeypatch.delenv("APPLICATIONINSIGHTS_STATSBEAT_DISABLED_ALL", raising=False)
    original_config = telemetry.config.side_effect

    def configure(**kwargs):
        assert os.environ["OTEL_TRACES_SAMPLER"] == "always_on"
        assert os.environ["APPLICATIONINSIGHTS_STATSBEAT_DISABLED_ALL"] == "true"
        assert os.environ["APPLICATIONINSIGHTS_SDKSTATS_DISABLED"] == "true"
        assert os.environ["APPLICATIONINSIGHTS_CONTROLPLANE_DISABLED"] == "true"
        original_config(**kwargs)

    telemetry.config.side_effect = configure
    result = CliRunner().invoke(app, ["emit-telemetry"], env={"APPLICATIONINSIGHTS_CONNECTION_STRING": CONNECTION})
    assert result.exit_code == 0, result.output
    assert os.environ["OTEL_TRACES_SAMPLER"] == "always_off"
    assert "APPLICATIONINSIGHTS_STATSBEAT_DISABLED_ALL" not in os.environ


def test_real_distro_exporter_construction_offline():
    # Global OTel providers are write-once; keep real SDK setup in a fresh process.
    script = textwrap.dedent("""
        import json
        from unittest.mock import patch
        from azure.monitor.opentelemetry.exporter._generated import AzureMonitorClient
        from azure.monitor.opentelemetry.exporter._generated.exporter.models import TrackResponse
        from typer.testing import CliRunner
        from scripts.cli_application_insights import app
        from template_azure_python.settings import AzureSettings

        AzureSettings.model_config["env_file"] = None

        uploaded = []

        def track(self, body, **kwargs):
            uploaded.extend(body)
            return TrackResponse(items_received=len(body), items_accepted=len(body), errors=[])

        with (
            patch.object(AzureMonitorClient, "track", track),
            patch("requests.sessions.Session.send", side_effect=AssertionError("Network forbidden")),
        ):
            result = CliRunner().invoke(app, ["emit-telemetry", "--count", "2"])
        assert result.exit_code == 0, result.output
        summary = json.loads(result.output)
        assert summary["flushed"] is True, summary
        assert summary["ingestion_guaranteed"] is False
        types = {item.data.base_type for item in uploaded}
        assert {"RequestData", "MessageData", "MetricData"} <= types, types
        assert len([item for item in uploaded if item.data.base_type == "RequestData"]) == 2
        assert len([item for item in uploaded if item.data.base_type == "MessageData"]) == 2
        print(result.output, end="")
    """)
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        env={
            **os.environ,
            "APPLICATIONINSIGHTS_CONNECTION_STRING": f"InstrumentationKey={GUID}",
            "OTEL_EXPERIMENTAL_RESOURCE_DETECTORS": "",
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["count"] == 2


@pytest.mark.parametrize("args", [[], ["query-telemetry"], ["emit-telemetry"]])
def test_help(args: list[str], telemetry: SimpleNamespace):
    result = CliRunner().invoke(app, [*args, "--help"])
    assert result.exit_code == 0
    telemetry.config.assert_not_called()
    telemetry.clients.auth.assert_not_called()


def test_main(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delitem(sys.modules, "scripts.cli_application_insights", raising=False)
    with patch("dotenv.load_dotenv") as dotenv, patch("typer.Typer.__call__") as invoke:
        runpy.run_module("scripts.cli_application_insights", run_name="__main__")
    dotenv.assert_not_called()
    invoke.assert_called_once_with()
