import json
from datetime import datetime, timezone

import pytest
import typer
from azure.monitor.query import LogsQueryError, LogsQueryPartialResult, LogsQueryResult, LogsTable

from scripts._azure_messaging import print_json
from scripts._azure_observability import format_logs_result, validate_arm_id, validate_guid

GUID = "01234567-89ab-cdef-0123-456789abcdef"
RESOURCE_ID = f"/subscriptions/{GUID}/resourceGroups/rg-test/providers/Microsoft.Insights/components/app-test"


@pytest.mark.parametrize("value", [GUID, GUID.upper()])
def test_guid(value: str):
    assert validate_guid(value) == value


@pytest.mark.parametrize("value", [None, 123, [], {}, "", "secret", GUID.replace("-", ""), f" {GUID}", f"{GUID}\n"])
def test_invalid_guid_is_sanitized(value):
    with pytest.raises(typer.BadParameter, match="must be a dashed UUID") as error:
        validate_guid(value)
    assert "secret" not in str(error.value)


def test_arm_id():
    assert validate_arm_id(RESOURCE_ID, "microsoft.insights", "components") == (GUID, "rg-test", "app-test")
    assert validate_arm_id(RESOURCE_ID.upper(), "Microsoft.Insights", "components") == (
        GUID.upper(),
        "RG-TEST",
        "APP-TEST",
    )


@pytest.mark.parametrize(
    "value",
    [
        None,
        123,
        [],
        {},
        "",
        "secret",
        RESOURCE_ID.replace(GUID, "secret"),
        RESOURCE_ID.replace("components", "workspaces"),
        RESOURCE_ID.replace("Microsoft.Insights", "Microsoft.Other"),
        RESOURCE_ID + "/child",
        RESOURCE_ID + "/",
        RESOURCE_ID + "?secret=value",
        RESOURCE_ID + "#secret",
        RESOURCE_ID.replace("app-test", ".."),
        RESOURCE_ID.replace("app-test", "%2Fsecret"),
        RESOURCE_ID.replace("app-test", "app\\secret"),
        RESOURCE_ID.replace("rg-test", "rg secret"),
        RESOURCE_ID + "\n",
    ],
)
def test_invalid_arm_id_is_sanitized(value):
    with pytest.raises(typer.BadParameter) as error:
        validate_arm_id(value, "Microsoft.Insights", "components")
    assert "secret" not in str(error.value)


@pytest.mark.parametrize("partial", [False, True])
@pytest.mark.parametrize("empty", [False, True])
def test_logs_format(partial: bool, empty: bool, capsys: pytest.CaptureFixture):
    timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    tables = (
        []
        if empty
        else [
            LogsTable(
                name="PrimaryResult",
                columns=["TimeGenerated", "Count"],
                columns_types=["datetime", "long"],
                rows=[[timestamp, 2], [None, 0]],
            )
        ]
    )
    result = (
        LogsQueryPartialResult(partial_data=tables, partial_error={"message": "secret"})
        if partial
        else LogsQueryResult(tables=tables)
    )
    output = format_logs_result(result)
    print_json(output)
    serialized = capsys.readouterr().out
    data = json.loads(serialized)
    assert "secret" not in serialized
    assert ("error" in data) == partial
    assert data["tables"] == (
        []
        if empty
        else [
            {
                "name": "PrimaryResult",
                "columns": [{"name": "TimeGenerated", "type": "datetime"}, {"name": "Count", "type": "long"}],
                "rows": [["2026-01-01T00:00:00+00:00", 2], [None, 0]],
            }
        ]
    )


@pytest.mark.parametrize("code", ["PartialError", "QueryExecutionError", "LimitsExceeded"])
def test_partial_error_service_code(code: str):
    result = LogsQueryPartialResult(
        partial_error=LogsQueryError(code=code, message="secret", details={"credential": "secret"}),
    )
    output = format_logs_result(result)
    assert output == {
        "tables": [],
        "error": {"code": code, "message": "Azure Logs query returned partial results."},
    }
    assert "secret" not in json.dumps(output)


@pytest.mark.parametrize("code", [None, 3, {}, "", "secret=value", "secret\nvalue", "x" * 129])
def test_unsafe_partial_error_code(code):
    result = LogsQueryPartialResult(partial_error=LogsQueryError(code=code, message="secret"))
    output = format_logs_result(result)
    assert output["error"]["code"] == "PartialError"
    assert "secret" not in json.dumps(output)
