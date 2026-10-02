"""Shared resource identifiers and Azure Logs JSON formatting."""

import re

import typer
from azure.monitor.query import LogsQueryPartialResult, LogsQueryResult, LogsQueryStatus

_GUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_SEGMENT = re.compile(r"[a-zA-Z0-9_().-]+")
_ERROR_CODE = re.compile(r"[a-zA-Z][a-zA-Z0-9_.-]{0,127}")


def validate_guid(value: str) -> str:
    """Require a dashed UUID without disclosing invalid input."""
    if not isinstance(value, str) or not _GUID.fullmatch(value):
        raise typer.BadParameter("must be a dashed UUID")
    return value


def validate_arm_id(value: str, provider: str, resource_type: str) -> tuple[str, str, str]:
    """Validate an absolute, single-resource ARM ID before authentication."""
    message = "must be an absolute ARM resource ID for the required resource type"
    if not isinstance(value, str):
        raise typer.BadParameter(message)
    parts = value.split("/")
    if (
        len(parts) != 9
        or parts[0] != ""
        or parts[1].lower() != "subscriptions"
        or not _GUID.fullmatch(parts[2])
        or parts[3].lower() != "resourcegroups"
        or parts[5].lower() != "providers"
        or parts[6].lower() != provider.lower()
        or parts[7].lower() != resource_type.lower()
        or any(
            not _SEGMENT.fullmatch(part) or part in (".", "..") or part.endswith(".") for part in (parts[4], parts[8])
        )
    ):
        raise typer.BadParameter(message)
    return parts[2], parts[4], parts[8]


def format_logs_result(result: LogsQueryResult | LogsQueryPartialResult) -> dict:
    """Preserve tabular results, but never include service error text or details."""
    partial = result.status == LogsQueryStatus.PARTIAL
    tables = result.partial_data if isinstance(result, LogsQueryPartialResult) else result.tables
    output: dict = {
        "tables": [
            {
                "name": table.name,
                "columns": [
                    {"name": name, "type": column_type} for name, column_type in zip(table.columns, table.columns_types)
                ],
                "rows": [list(row) for row in table.rows],
            }
            for table in tables
        ]
    }
    if partial:
        error = result.partial_error if isinstance(result, LogsQueryPartialResult) else None
        code = getattr(error, "code", None)
        output["error"] = {
            "code": code if isinstance(code, str) and _ERROR_CODE.fullmatch(code) else "PartialError",
            "message": "Azure Logs query returned partial results.",
        }
    return output
