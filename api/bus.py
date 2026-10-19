"""The live feed on the event bus: every match's events, state and overlays (and a sample of frames) are published to
Event Hubs, partitioned by match, for downstream consumers such as Fabric Real-Time Intelligence.

MM_BUS=memory (default, local: kept in a short ring buffer) or eventhubs (EVENTHUBS_FQDN + EVENTHUB_NAME, managed
identity). Publishing is batched and never blocks the broadcast.
"""
from __future__ import annotations

import json
import logging
import os
from collections import deque

log = logging.getLogger("matchmind.bus")


class MemoryBus:
    kind = "memory"

    def __init__(self) -> None:
        self.sent: deque = deque(maxlen=2000)

    async def publish(self, match_id: str, messages: list[dict]) -> None:
        self.sent.extend(messages)

    async def close(self) -> None:
        pass


class EventHubsBus:
    kind = "eventhubs"

    def __init__(self, fqdn: str, hub: str) -> None:
        from azure.eventhub.aio import EventHubProducerClient
        from azure.identity.aio import DefaultAzureCredential
        self._cred = DefaultAzureCredential()
        self._producer = EventHubProducerClient(fully_qualified_namespace=fqdn, eventhub_name=hub,
                                                credential=self._cred)

    async def publish(self, match_id: str, messages: list[dict]) -> None:
        if not messages:
            return
        from azure.eventhub import EventData
        try:
            batch = await self._producer.create_batch(partition_key=match_id)
            for m in messages:
                ev = EventData(json.dumps(m, separators=(",", ":")))
                try:
                    batch.add(ev)
                except ValueError:                       # batch full: send it and start another
                    await self._producer.send_batch(batch)
                    batch = await self._producer.create_batch(partition_key=match_id)
                    batch.add(ev)
            await self._producer.send_batch(batch)
        except Exception as e:
            log.warning("event hubs publish failed: %s", e)

    async def close(self) -> None:
        await self._producer.close()
        await self._cred.close()


def make_bus():
    if os.environ.get("MM_BUS", "memory") == "eventhubs" and os.environ.get("EVENTHUBS_FQDN"):
        return EventHubsBus(os.environ["EVENTHUBS_FQDN"], os.environ.get("EVENTHUB_NAME", "match-feed"))
    return MemoryBus()
