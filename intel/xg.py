"""Expected goals for a shot event.

Open play uses the logistic model fitted on 8,451 real Premier League shots (calibration/params_wyscout_pl1718.json:
distance, goal angle, header). Penalties and direct free kicks use their real conversion rates. This is the app's
own analysis model: it sees only what a feed provides (location, body part, shot type), not the generator's
hidden player and team ratings.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

from intel.common import goal_angle, goal_distance

CALIBRATION = Path(__file__).resolve().parents[1] / "calibration" / "params_wyscout_pl1718.json"


@lru_cache(maxsize=1)
def _model() -> dict:
    cal = json.loads(CALIBRATION.read_text(encoding="utf-8"))["shots"]
    return {"coef": cal["xg_model"], "penalty": cal["penalty"]["conversion"],
            "free_kick": cal["direct_free_kick"]["conversion"]}


def xg_at(x: float, y: float, header: bool = False) -> float:
    c = _model()["coef"]
    z = c["b0"] + c["b1"] * goal_distance(x, y) + c["b2"] * goal_angle(x, y) + c["b3"] * header
    return 1 / (1 + math.exp(-z))


def shot_xg(e: dict) -> float:
    sub = e.get("subtype")
    if sub == "penalty":
        return _model()["penalty"]
    if sub == "free_kick":
        return _model()["free_kick"]
    return xg_at(e["start"]["x"], e["start"]["y"], e.get("body_part") == "head")


def chance_label(xg: float) -> str:
    """Plain words for chance quality, used in fact sheets."""
    if xg >= 0.5:
        return "a gilt-edged chance"
    if xg >= 0.25:
        return "a big chance"
    if xg >= 0.1:
        return "a decent chance"
    if xg >= 0.04:
        return "a half-chance"
    return "a speculative effort"
