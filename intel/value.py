"""Possession value: how much an action changed a team's expected goal difference over the next few actions.

States are pitch cells (NX x NY, in the acting team's attacking frame). From an on-ball action in cell s, play moves
to the next on-ball action: the same team in cell k (probability Ps[s,k]), the opponent in cell k (Po[s,k], seen
from their side), or a goal (r[s]). With a per-action discount gamma (horizon about 1 / (1 - gamma) actions), the
value V(s) = expected discounted (own goals - opponent goals) solves one zero-sum linear system:

    V = r + gamma * (Ps - Po) V        ->        (I - gamma (Ps - Po)) V = r

An action's value added is the value after it (the receiver's cell, the opponent's cell after a turnover, or 1 for a
goal) minus the value before it. Trained on synthetic seasons by `python -m intel.train`; the model is a small JSON
grid in intel/models/.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np

from intel.common import ON_BALL, L, W, flip, is_goal, pt

NX, NY = 12, 8
GAMMA = 0.9
MODEL = Path(__file__).resolve().parent / "models" / "value_grid.json"


def cell(x: float, y: float) -> int:
    i = min(NX - 1, max(0, int(x / L * NX)))
    j = min(NY - 1, max(0, int(y / W * NY)))
    return j * NX + i


def fit(matches: list[list[dict]], gamma: float = GAMMA) -> dict:
    n = NX * NY
    same = np.zeros((n, n))
    opp = np.zeros((n, n))
    goal = np.zeros(n)
    visits = np.zeros(n)
    for events in matches:
        on = [e for e in events if e["type"] in ON_BALL or e["type"] == "period_end"]
        for a, b in zip(on, on[1:]):
            if a["type"] == "period_end":
                continue
            s = cell(*pt(a))
            visits[s] += 1
            if is_goal(a):
                goal[s] += 1
            elif b["type"] == "period_end" or b["period"] != a["period"]:
                continue                      # absorbed at 0 by the end of the half
            elif b["team_id"] == a["team_id"]:
                same[s, cell(*pt(b))] += 1
            else:
                opp[s, cell(*pt(b))] += 1
    tot = np.maximum(visits, 1)
    ps, po, r = same / tot[:, None], opp / tot[:, None], goal / tot
    v = np.linalg.solve(np.eye(n) - gamma * (ps - po), r)
    return {"nx": NX, "ny": NY, "gamma": gamma, "values": np.round(v.reshape(NY, NX), 5).tolist(),
            "visits": visits.reshape(NY, NX).astype(int).tolist(), "matches": len(matches)}


@lru_cache(maxsize=1)
def _grid() -> np.ndarray:
    if not MODEL.exists():
        raise FileNotFoundError(f"{MODEL} missing: run `python -m intel.train`")
    return np.array(json.loads(MODEL.read_text(encoding="utf-8"))["values"]).ravel()


def value_at(x: float, y: float) -> float:
    return float(_grid()[cell(x, y)])


def action_value(e: dict) -> dict | None:
    """Value before / after / added for one on-ball event, from what the event itself shows."""
    if e["type"] not in ON_BALL or "start" not in e:
        return None
    start = pt(e)
    before = value_at(*start)
    end = pt(e, "end")
    out = e.get("outcome")
    if e["type"] == "shot":
        # a miss hands the ball back near the opponent's goal (goal kick, keeper's ball, or a scramble)
        after = 1.0 if out == "goal" else -value_at(*flip((8.0, W / 2)))
        how = "scored" if out == "goal" else f"shot {out.replace('_', ' ')}"
    elif e["type"] == "carry" or out in ("complete", "won", "neutral"):
        target = end or start
        after = value_at(*target)
        how = "kept the ball"
    else:
        lost_at = end or start
        after = -value_at(*flip(lost_at))
        how = "lost the ball"
    return {"event_id": e["event_id"], "before": round(before, 4), "after": round(after, 4),
            "added": round(after - before, 4), "how": how}
