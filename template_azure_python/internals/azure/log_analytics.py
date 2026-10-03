from contextlib import closing
from datetime import timedelta

from azure.identity import DefaultAzureCredential
from azure.monitor.query import LogsQueryClient

from template_azure_python.internals.azure._common import (
    azure_errors,
    format_logs_result,
    required_value,
    validate_guid,
)
from template_azure_python.settings import get_azure_settings


def query_logs(workspace_id: str | None, hours: int, limit: int, *, summarize: bool = False) -> dict[str, object]:
    workspace_id = validate_guid(
        required_value(workspace_id, get_azure_settings().log_analytics.workspace_id, "--workspace-id")
    )
    query = f"AzureActivity | where TimeGenerated >= ago({hours}h)"
    if summarize:
        query += " | summarize Count=count() by OperationNameValue, ActivityStatusValue | order by Count desc"
    else:
        query += (
            " | project TimeGenerated, OperationNameValue, ActivityStatusValue, ResourceGroup, ResourceId"
            " | order by TimeGenerated desc"
        )
    query += f" | take {limit}"
    with azure_errors("Azure Log Analytics query failed."):
        with closing(DefaultAzureCredential()) as credential, closing(LogsQueryClient(credential)) as client:
            result = client.query_workspace(workspace_id, query, timespan=timedelta(hours=hours), server_timeout=30)
            return format_logs_result(result)
