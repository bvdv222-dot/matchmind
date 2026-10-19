"""Where notes, their agent traces and viewer questions are kept: the audit trail behind every published sentence.

MM_STORE=memory (default, local) or cosmos (Azure: COSMOS_ENDPOINT + COSMOS_DATABASE, managed identity, no keys).
Writes never block or break the broadcast: a failed write is logged and dropped.
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from collections import defaultdict

log = logging.getLogger("matchmind.store")


class MemoryStore:
    kind = "memory"

    def __init__(self) -> None:
        self.items: dict[str, list[dict]] = defaultdict(list)

    async def put(self, container: str, doc: dict) -> None:
        self.items[container].append(doc)
        del self.items[container][:-500]

    async def close(self) -> None:
        pass


class CosmosStore:
    kind = "cosmos"

    def __init__(self, endpoint: str, database: str) -> None:
        from azure.cosmos.aio import CosmosClient
        from azure.identity.aio import DefaultAzureCredential
        self._cred = DefaultAzureCredential()
        self._client = CosmosClient(endpoint, credential=self._cred)
        self._db = self._client.get_database_client(database)

    async def put(self, container: str, doc: dict) -> None:
        try:
            await self._db.get_container_client(container).upsert_item(doc)
        except Exception as e:          # the audit trail must never stop the match
            log.warning("cosmos write to %s failed: %s", container, e)

    async def close(self) -> None:
        await self._client.close()
        await self._cred.close()


def make_store():
    if os.environ.get("MM_STORE", "memory") == "cosmos" and os.environ.get("COSMOS_ENDPOINT"):
        return CosmosStore(os.environ["COSMOS_ENDPOINT"], os.environ.get("COSMOS_DATABASE", "matchmind"))
    return MemoryStore()


def record(match_id: str, kind: str, **fields) -> dict:
    """A store document: id, partition key (match_id), kind and a timestamp."""
    return {"id": str(uuid.uuid4()), "match_id": match_id, "kind": kind, "ts": time.time(), **fields}
