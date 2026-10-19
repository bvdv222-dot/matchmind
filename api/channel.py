"""A live match channel: follows the registry's LiveMatch and pushes what each viewer should see.

Every tick it sends the latest position frame and match state, turns new moments into deterministic overlays (score
bug, win probability, moment cards, speed tags), and hands triggers to the agent worker, whose verified notes go to
each viewer in their chosen persona and language.
"""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field

from fastapi import WebSocket

from agents.personas import Persona, default_personas
from agents.workflow import Trigger, build_workflow
from api.bus import MemoryBus
from api.store import MemoryStore, record
from intel import facts
from mcp_server.registry import Running

TICK_S = 0.25
FRAME_SAMPLE = 4             # publish every 4th frame to the bus (2 Hz match time is plenty for consumers)
TRIGGER_PRIORITY = 5
QUIET_MINUTES = 15
STALE_MINUTES = 6            # a moment older than this when the agents get to it is folded into the next note
NOTE_HISTORY = 30


@dataclass(eq=False)
class Viewer:
    ws: WebSocket
    persona: str = "casual"
    lang: str = "en"
    focus_player: str | None = None


@dataclass
class Channel:
    run: Running
    languages: list[str]
    agents_on: bool
    viewers: set[Viewer] = field(default_factory=set)
    notes: list[dict] = field(default_factory=list)          # published note bundles (all audiences / languages)
    overlays: list[dict] = field(default_factory=list)       # deterministic overlays so far
    agent_log: list[dict] = field(default_factory=list)
    _moment_i: int = 0
    _last_frame_t: tuple | None = None
    _last_state: dict | None = None
    _pending: list[dict] = field(default_factory=list)
    _last_note_min: float = 0.0
    _half_time_sent: bool = False
    _full_time_sent: bool = False
    _busy: bool = False
    _task: asyncio.Task | None = None
    _agent_task: asyncio.Task | None = None
    _queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    store: object = field(default_factory=MemoryStore)
    bus: object = field(default_factory=MemoryBus)
    _event_i: int = 0
    _frames_seen: int = 0
    _bg: set = field(default_factory=set)

    @property
    def match_id(self) -> str:
        return self.run.fixture.match_id

    # ------------------------------------------------------------------ lifecycle
    def start(self, intel, agents: dict | None, names: dict) -> None:
        self.names = names
        self.workflow = build_workflow(intel, agents) if agents else None
        self._task = asyncio.create_task(self._pump(), name=f"pump-{self.match_id}")
        if self.workflow:
            self._agent_task = asyncio.create_task(self._agent_worker(), name=f"agents-{self.match_id}")

    def stop(self) -> None:
        for t in (self._task, self._agent_task):
            if t:
                t.cancel()

    # ------------------------------------------------------------------ viewers
    async def add(self, v: Viewer) -> None:
        self.viewers.add(v)
        lm = self.run.live
        with self.run.lock:
            hello = {"type": "hello", "data": {"meta": lm.meta, "state": lm.state(),
                                               "personas": [p.__dict__ for p in self.personas()]}}
        await self._send(v, hello)
        # history only: replayed overlays fill the lists but don't pop up as fresh cards
        for o in self.overlays[-20:]:
            await self._send(v, {"type": "overlay", "data": o, "replay": True})
        for bundle in self.notes[-8:]:
            await self._send(v, {"type": "overlay", "data": self.pick(bundle, v), "replay": True})

    def remove(self, v: Viewer) -> None:
        self.viewers.discard(v)

    async def _send(self, v: Viewer, msg: dict) -> None:
        try:
            await v.ws.send_json(msg)
        except Exception:
            self.viewers.discard(v)

    async def broadcast(self, msg: dict) -> None:
        await asyncio.gather(*(self._send(v, msg) for v in list(self.viewers)))

    def personas(self) -> list[Persona]:
        lm = self.run.live
        focus = sorted({v.focus_player for v in self.viewers if v.focus_player})[:2]
        out = default_personas(lm.home, lm.away)
        for pid in focus:
            out += [p for p in default_personas(lm.home, lm.away, pid) if p.player_id == pid]
        return out

    def pick(self, bundle: list[dict], v: Viewer) -> dict:
        """The best version of a note for one viewer: their persona and language, else their persona in English,
        else the neutral note."""
        persona = f"player_{v.focus_player}" if v.persona == "player" and v.focus_player else v.persona
        for want_aud, want_lang in ((persona, v.lang), (persona, "en"), ("all", "en")):
            for o in bundle:
                if o["audience"] == [want_aud] and o["lang"] == want_lang:
                    return o
        return bundle[0]

    # ------------------------------------------------------------------ the pump
    async def _pump(self) -> None:
        while True:
            await asyncio.sleep(TICK_S)
            run, lm = self.run, self.run.live
            with run.lock:
                state = lm.state()
                frame = lm.last_frame
                new_moments = lm.moments[self._moment_i:]
                self._moment_i = len(lm.moments)
                new_events = lm.events[self._event_i:]
                self._event_i = len(lm.events)
                wp = lm.win_probability()
            to_bus = [{"kind": "event", "data": e} for e in new_events]
            if frame and (frame["period"], frame["t"]) != self._last_frame_t:
                self._last_frame_t = (frame["period"], frame["t"])
                await self.broadcast({"type": "frame", "data": frame})
                self._frames_seen += 1
                if self._frames_seen % FRAME_SAMPLE == 0:
                    to_bus.append({"kind": "frame", "data": frame})
            if state != self._last_state:
                self._last_state = state
                await self.broadcast({"type": "state", "data": {**state, "win_probability": wp}})
                to_bus.append({"kind": "state", "data": {**state, "win_probability": wp}})
            for m in new_moments:
                o = self._moment_overlay(m)
                if o:
                    self.overlays.append(o)
                    await self.broadcast({"type": "overlay", "data": o})
                    to_bus.append({"kind": "overlay", "data": o})
                if m["priority"] >= TRIGGER_PRIORITY:
                    self._pending.append(m)
            if to_bus:
                self._background(self.bus.publish(self.match_id, to_bus))
            await self._maybe_trigger(state)
            if state.get("finished") and self._full_time_sent and not self._busy and self._queue.empty():
                await self.broadcast({"type": "finished", "data": state})
                return

    def _background(self, coro) -> None:
        """Bus and store writes run alongside the broadcast, never in its way."""
        task = asyncio.create_task(coro)
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

    def _moment_overlay(self, m: dict) -> dict | None:
        lm = self.run.live
        kind = {"goal": "moment_card", "brace": "moment_card", "hat_trick": "moment_card", "red_card": "moment_card",
                "penalty": "moment_card", "big_chance_missed": "moment_card", "big_save": "moment_card",
                "tactical_shift": "stat_tile", "momentum": "stat_tile", "rhythm": "stat_tile",
                "speed_tag": "player_tag", "distance_milestone": "player_tag", "substitution": "stat_tile",
                "yellow_card": "stat_tile", "sustained_pressure": "stat_tile"}.get(m["kind"])
        if not kind:
            return None
        with self.run.lock:
            text = facts.headline(lm, m)
        prio = 9 if m["kind"] in ("goal", "brace", "hat_trick") else min(8, m["priority"])
        return {"msg_id": m["moment_id"], "match_id": self.match_id, "kind": kind,
                "at": {"period": m["period"], "t": m["t"], "clock": m["clock"]},
                "ttl_s": 12.0 if prio >= 8 else 7.0, "priority": prio, "audience": ["all"], "lang": "en",
                "title": m["kind"].replace("_", " ").title(), "body": text,
                "data": {k: m.get(k) for k in ("team_id", "player_ids", "xg", "score", "win_prob_after", "speed_kmh",
                                                "win_prob_swing")},
                "source_event_ids": m.get("event_ids", []), "verified": True}

    async def _maybe_trigger(self, state: dict) -> None:
        if not self.workflow:
            if state.get("finished"):
                self._full_time_sent = True
            return
        minute = state.get("minute", 0.0)
        reason = None
        if state.get("finished") and not self._full_time_sent:
            self._full_time_sent, kind, reason = True, "recap", "full_time"
        elif state.get("period") == 2 and not self._half_time_sent:
            self._half_time_sent, kind, reason = True, "recap", "half_time"
        elif self._pending and not self._busy:
            kind, reason = "live_note", "moment"
        elif minute - self._last_note_min >= QUIET_MINUTES and not self._busy and self._queue.empty() and minute > 5:
            kind, reason = "live_note", "check_in"
        if reason:
            moments, self._pending = self._pending, []
            if reason == "check_in":
                self._last_note_min = minute        # don't re-ask while this check-in is being written
            await self._queue.put((kind, reason, moments))

    async def _agent_worker(self) -> None:
        while True:
            kind, reason, moments = await self._queue.get()
            # coalesce a backlog into one note, so the commentary keeps up with the match (a recap wins)
            while not self._queue.empty():
                k2, r2, m2 = self._queue.get_nowait()
                if k2 == "recap":
                    kind, reason = k2, r2
                moments += m2
            with self.run.lock:
                now = self.run.live.minute()
            if kind == "live_note":         # moments that slow models left behind are old news: keep the recent
                moments = [m for m in moments if now - m["minute"] <= STALE_MINUTES] or moments[-1:]
            self._busy = True
            t0 = time.monotonic()
            trig = Trigger(self.match_id, kind, moments, self.personas(), self.languages, self.names, reason)
            try:
                res = await self.workflow.run(trig)
                job = res.get_outputs()[0]
            except Exception as e:      # the broadcast never stops for a failed note
                self.agent_log.append({"error": str(e)[:300], "kind": kind})
                self._busy = False
                continue
            self.agent_log.append({"clock": job.state.get("clock"), "kind": kind, "reason": reason,
                                   "skipped": job.skipped, "seconds": round(time.monotonic() - t0, 1),
                                   "note_source": job.note_source, "trace": job.trace})
            del self.agent_log[:-50]
            self._background(self.store.put("notes", record(
                self.match_id, "note", clock=job.state.get("clock"), note_kind=kind, reason=reason,
                skipped=job.skipped, plan=job.plan, note=job.note, note_source=job.note_source, trace=job.trace,
                overlays=job.overlays)))
            if job.overlays:
                self._background(self.bus.publish(self.match_id, [{"kind": "overlay", "data": o}
                                                                  for o in job.overlays]))
            if not job.skipped and job.overlays:
                # the quiet-period clock restarts only when something was actually said
                self._last_note_min = job.state.get("minute", self._last_note_min)
                self.notes.append(job.overlays)
                del self.notes[:-NOTE_HISTORY]
                await asyncio.gather(*(self._send(v, {"type": "overlay", "data": self.pick(job.overlays, v)})
                                       for v in list(self.viewers)))
            self._busy = False


def agents_enabled() -> bool:
    return os.environ.get("MM_AGENTS", "on").lower() not in ("0", "off", "false", "no")
