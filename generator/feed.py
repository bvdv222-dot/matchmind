"""The live feed: a match as an ordered sequence of StreamMessage dicts, optionally paced in real time.

Shared by the CLI's `stream` command and (from day 3) the publisher that puts the feed on the event bus.
"""
from __future__ import annotations

import heapq
import json
import time
from collections.abc import Iterator

from contracts.models import MatchMeta


def messages(meta: MatchMeta, events: list[dict], frames: list[dict] | None = None) -> Iterator[dict]:
    """Meta first, then events and frames merged by match time (events win ties, so a frame never shows a
    moment before its event has been announced)."""
    yield {"kind": "meta", "data": json.loads(meta.model_dump_json())}
    ev = ((e["period"], e["t"], 0, i, "event", e) for i, e in enumerate(events))
    fr = ((f["period"], f["t"], 1, i, "frame", f) for i, f in enumerate(frames or []))
    for *_, kind, data in heapq.merge(ev, fr):
        yield {"kind": kind, "data": data}


def match_seconds(msg: dict, half_length: float) -> float:
    d = msg["data"]
    return (half_length if d["period"] == 2 else 0.0) + d["t"]


def paced(msgs: Iterator[dict], events: list[dict], speed: float) -> Iterator[dict]:
    """Yield messages at match pace / speed (half-time skipped)."""
    first_half = next(e["t"] for e in events if e["type"] == "period_end")
    start = time.monotonic()
    for m in msgs:
        if m["kind"] != "meta":
            wait = match_seconds(m, first_half) / speed - (time.monotonic() - start)
            if wait > 0:
                time.sleep(wait)
        yield m
