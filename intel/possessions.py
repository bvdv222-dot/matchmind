"""Live possession tracking: one record per spell on the ball, updated event by event.

The feed's `possession` counter marks a change of control; a record collects the possessing team's on-ball
actions plus how the spell started and ended.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from intel.common import L, SET_PIECES, is_goal, match_minute, pt, third
from intel.xg import shot_xg

ENDINGS = {"interception": "intercepted", "tackle": "tackled", "ball_recovery": "lost loose ball",
           "clearance": "cleared", "ball_out": "ball out of play", "foul": "foul", "offside": "offside",
           "save": "saved", "period_end": "end of half"}


@dataclass
class Possession:
    pid: int
    team_id: str
    period: int
    start_minute: float
    start_type: str = "open play"
    start_x: float | None = None
    end_minute: float = 0.0
    end_type: str = "ongoing"
    actions: int = 0
    passes: int = 0
    passes_complete: int = 0
    max_x: float = 0.0
    final_third: bool = False
    box_entry: bool = False
    shots: int = 0
    xg: float = 0.0
    goals: int = 0
    value: float = 0.0               # possession value added (filled by intel.value)
    event_ids: list[str] = field(default_factory=list)

    @property
    def duration_s(self) -> float:
        return max(0.0, (self.end_minute - self.start_minute) * 60)

    def as_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "event_ids"}
        d["duration_s"] = round(self.duration_s, 1)
        d["xg"] = round(self.xg, 3)
        d["value"] = round(self.value, 4)
        return d


class PossessionTracker:
    def __init__(self) -> None:
        self.done: list[Possession] = []
        self.current: Possession | None = None
        self._last_opp_action: str | None = None

    def ingest(self, e: dict) -> Possession | None:
        """Feed one event; returns the possession that just closed, if any."""
        closed = None
        team = e.get("possession_team_id")
        if self.current is not None and (e["possession"] != self.current.pid or e["type"] == "period_end"):
            if e["type"] == "period_end":
                self.current.end_type = ENDINGS["period_end"]
            closed = self._close(e)
        if e["type"] in ("period_start", "period_end") or team is None:
            return closed
        if self.current is None:
            self.current = Possession(e["possession"], team, e["period"], match_minute(e))
            if self._last_opp_action:
                self.current.start_type = {"interception": "interception", "tackle": "tackle won",
                                           "ball_recovery": "loose ball won", "save": "goalkeeper"} \
                    .get(self._last_opp_action, "open play")
        p = self.current
        p.end_minute = match_minute(e)
        acting = e.get("team_id")
        if acting == p.team_id and e["type"] in ("pass", "carry", "take_on", "shot"):
            if p.actions == 0 and e["type"] == "pass" and e.get("subtype") in SET_PIECES:
                p.start_type = e["subtype"].replace("_", " ")
            if p.start_x is None:
                p.start_x = pt(e)[0]
            p.actions += 1
            p.event_ids.append(e["event_id"])
            # an end point counts only if the team actually had the ball there
            arrived = e["type"] == "carry" or e.get("outcome") in ("complete", "won")
            for key in ("start", "end"):
                xy = pt(e, key)
                if xy and (key == "start" or arrived):
                    p.max_x = max(p.max_x, xy[0])
                    p.final_third |= third(xy[0]) == 2
                    p.box_entry |= xy[0] >= 88.5 and 13.84 <= xy[1] <= 54.16
            if e["type"] == "pass":
                p.passes += 1
                p.passes_complete += e.get("outcome") == "complete"
            if e["type"] == "shot":
                p.shots += 1
                p.xg += shot_xg(e)
                p.goals += is_goal(e)
                p.end_type = "goal" if is_goal(e) else "shot"
        elif acting and acting != p.team_id:
            self._last_opp_action = e["type"]
            if p.end_type not in ("goal", "shot") and e["type"] in ENDINGS:
                p.end_type = ENDINGS[e["type"]]
        elif e["type"] in ("ball_out", "foul", "offside") and p.end_type not in ("goal", "shot"):
            p.end_type = ENDINGS[e["type"]]
        return closed

    def _close(self, e: dict) -> Possession:
        p = self.current
        if p.end_type == "ongoing":
            p.end_type = "turnover"
        self.done.append(p)
        self.current = None
        if e.get("team_id") == p.team_id:
            self._last_opp_action = None
        return p

    def all(self) -> list[Possession]:
        return self.done + ([self.current] if self.current else [])


def summarise(possessions: list[Possession], team_id: str) -> dict:
    mine = [p for p in possessions if p.team_id == team_id and p.actions > 0]
    if not mine:
        return {"possessions": 0}
    n = len(mine)
    return {
        "possessions": n,
        "avg_passes": round(sum(p.passes for p in mine) / n, 2),
        "avg_duration_s": round(sum(p.duration_s for p in mine) / n, 1),
        "final_third_entries": sum(p.final_third for p in mine),
        "box_entries": sum(p.box_entry for p in mine),
        "shot_possessions": sum(p.shots > 0 for p in mine),
        "share_ending_in_shot": round(sum(p.shots > 0 for p in mine) / n, 3),
        "avg_start_x": round(sum(p.start_x or 0 for p in mine) / n, 1),
        "high_regains": sum(p.start_type in ("interception", "tackle won", "loose ball won")
                            and (p.start_x or 0) >= 2 * L / 3 - 5 for p in mine),
    }
