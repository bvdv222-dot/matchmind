"""Matches the MCP server knows about, and the feeds that keep their LiveMatch views current.

Today the feed is an in-process replay of a simulated fixture (paced in a background thread, or fast-forwarded to a
minute). From day 3 the same registry reads the live feed from the event bus instead; tools don't change.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from generator.engine import simulate
from generator.feed import match_seconds, messages
from generator.frames import build_frames
from generator.league import build_league
from generator.season import Fixture, fixtures, match_seed
from intel.live import LiveMatch


@dataclass
class Running:
    fixture: Fixture
    live: LiveMatch
    queue: list[dict]                 # messages not yet delivered
    first_half_s: float
    lock: threading.Lock = field(default_factory=threading.Lock)
    speed: float = 0.0
    thread: threading.Thread | None = None
    stop: threading.Event = field(default_factory=threading.Event)

    def deliver_until(self, match_s: float) -> int:
        n = 0
        with self.lock:
            while self.queue and match_seconds(self.queue[0], self.first_half_s) <= match_s:
                self.live.ingest(self.queue.pop(0))
                n += 1
        return n


class Registry:
    def __init__(self, league_seed: int = 2026):
        self.league = build_league(league_seed)
        self.teams = {t.team_id: t for t in self.league.teams}
        self.fixtures = fixtures(self.league)
        self.by_id = {f.match_id: f for f in self.fixtures}
        self.running: dict[str, Running] = {}

    def find_fixture(self, match_id: str | None = None, home: str | None = None, away: str | None = None) -> Fixture:
        if match_id:
            if match_id not in self.by_id:
                raise KeyError(f"unknown match_id {match_id}")
            return self.by_id[match_id]
        code = {t.short_name: t.team_id for t in self.league.teams}
        h, a = code.get(home, home), code.get(away, away)
        for f in self.fixtures:
            if f.home == h and f.away == a:
                return f
        raise KeyError(f"no fixture {home} v {away}")

    def load(self, fx: Fixture, with_frames: bool = False) -> Running:
        if fx.match_id in self.running:
            return self.running[fx.match_id]
        k = [f.match_id for f in self.fixtures].index(fx.match_id)
        home, away = self.teams[fx.home], self.teams[fx.away]
        meta, events = simulate(home, away, seed=match_seed(self.league, k), match_id=fx.match_id,
                                round_no=fx.round, kickoff_utc=fx.kickoff_utc)
        frames = build_frames(meta, events, {home.team_id: home, away.team_id: away}) if with_frames else None
        msgs = list(messages(meta, events, frames))
        live = LiveMatch(msgs[0]["data"], self.league)
        first_half = next(e["t"] for e in events if e["type"] == "period_end")
        run = Running(fx, live, msgs[1:], first_half)
        self.running[fx.match_id] = run
        return run

    def start(self, fx: Fixture, speed: float = 10.0, with_frames: bool = False) -> Running:
        """Play the match in the background at `speed` x real time."""
        run = self.load(fx, with_frames)
        if run.thread and run.thread.is_alive():
            return run
        run.speed = speed
        played = match_seconds(run.queue[0], run.first_half_s) if run.queue else 0.0

        def loop() -> None:
            t0 = time.monotonic()
            while run.queue and not run.stop.is_set():
                run.deliver_until(played + (time.monotonic() - t0) * speed)
                time.sleep(0.2)

        run.thread = threading.Thread(target=loop, daemon=True, name=f"feed-{fx.match_id}")
        run.thread.start()
        return run

    def advance(self, fx: Fixture, to_minute: float) -> Running:
        """Fast-forward (never rewind) to a match minute; 95+ plays to the end."""
        run = self.load(fx)
        run.deliver_until(to_minute * 60 if to_minute < 95 else float("inf"))
        return run

    def get(self, match_id: str) -> Running:
        if match_id not in self.running:
            raise KeyError(f"match {match_id} is not loaded: call start_match or advance_match first")
        return self.running[match_id]

    def status(self, fx: Fixture) -> str:
        run = self.running.get(fx.match_id)
        if run is None:
            return "not started"
        return "finished" if not run.queue else ("live" if run.thread and run.thread.is_alive() else "paused")
