"""Deterministic point-in-time event queue."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import heapq
from typing import Iterator

from .types import Event


@dataclass(order=True)
class _QueuedEvent:
    available_at: datetime
    priority: int
    source: str
    source_sequence: int
    event_id: str
    event: Event = field(compare=False)


class EventQueue:
    """Priority queue ordered by knowledge time, event priority and sequence."""

    def __init__(self) -> None:
        self._heap: list[_QueuedEvent] = []
        self._clock: datetime | None = None
        self._event_ids: set[str] = set()

    @property
    def clock(self) -> datetime | None:
        return self._clock

    def __len__(self) -> int:
        return len(self._heap)

    def push(self, event: Event) -> None:
        if self._clock is not None and event.process_at < self._clock:
            raise ValueError("retroactive event rejected by point-in-time clock")
        if event.event_id in self._event_ids:
            raise ValueError(f"duplicate event_id: {event.event_id}")
        self._event_ids.add(event.event_id)
        heapq.heappush(
            self._heap,
            _QueuedEvent(
                event.process_at,
                int(event.kind),
                str(event.source),
                int(event.source_sequence),
                event.event_id,
                event,
            ),
        )

    def pop(self) -> Event:
        if not self._heap:
            raise IndexError("event queue is empty")
        item = heapq.heappop(self._heap)
        if self._clock is not None and item.available_at < self._clock:
            raise RuntimeError("event clock moved backwards")
        self._clock = item.available_at
        return item.event

    def drain(self) -> Iterator[Event]:
        while self._heap:
            yield self.pop()
