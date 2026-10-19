"""Shared helpers for the interpret layer. Event coordinates are in the acting team's attacking frame."""
from __future__ import annotations

import math

L, W = 105.0, 68.0
ON_BALL = ("pass", "carry", "take_on", "shot")
SET_PIECES = ("throw_in", "goal_kick", "corner", "free_kick", "kick_off")
THIRDS = ("defensive third", "middle third", "final third")


def is_goal(e: dict) -> bool:
    return e["type"] == "shot" and e.get("outcome") == "goal"


def pt(e: dict, key: str = "start") -> tuple[float, float] | None:
    p = e.get(key)
    return (p["x"], p["y"]) if p else None


def flip(p: tuple[float, float]) -> tuple[float, float]:
    return L - p[0], W - p[1]


def third(x: float) -> int:
    return 0 if x < L / 3 else (1 if x < 2 * L / 3 else 2)


def goal_distance(x: float, y: float) -> float:
    return math.hypot(L - x, y - W / 2)


def goal_angle(x: float, y: float) -> float:
    dx = L - x
    a = math.atan2(7.32 * dx, dx * dx + (y - W / 2) ** 2 - 3.66 ** 2)
    return a + math.pi if a < 0 else a


def match_minute(e: dict) -> float:
    """Continuous match minutes (first-half stoppage stays in the first half's 45+ minutes)."""
    return e["t"] / 60 + (45.0 if e["period"] == 2 else 0.0)


def pct(x: float, digits: int = 0) -> str:
    return f"{100 * x:.{digits}f}%"


def ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"
