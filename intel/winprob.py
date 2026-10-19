"""Live win probability.

Goals still to come for each side are Poisson with mean = expected rate x minutes left, where the rate blends the
pre-match expectation (team ratings) with what the match has shown so far (xG per minute), leaning on the match more
as it goes. Red cards and the trailing side's late push adjust the rates. P(home / draw / away) then follows from
the current score. Parameters are tuned and checked (Brier score, calibration by decile) on held-out synthetic
matches by `python -m intel.train`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

MATCH_MINUTES = 95.0        # 90 + typical stoppage


@dataclass
class WinProbParams:
    # weight on the observed xG rate by full time: 0 is best on held-out matches (Brier 0.456 vs 0.459 at 0.45),
    # because last season's ratings are a strong prior; momentum is shown separately (field tilt, xG flow)
    live_weight_full: float = 0.0
    red_card_for: float = 0.75         # rate multiplier for a side a player down
    red_card_against: float = 1.25     # ... and for their opponents
    trailing_push: float = 1.15        # rate multiplier for the trailing side after 70'
    leading_sit: float = 0.85          # ... and for the leader


def _poisson(lam: float, kmax: int = 12) -> list[float]:
    p = [math.exp(-lam)]
    for k in range(1, kmax + 1):
        p.append(p[-1] * lam / k)
    return p


def probabilities(minute: float, score: tuple[int, int], prematch: tuple[float, float],
                  xg_so_far: tuple[float, float] = (0.0, 0.0), reds: tuple[int, int] = (0, 0),
                  params: WinProbParams | None = None) -> tuple[float, float, float]:
    """(home win, draw, away win) at `minute` (continuous match minutes)."""
    prm = params or WinProbParams()
    left = max(0.0, MATCH_MINUTES - minute)
    played = max(1.0, minute)
    w = prm.live_weight_full * min(1.0, minute / 90)
    rates = []
    for side in (0, 1):
        pre = prematch[side] / MATCH_MINUTES
        live = xg_so_far[side] / played
        rate = (1 - w) * pre + w * live
        rate *= prm.red_card_for ** reds[side] * prm.red_card_against ** reds[1 - side]
        rates.append(rate)
    if minute >= 70 and score[0] != score[1]:
        lead = 0 if score[0] > score[1] else 1
        rates[lead] *= prm.leading_sit
        rates[1 - lead] *= prm.trailing_push
    ph, pa = _poisson(rates[0] * left), _poisson(rates[1] * left)
    home = draw = away = 0.0
    for i, pi in enumerate(ph):
        for j, pj in enumerate(pa):
            d = (score[0] + i) - (score[1] + j)
            p = pi * pj
            if d > 0:
                home += p
            elif d == 0:
                draw += p
            else:
                away += p
    s = home + draw + away
    return home / s, draw / s, away / s


def timeline(events: list[dict], home_id: str, prematch: tuple[float, float], every_min: float = 1.0,
             params: WinProbParams | None = None) -> list[dict]:
    """Win probability after every goal, red card and at a regular cadence, for charts and swing detection."""
    from intel.common import is_goal, match_minute
    from intel.xg import shot_xg
    out, score, xg, reds = [], [0, 0], [0.0, 0.0], [0, 0]
    next_tick = 0.0
    for e in events:
        m = match_minute(e)
        side = 0 if e.get("team_id") == home_id else 1
        changed = False
        if e["type"] == "shot":
            xg[side] += shot_xg(e)
            if is_goal(e):
                score[side] += 1
                changed = True
        elif e["type"] == "card" and e.get("subtype") in ("red", "second_yellow"):
            reds[side] += 1
            changed = True
        if changed or m >= next_tick or e["type"] == "period_end":
            ph, pd, pa = probabilities(m, tuple(score), prematch, tuple(xg), tuple(reds), params)
            out.append({"minute": round(m, 2), "clock": e["clock"], "event_id": e["event_id"], "score": list(score),
                        "home": round(ph, 4), "draw": round(pd, 4), "away": round(pa, 4)})
            while next_tick <= m:
                next_tick += every_min
    return out
