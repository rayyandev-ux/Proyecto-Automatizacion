from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Union


CAR_ACQUIRED = "car.acquired"
INSPECTION_COMPLETED = "inspection.completed"
CAR_REJECTED = "car.rejected"
PUBLICATION_READY = "publication.ready"
PUBLISHED = "car.published"
LEAD_RECEIVED = "lead.received"
LEAD_QUALIFIED = "lead.qualified"
LEAD_DISCARDED = "lead.discarded"
NEGOTIATION_STARTED = "negotiation.started"
SALE_COMPLETED = "sale.completed"
NEGOTIATION_FAILED = "negotiation.failed"


@dataclass(frozen=True)
class Event:
    event_type: str
    payload: dict[str, Any]
    timestamp: datetime
    source_agent: str


Callback = Callable[[Event], Union[Any, Awaitable[Any]]]


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callback]] = {}
        self._history: list[Event] = []

    def subscribe(self, event_type: str, callback: Callback) -> None:
        self._subscribers.setdefault(event_type, []).append(callback)

    def publish(self, event: Event) -> None:
        self._history.append(event)
        for callback in self._subscribers.get(event.event_type, []):
            try:
                result = callback(event)
                if asyncio.iscoroutine(result):
                    asyncio.create_task(result)
            except Exception:
                continue

    def get_history(self) -> list[Event]:
        return list(self._history)


event_bus = EventBus()


def new_event(event_type: str, payload: dict[str, Any], source_agent: str) -> Event:
    return Event(
        event_type=event_type,
        payload=payload,
        timestamp=datetime.now(timezone.utc),
        source_agent=source_agent,
    )
