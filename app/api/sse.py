"""EventBus por caso + formato SSE (CONTRATOS_API §7). Uma instância (Railway): em memória.

Cada evento ganha `id` sequencial por caso; o histórico permite retomar com `Last-Event-ID`."""

import asyncio
import json
from collections import defaultdict
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

HEARTBEAT_S = 15


@dataclass(frozen=True)
class ServerEvent:
    id: int
    event: str
    data: Any

    def as_sse(self) -> dict[str, str]:
        return {"id": str(self.id), "event": self.event, "data": json.dumps(self.data, default=str)}


class EventBus:
    def __init__(self) -> None:
        self._history: dict[str, list[ServerEvent]] = defaultdict(list)
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)

    def publish(self, case_id: str, event: str, data: Any) -> ServerEvent:
        history = self._history[case_id]
        item = ServerEvent(id=len(history) + 1, event=event, data=data)
        history.append(item)
        for queue in self._subscribers[case_id]:
            queue.put_nowait(item)
        return item

    def history(self, case_id: str, after: int = 0) -> list[ServerEvent]:
        return [e for e in self._history.get(case_id, []) if e.id > after]

    async def subscribe(self, case_id: str, after: int = 0) -> AsyncIterator[ServerEvent]:
        """Primeiro o que ficou depois de `after`, depois os eventos ao vivo."""
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers[case_id].add(queue)
        try:
            for item in self.history(case_id, after):
                yield item
            while True:
                yield await queue.get()
        finally:
            self._subscribers[case_id].discard(queue)
