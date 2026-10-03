from collections import Counter
from contextlib import closing
from datetime import datetime, timedelta, timezone
from itertools import islice

from azure.identity import DefaultAzureCredential
from azure.mgmt.monitor import MonitorManagementClient
from azure.mgmt.monitor.models import EventData

from template_azure_python.internals.azure._common import (
    InputError,
    azure_errors,
    required_value,
    validate_guid,
    validate_resource_group,
)
from template_azure_python.settings import get_azure_settings


def _event_record(event: EventData) -> dict[str, object]:
    return {
        "event_data_id": event.event_data_id,
        "event_timestamp": event.event_timestamp,
        "resource_id": event.resource_id,
        "resource_group_name": event.resource_group_name,
        "operation_name": event.operation_name.value if event.operation_name is not None else None,
        "status": event.status.value if event.status is not None else None,
        "level": event.level,
    }


def _read_events(
    subscription_id: str | None, resource_group: str | None, hours: int, limit: int
) -> tuple[list[dict[str, object]], dict[str, object]]:
    settings = get_azure_settings()
    subscription_id = validate_guid(
        required_value(subscription_id, settings.resource.subscription_id, "--subscription-id")
    )
    resource_group = validate_resource_group(
        settings.resource.resource_group if resource_group is None else resource_group
    )
    if not 1 <= hours <= 168:
        raise InputError("must be between 1 and 168", "--hours")
    if not 1 <= limit <= 1000:
        raise InputError("must be between 1 and 1000", "--limit")
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=hours)
    start = start_time.isoformat().replace("+00:00", "Z")
    end = end_time.isoformat().replace("+00:00", "Z")
    expression = f"eventTimestamp ge '{start}' and eventTimestamp le '{end}'"
    if resource_group is not None:
        expression += f" and resourceGroupName eq '{resource_group}'"
    with azure_errors("Azure Activity Log request failed. Check Azure authentication and Reader access."):
        with closing(DefaultAzureCredential()) as credential:
            with closing(MonitorManagementClient(credential=credential, subscription_id=subscription_id)) as client:
                events = [_event_record(event) for event in islice(client.activity_logs.list(filter=expression), limit)]
    return events, {"start_time": start, "end_time": end, "limit": limit, "sample_count": len(events)}


def list_events(subscription_id: str | None, resource_group: str | None, hours: int, limit: int) -> dict[str, object]:
    events, metadata = _read_events(subscription_id, resource_group, hours, limit)
    return {**metadata, "events": events}


def summarize_events(
    subscription_id: str | None, resource_group: str | None, hours: int, limit: int
) -> dict[str, object]:
    events, metadata = _read_events(subscription_id, resource_group, hours, limit)
    return {
        **metadata,
        "by_status": dict(Counter(str(event["status"] or "(unknown)") for event in events)),
        "by_operation": dict(Counter(str(event["operation_name"] or "(unknown)") for event in events)),
    }
