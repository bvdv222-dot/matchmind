"""Tactical shifts: has a team's share of the play changed, beyond what noise explains?

Compares the last `recent_min` minutes with the `before_min` minutes before them on share metrics (possession by
passes, field tilt by final-third passes, pressing by defensive actions high up), with a two-proportion z-test per
metric and team, then Benjamini-Hochberg across all of them so a busy match doesn't announce noise as tactics.
"""
from __future__ import annotations

import math

from intel.common import L, match_minute, ordinal, pt, third

Q_CLEAR = 0.10


def _phi(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def _counts(events: list[dict], team: str, lo: float, hi: float) -> dict[str, tuple[int, int]]:
    """(team's count, both teams' count) per share metric within [lo, hi) minutes."""
    es = [e for e in events if e.get("team_id") and lo <= match_minute(e) < hi]
    passes = [e for e in es if e["type"] == "pass"]
    f3 = [e for e in passes if third(e["start"]["x"]) == 2]
    high = [e for e in es
            if e["type"] in ("tackle", "interception", "pressure", "foul") and pt(e) and pt(e)[0] > 0.6 * L]
    mine = lambda xs: sum(e["team_id"] == team for e in xs)   # noqa: E731
    return {"possession": (mine(passes), len(passes)), "field_tilt": (mine(f3), len(f3)),
            "high_press": (mine(high), len(high))}


WORDS = {"possession": "share of the passes", "field_tilt": "share of final-third passes",
         "high_press": "share of defensive actions high up the pitch"}


def detect(events: list[dict], teams: dict[str, str], now_min: float, recent_min: float = 15,
           before_min: float = 30) -> list[dict]:
    """teams: team_id -> name (home first). Every metric is a share between the two teams, so it is tested once, from
    the home side, and reported from the side of the team whose share grew. Returns the clear shifts (q < Q_CLEAR),
    strongest first."""
    lo = max(0.0, now_min - recent_min)
    if lo < 20:          # need a real "before" to compare against
        return []
    tests = []
    ids = list(teams)
    for team, name in list(teams.items())[:1]:
        a = _counts(events, team, max(0.0, lo - before_min), lo)
        b = _counts(events, team, lo, now_min)
        for metric in a:
            (x1, n1), (x2, n2) = a[metric], b[metric]
            if n1 < 20 or n2 < 15:
                continue
            p1, p2 = x1 / n1, x2 / n2
            pool = (x1 + x2) / (n1 + n2)
            se = math.sqrt(pool * (1 - pool) * (1 / n1 + 1 / n2)) or 1e-9
            z = (p2 - p1) / se
            tests.append({"team_id": team, "team": name, "metric": metric, "before": round(p1, 3),
                          "recent": round(p2, 3), "z": round(z, 2), "p": 2 * (1 - _phi(abs(z))),
                          "since_minute": int(lo), "before_from": int(max(0.0, lo - before_min))})
    if not tests:
        return []
    tests.sort(key=lambda t: t["p"])
    m = len(tests)
    q_prev = 1.0
    for rank in range(m, 0, -1):        # BH step-up adjusted q-values
        t = tests[rank - 1]
        q_prev = min(q_prev, t["p"] * m / rank)
        t["q"] = round(q_prev, 4)
    out = []
    for t in tests:
        if t["q"] < Q_CLEAR:
            if t["recent"] < t["before"]:      # report it from the side that gained
                other = ids[1]
                t.update(team_id=other, team=teams[other], before=round(1 - t["before"], 3),
                         recent=round(1 - t["recent"], 3), z=-t["z"])
            direction = "risen"
            t["text"] = (f"Since the {ordinal(t['since_minute'])} minute, {t['team']}'s {WORDS[t['metric']]} has "
                         f"{direction} from {round(100 * t['before'])}% to {round(100 * t['recent'])}%")
            out.append(t)
    return sorted(out, key=lambda t: -abs(t["z"]))
