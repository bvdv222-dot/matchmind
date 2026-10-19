"""Expectation baselines: what a team usually produces against this kind of opponent, home or away.

Per metric, a ridge fit on last season's team-matches:
    y = mu + offence[team] + defence[opponent] + home * is_home
with the team terms shrunk towards zero by LAMBDA pseudo-matches. Live comparisons scale count metrics by the share
of the match played and widen the noise band early on, then put the gap into plain words.
"""
from __future__ import annotations

import math

import numpy as np

METRICS = ("xg", "shots", "passes", "pass_completion", "possession_share", "field_tilt", "progressive_passes",
           "ppda", "pressures", "crosses", "big_chances", "long_ball_share", "take_ons", "corners")
RATIOS = {"pass_completion", "possession_share", "field_tilt", "ppda", "long_ball_share"}
LOWER_IS_BETTER = {"ppda"}          # fewer passes allowed per defensive action = more intense pressing
LAMBDA = 4.0


def fit(rows: list[dict]) -> dict:
    """rows: {team, opp, home: bool, <metric>: value} per team-match."""
    teams = sorted({r["team"] for r in rows})
    idx = {t: i for i, t in enumerate(teams)}
    n, k = len(rows), 2 * len(teams) + 2
    x = np.zeros((n, k))
    for i, r in enumerate(rows):
        x[i, 0] = 1.0
        x[i, 1 + idx[r["team"]]] = 1.0
        x[i, 1 + len(teams) + idx[r["opp"]]] = 1.0
        x[i, -1] = 1.0 if r["home"] else 0.0
    pen = np.full(k, LAMBDA)
    pen[0] = pen[-1] = 0.0
    out = {"teams": teams, "metrics": {}}
    for m in METRICS:
        y = np.array([r[m] for r in rows], dtype=float)
        beta = np.linalg.solve(x.T @ x + np.diag(pen), x.T @ y)
        resid = y - x @ beta
        out["metrics"][m] = {
            "mu": round(float(beta[0]), 4), "home": round(float(beta[-1]), 4),
            "offence": {t: round(float(beta[1 + idx[t]]), 4) for t in teams},
            "defence": {t: round(float(beta[1 + len(teams) + idx[t]]), 4) for t in teams},
            "sd": round(float(resid.std()), 4), "league_mean": round(float(y.mean()), 4),
        }
    return out


def expected(model: dict, metric: str, team: str, opp: str, home: bool) -> float:
    m = model["metrics"][metric]
    return m["mu"] + m["offence"][team] + m["defence"][opp] + (m["home"] if home else 0.0)


def compare(model: dict, metric: str, team: str, opp: str, home: bool, actual: float, share_played: float) -> dict:
    """Actual so far vs expectation, with a z-score and words. share_played in (0, 1]."""
    f = min(1.0, max(0.05, share_played))
    m = model["metrics"][metric]
    full = expected(model, metric, team, opp, home)
    if metric in RATIOS:
        exp_now, sd_now = full, m["sd"] / math.sqrt(f)
    else:
        exp_now, sd_now = full * f, m["sd"] * math.sqrt(f)
    z = (actual - exp_now) / sd_now if sd_now > 0 else 0.0
    good = -z if metric in LOWER_IS_BETTER else z
    if abs(z) < 0.75:
        words = "about their usual"
    else:
        size = "well " if abs(z) >= 1.5 else ""
        words = f"{size}{'above' if z > 0 else 'below'} their usual"
    return {"metric": metric, "actual": round(actual, 3), "expected": round(exp_now, 3),
            "expected_full_match": round(full, 3), "z": round(z, 2), "words": words,
            "good_for_team": bool(good > 0.75), "concern": bool(good < -0.75)}


def standing(model: dict, metric: str, team: str, side: str = "offence") -> dict:
    """Where a team ranks in the league on a metric's offence (or defence) term, in words."""
    terms = model["metrics"][metric][side]
    higher_better = (side == "offence") != (metric in LOWER_IS_BETTER)
    order = sorted(terms, key=lambda t: -terms[t] if higher_better else terms[t])
    rank = order.index(team) + 1
    n = len(order)
    suffix = "th" if 10 <= rank % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(rank % 10, "th")
    if rank <= 3:
        band = "among the best"
    elif rank > n - 3:
        band = "among the weakest"
    elif rank <= n // 2:
        band = "in the top half"
    else:
        band = "in the bottom half"
    return {"rank": rank, "of": n, "words": f"{rank}{suffix} of {n}", "band": band}
