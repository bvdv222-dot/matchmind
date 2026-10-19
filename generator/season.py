"""Season mode: a double round-robin fixture list, simulated results and the league table."""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, UTC

from contracts.models import League, MatchMeta
from generator.engine import simulate

SEASON_START = datetime(2026, 8, 15, 14, 0, tzinfo=UTC)   # Saturday
SLOTS = [(0, 11, 30), (0, 14, 0), (0, 14, 0), (0, 14, 0), (0, 16, 30), (1, 13, 0), (1, 15, 30), (1, 15, 30),
         (2, 19, 0), (0, 14, 0)]                                  # (day offset from Saturday, hour, minute) UTC


@dataclass
class Fixture:
    round: int
    home: str
    away: str
    kickoff_utc: str
    match_id: str


@dataclass
class Row:
    team_id: str
    played: int = 0
    won: int = 0
    drawn: int = 0
    lost: int = 0
    gf: int = 0
    ga: int = 0
    form: list[str] = field(default_factory=list)

    @property
    def points(self) -> int:
        return 3 * self.won + self.drawn

    @property
    def gd(self) -> int:
        return self.gf - self.ga


def fixtures(league: League, seed: int | None = None) -> list[Fixture]:
    """Circle-method double round robin: every pair meets home and away, venues alternate so no club has long home
    or away runs, and the second half of the season mirrors the first with venues swapped."""
    rng = random.Random(league.seed if seed is None else seed)
    ids = [t.team_id for t in league.teams]
    rng.shuffle(ids)
    n = len(ids)
    rounds = []
    order = ids[:]
    last = {t: "A" for t in ids}       # venue of each club's previous match
    homes = {t: 0 for t in ids}
    for _ in range(n - 1):
        pairs = []
        for i in range(n // 2):
            a, b = order[i], order[n - 1 - i]
            # greedy venue choice: give home to whoever was away last time, then whoever has fewer home games
            score_ab = (last[a] == "A") + (last[b] == "H") - 0.01 * (homes[a] - homes[b])
            score_ba = (last[b] == "A") + (last[a] == "H") - 0.01 * (homes[b] - homes[a])
            h, aw = (a, b) if score_ab >= score_ba else (b, a)
            pairs.append((h, aw))
            last[h], last[aw] = "H", "A"
            homes[h] += 1
        rounds.append(pairs)
        order = [order[0]] + [order[-1]] + order[1:-1]
    rounds += [[(b, a) for a, b in pairs] for pairs in rounds]
    out = []
    for r, pairs in enumerate(rounds, start=1):
        base = SEASON_START + timedelta(days=7 * (r - 1))
        slots = SLOTS[:]
        rng.shuffle(slots)
        for k, (h, a) in enumerate(pairs):
            day, hh, mm = slots[k % len(slots)]
            ko = (base + timedelta(days=day)).replace(hour=hh, minute=mm)
            out.append(Fixture(r, h, a, ko.isoformat(), f"{league.league_id}-R{r:02d}-{h}{a}"))
    return out


def table(rows: dict[str, Row]) -> list[Row]:
    return sorted(rows.values(), key=lambda r: (-r.points, -r.gd, -r.gf, r.team_id))


def play_season(league: League, rounds: int | None = None, keep_events: bool = False):
    """Simulate the season (or its first `rounds` rounds). Returns (fixtures, results, table, matches) where
    matches holds (meta, events) per fixture only when keep_events is set."""
    teams = {t.team_id: t for t in league.teams}
    rows = {tid: Row(tid) for tid in teams}
    results, matches = [], []
    for k, fx in enumerate(fixtures(league)):
        if rounds is not None and fx.round > rounds:
            break
        meta, events = simulate(teams[fx.home], teams[fx.away], seed=league.seed * 1000 + k, match_id=fx.match_id,
                                round_no=fx.round, kickoff_utc=fx.kickoff_utc)
        hg = sum(1 for e in events if e["type"] == "shot" and e.get("outcome") == "goal" and e["team_id"] == fx.home)
        ag = sum(1 for e in events if e["type"] == "shot" and e.get("outcome") == "goal" and e["team_id"] == fx.away)
        results.append({"round": fx.round, "match_id": fx.match_id, "home": fx.home, "away": fx.away,
                        "home_goals": hg, "away_goals": ag, "kickoff_utc": fx.kickoff_utc})
        for tid, gf, ga in ((fx.home, hg, ag), (fx.away, ag, hg)):
            r = rows[tid]
            r.played += 1
            r.gf += gf
            r.ga += ga
            res = "W" if gf > ga else ("D" if gf == ga else "L")
            r.won += res == "W"
            r.drawn += res == "D"
            r.lost += res == "L"
            r.form = (r.form + [res])[-5:]
        if keep_events:
            matches.append((meta, events))
    return fixtures(league), results, table(rows), matches


def meta_for(league: League, fx: Fixture) -> MatchMeta:
    teams = {t.team_id: t for t in league.teams}
    k = [f.match_id for f in fixtures(league)].index(fx.match_id)
    meta, _ = simulate(teams[fx.home], teams[fx.away], seed=league.seed * 1000 + k, match_id=fx.match_id,
                       round_no=fx.round, kickoff_utc=fx.kickoff_utc)
    return meta
