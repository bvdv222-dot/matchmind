"""Team strength the way an analyst would get it: fitted on last season's results, not read from the generator.

Multiplicative Poisson on a blend of goals and xG per team-match (xG is steadier over one season):
    expected(team vs opp) = base * home^is_home * attack[team] * defence[opp]
"""
from __future__ import annotations

import statistics as st
from collections import defaultdict

from intel.common import is_goal
from intel.xg import shot_xg

GOALS_WEIGHT = 0.4      # share of actual goals in the target (the rest is xG)


def team_match_targets(matches: list[tuple[dict, list[dict]]]) -> list[tuple[str, str, bool, float]]:
    """(team, opponent, is_home, blended goals) for every team-match; matches are (meta_dict, events)."""
    rows = []
    for meta, events in matches:
        h, a = meta["home"]["team_id"], meta["away"]["team_id"]
        g, x = defaultdict(float), defaultdict(float)
        for e in events:
            if e["type"] == "shot":
                x[e["team_id"]] += shot_xg(e)
                g[e["team_id"]] += is_goal(e)
        for team, opp, home in ((h, a, True), (a, h, False)):
            rows.append((team, opp, home, GOALS_WEIGHT * g[team] + (1 - GOALS_WEIGHT) * x[team]))
    return rows


def fit(matches: list[tuple[dict, list[dict]]], iters: int = 100) -> dict:
    rows = team_match_targets(matches)
    teams = sorted({r[0] for r in rows})
    att = dict.fromkeys(teams, 1.0)
    dfn = dict.fromkeys(teams, 1.0)
    home, base = 1.2, st.mean(r[3] for r in rows)
    for _ in range(iters):
        for t in teams:
            mine = [r for r in rows if r[0] == t]
            att[t] = sum(r[3] for r in mine) / sum(base * (home if r[2] else 1) * dfn[r[1]] for r in mine)
        for t in teams:
            vs = [r for r in rows if r[1] == t]
            dfn[t] = sum(r[3] for r in vs) / sum(base * (home if r[2] else 1) * att[r[0]] for r in vs)
        hr = [r for r in rows if r[2]]
        ar = [r for r in rows if not r[2]]
        home = (sum(r[3] for r in hr) / sum(base * att[r[0]] * dfn[r[1]] for r in hr)) / \
            (sum(r[3] for r in ar) / sum(base * att[r[0]] * dfn[r[1]] for r in ar))
        base = sum(r[3] for r in ar) / sum(att[r[0]] * dfn[r[1]] for r in ar)
        m = st.geometric_mean(att.values())
        att = {t: v / m for t, v in att.items()}
        base *= m
        m = st.geometric_mean(dfn.values())
        dfn = {t: v / m for t, v in dfn.items()}
        base *= m
    return {"base": round(base, 4), "home": round(home, 4), "attack": {t: round(v, 4) for t, v in att.items()},
            "defence": {t: round(v, 4) for t, v in dfn.items()}, "team_matches": len(rows)}


def expected_goals(r: dict, home_id: str, away_id: str) -> tuple[float, float]:
    """Pre-match expected goals (home, away) from fitted ratings."""
    lh = r["base"] * r["home"] * r["attack"][home_id] * r["defence"][away_id]
    la = r["base"] * r["attack"][away_id] * r["defence"][home_id]
    return lh, la
