from enum import Enum

from azure.core.messaging import CloudEvent
from azure.eventgrid import EventGridEvent, EventGridPublisherClient

from template_azure_python.internals.azure._common import (
    managed_client,
    required_value,
    validate_endpoint,
    validate_json_object,
    validate_name,
)
from template_azure_python.settings import get_azure_settings


class EventSchema(str, Enum):
    EVENT_GRID = "event-grid"
    CLOUD_EVENT = "cloud-event"


def publish(
    endpoint: str | None,
    schema: EventSchema,
    subject: str,
    source: str,
    event_type: str,
    data: str,
    data_version: str,
    count: int,
    *,
    multiple: bool,
) -> dict[str, object]:
    endpoint = validate_endpoint(
        required_value(endpoint, get_azure_settings().event_grid.endpoint, "--endpoint"), allow_path=True
    )
    subject = validate_name(subject, "--subject")
    source = validate_name(source, "--source")
    event_type = validate_name(event_type, "--event-type")
    data_version = validate_name(data_version, "--data-version")
    payload = validate_json_object(data)
    events: list[EventGridEvent | CloudEvent] = []
    for _ in range(count):
        if schema == EventSchema.CLOUD_EVENT:
            events.append(
                CloudEvent(
                    source=source, type=event_type, subject=subject, data=payload, datacontenttype="application/json"
                )
            )
        else:
            events.append(
                EventGridEvent(subject=subject, event_type=event_type, data=payload, data_version=data_version)
            )
    with managed_client(
        "Event Grid", lambda credential: EventGridPublisherClient(endpoint=endpoint, credential=credential)
    ) as client:
        client.send(events if multiple else events[0])
    return {"schema": schema.value, "count": len(events), "ids": [event.id for event in events]}
