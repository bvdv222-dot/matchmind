"""LiveMatch: the interpret layer's view of one match, fed message by message from the live feed.

Cheap things update on every message (score, possessions, value added, player tallies, physical maxima, instant
moments). Heavier views (team stats, windows, shifts, networks, fact sheets) are computed on demand from the events
seen so far, so every answer reflects exactly "now" and nothing from the future.
"""
from __future__ import annotations

import json
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

from contracts.models import League
from intel import expect, flow, ratings, shifts
from intel.common import ON_BALL, is_goal, match_minute
from intel.possessions import PossessionTracker
from intel.value import action_value
from intel.winprob import WinProbParams, probabilities
from intel.xg import chance_label, shot_xg

MODELS = Path(__file__).resolve().parent / "models"
SPEED_TAG_KMH = 33.0           # player tag: "top speed" overlay threshold
DISTANCE_MILESTONE_M = 10_000.0
CHECK_EVERY_MIN = 5.0


@lru_cache(maxsize=4)
def league_models(league_seed: int) -> dict:
    p = MODELS / f"league_{league_seed}.json"
    if not p.exists():
        raise FileNotFoundError(f"{p} missing: run `python -m intel.train --league-seed {league_seed}`")
    return json.loads(p.read_text(encoding="utf-8"))


class LiveMatch:
    def __init__(self, meta: dict, league: League):
        self.meta = meta
        self.match_id = meta["match_id"]
        self.home, self.away = meta["home"]["team_id"], meta["away"]["team_id"]
        self.team_name = {self.home: meta["home"]["name"], self.away: meta["away"]["name"]}
        self.team_short = {self.home: meta["home"]["short_name"], self.away: meta["away"]["short_name"]}
        self.players = {p.player_id: p for t in league.teams if t.team_id in (self.home, self.away) for p in t.players}
        self.models = league_models(league.seed)
        self.prematch = ratings.expected_goals(self.models["ratings"], self.home, self.away)
        self.wp_params = WinProbParams()
        self.events: list[dict] = []
        self.by_id: dict[str, dict] = {}
        self.values: dict[str, dict] = {}
        self.possessions = PossessionTracker()
        self.score = [0, 0]
        self.xg = [0.0, 0.0]
        self.reds = [0, 0]
        self.on_pitch = {pid: True for side in ("home", "away") for pid in
                         (p["player_id"] for p in meta[side]["starting"])}
        self.tally: dict[str, dict] = defaultdict(lambda: defaultdict(float))
        self.physical: dict[str, dict] = {}
        self.moments: list[dict] = []
        self.winprob_history: list[dict] = []
        self.last_frame: dict | None = None
        self._next_check = CHECK_EVERY_MIN
        self._last_momentum = "neither"
        self._announced_shifts: set[tuple] = set()
        self._speed_tagged: set[str] = set()
        self._distance_tagged: set[str] = set()

    # ------------------------------------------------------------------ helpers
    def side(self, team_id: str | None) -> int:
        return 0 if team_id == self.home else 1

    def name(self, pid: str | None) -> str:
        return self.players[pid].name if pid in self.players else "unknown"

    def short(self, pid: str | None) -> str:
        return self.players[pid].short_name if pid in self.players else "unknown"

    def minute(self) -> float:
        return match_minute(self.events[-1]) if self.events else 0.0

    def clock(self) -> str:
        return self.events[-1]["clock"] if self.events else "0'"

    def win_probability(self) -> dict:
        ph, pd, pa = probabilities(self.minute(), tuple(self.score), self.prematch, tuple(self.xg), tuple(self.reds),
                                   self.wp_params)
        return {"home": round(ph, 4), "draw": round(pd, 4), "away": round(pa, 4)}

    def _moment(self, kind: str, priority: int, e: dict, **data) -> dict:
        m = {"moment_id": f"{self.match_id}-M{len(self.moments):03d}", "kind": kind, "priority": priority,
             "period": e["period"], "t": e["t"], "minute": round(match_minute(e), 2), "clock": e["clock"],
             "event_ids": [e["event_id"]], **data}
        self.moments.append(m)
        return m

    # ------------------------------------------------------------------ ingest
    def ingest(self, msg: dict) -> list[dict]:
        """Feed one StreamMessage; returns any moments it produced."""
        before = len(self.moments)
        if msg["kind"] == "event":
            self._event(msg["data"])
        elif msg["kind"] == "frame":
            self._frame(msg["data"])
        return self.moments[before:]

    def _event(self, e: dict) -> None:
        self.events.append(e)
        self.by_id[e["event_id"]] = e
        closed = self.possessions.ingest(e)
        team, pid = e.get("team_id"), e.get("player_id")
        s = self.side(team)
        if e["type"] in ON_BALL:
            v = action_value(e)
            if v:
                self.values[e["event_id"]] = v
                self.tally[pid]["value_added"] += v["added"]
                cur = self.possessions.current
                if cur is not None and cur.team_id == team:
                    cur.value += v["added"]
            self.tally[pid]["touches"] += 1
        t = self.tally[pid] if pid else None
        if e["type"] == "pass" and t is not None:
            t["passes"] += 1
            t["passes_complete"] += e.get("outcome") == "complete"
            t["progressive_passes"] += flow._progressive(e)
            if "key_pass" in e.get("tags", []):
                t["key_passes"] += 1
            if "assist" in e.get("tags", []):
                t["assists"] += 1
        elif e["type"] == "shot":
            x = shot_xg(e)
            if e.get("subtype") == "penalty":
                self._moment("penalty", 7, e, team_id=team, player_ids=[pid], taker=self.name(pid))
            self.xg[s] += x
            t["shots"] += 1
            t["xg"] += x
            if is_goal(e):
                self._goal(e, x)
            elif x >= 0.25:
                self._moment("big_chance_missed", 6, e, team_id=team, player_ids=[pid], xg=round(x, 3),
                             outcome=e.get("outcome"), chance=chance_label(x))
        elif e["type"] == "take_on" and t is not None:
            t["take_ons"] += 1
            t["take_ons_won"] += e.get("outcome") == "won"
        elif e["type"] == "tackle" and t is not None:
            t["tackles_won"] += e.get("outcome") == "won"
        elif e["type"] == "interception" and t is not None:
            t["interceptions"] += 1
        elif e["type"] == "save":
            shot = self.events[-2] if len(self.events) > 1 and self.events[-2]["type"] == "shot" else None
            if shot and shot_xg(shot) >= 0.2:
                self._moment("big_save", 6, e, team_id=team, player_ids=[pid, shot.get("player_id")],
                             xg_faced=round(shot_xg(shot), 3), shooter=self.name(shot.get("player_id")))
        elif e["type"] == "card":
            red = e.get("subtype") in ("red", "second_yellow")
            if red:
                self.reds[s] += 1
                self.on_pitch[pid] = False
            self._moment("red_card" if red else "yellow_card", 8 if red else 2, e, team_id=team, player_ids=[pid],
                         card=e.get("subtype"), player=self.name(pid))
        elif e["type"] == "substitution":
            self.on_pitch[pid] = False
            self.on_pitch[e["related_player_id"]] = True
            self._moment("substitution", 2, e, team_id=team, player_ids=[pid, e["related_player_id"]],
                         off=self.name(pid), on=self.name(e["related_player_id"]))
        if closed is not None and closed.xg >= 0.25 and closed.goals == 0 and closed.shots >= 2:
            self._moment("sustained_pressure", 4, e, team_id=closed.team_id, xg=round(closed.xg, 3),
                         shots=closed.shots, passes=closed.passes)
        if match_minute(e) >= self._next_check or e["type"] == "period_end":
            self._periodic(e)
            while self._next_check <= match_minute(e):
                self._next_check += CHECK_EVERY_MIN

    def _goal(self, e: dict, x: float) -> None:
        s = self.side(e["team_id"])
        wp_before = self.win_probability()
        self.score[s] += 1
        wp_after = self.win_probability()
        poss = self.possessions.current
        assist = next((prev["player_id"] for prev in reversed(self.events[-4:-1])
                       if "assist" in prev.get("tags", [])), None)
        goals_by_player = sum(1 for ev in self.events if is_goal(ev) and ev.get("player_id") == e.get("player_id"))
        kind = "hat_trick" if goals_by_player == 3 else ("brace" if goals_by_player == 2 else "goal")
        self.tally[e["player_id"]]["goals"] += 1
        key = "home" if s == 0 else "away"
        swing = round(wp_after[key] - wp_before[key], 4)
        self._moment(kind, 9, e, team_id=e["team_id"], player_ids=[e["player_id"]] +
                     ([assist] if assist else []), scorer=self.name(e["player_id"]),
                     assist=self.name(assist) if assist else None, xg=round(x, 3), chance=chance_label(x),
                     body_part=e.get("body_part"), shot_type=e.get("subtype"), score=list(self.score),
                     win_prob_before=wp_before, win_prob_after=wp_after, win_prob_swing=swing,
                     possession={"passes": poss.passes, "duration_s": round(poss.duration_s, 1),
                                 "start_type": poss.start_type, "phase": flow.phase_of(poss)} if poss else None,
                     goal_number_for_player=goals_by_player)

    def _periodic(self, e: dict) -> None:
        now = match_minute(e)
        self.winprob_history.append({"minute": round(now, 2), "clock": e["clock"], **self.win_probability(),
                                     "score": list(self.score)})
        win = flow.windows(self.events, self.home)
        mom = flow.momentum(win)
        if mom["side"] != "neither" and mom["side"] != self._last_momentum:
            team = self.home if mom["side"] == "home" else self.away
            self._moment("momentum", 5, e, team_id=team, team=self.team_name[team], **mom)
        self._last_momentum = mom["side"]
        if win and flow.rhythm_label(win[-1]["chaos_index"]) == "chaotic":
            if not self.moments or self.moments[-1]["kind"] != "rhythm":
                self._moment("rhythm", 4, e, label="chaotic", chaos_index=win[-1]["chaos_index"])
        for sh in shifts.detect(self.events, self.team_name, now):
            key = (sh["team_id"], sh["metric"], sh["recent"] > sh["before"])
            if key not in self._announced_shifts:
                self._announced_shifts.add(key)
                self._moment("tactical_shift", 5, e, **{k: v for k, v in sh.items() if k != "p"})

    def _frame(self, f: dict) -> None:
        self.last_frame = f
        for p in f["players"]:
            ph = self.physical.setdefault(p["player_id"], {"top_speed_kmh": 0.0, "distance_m": 0.0, "sprints": 0,
                                                           "_fast": False})
            ph["distance_m"] = p["distance_m"]
            ph["top_speed_kmh"] = max(ph["top_speed_kmh"], p["speed_kmh"])
            fast = p["speed_kmh"] > 25.2
            ph["sprints"] += fast and not ph["_fast"]
            ph["_fast"] = fast
            if p["speed_kmh"] >= SPEED_TAG_KMH and p["player_id"] not in self._speed_tagged and self.events:
                self._speed_tagged.add(p["player_id"])
                self._moment("speed_tag", 3, self.events[-1], team_id=p["team_id"], player_ids=[p["player_id"]],
                             player=self.name(p["player_id"]), speed_kmh=p["speed_kmh"])
            if p["distance_m"] >= DISTANCE_MILESTONE_M and p["player_id"] not in self._distance_tagged and self.events:
                self._distance_tagged.add(p["player_id"])
                self._moment("distance_milestone", 2, self.events[-1], team_id=p["team_id"],
                             player_ids=[p["player_id"]], player=self.name(p["player_id"]),
                             distance_km=round(p["distance_m"] / 1000, 1))

    # ------------------------------------------------------------------ views
    def state(self) -> dict:
        cur = self.possessions.current
        return {"match_id": self.match_id, "clock": self.clock(), "minute": round(self.minute(), 2),
                "period": self.events[-1]["period"] if self.events else 1,
                "home": {"team_id": self.home, "name": self.team_name[self.home], "goals": self.score[0],
                         "xg": round(self.xg[0], 2), "red_cards": self.reds[0]},
                "away": {"team_id": self.away, "name": self.team_name[self.away], "goals": self.score[1],
                         "xg": round(self.xg[1], 2), "red_cards": self.reds[1]},
                "in_possession": self.team_name.get(cur.team_id) if cur else None,
                "win_probability": self.win_probability(),
                "prematch_expected_goals": [round(x, 2) for x in self.prematch],
                "finished": bool(self.events) and self.events[-1]["type"] == "period_end"
                and self.events[-1]["period"] == 2,
                "moments": len(self.moments), "events": len(self.events)}

    def share_played(self) -> float:
        return min(1.0, max(0.01, self.minute() / 95))

    def team_view(self, team_id: str) -> dict:
        opp = self.away if team_id == self.home else self.home
        stats = flow.team_stats(self.events, team_id, self.possessions.all())
        model = self.models["expect"]
        vs = {m: expect.compare(model, m, team_id, opp, team_id == self.home, stats[m], self.share_played())
              for m in expect.METRICS}
        return {"team_id": team_id, "name": self.team_name[team_id], "stats": stats, "vs_expected": vs,
                "phases": flow.phase_breakdown(self.possessions.all(), team_id),
                "network": flow.pass_network(self.events, team_id),
                "attack_standing": expect.standing(model, "xg", team_id, "offence"),
                "defence_standing": expect.standing(model, "xg", team_id, "defence")}

    def player_view(self, pid: str) -> dict:
        p = self.players[pid]
        t = {k: (round(v, 3) if k in ("value_added", "xg") else int(v)) for k, v in self.tally.get(pid, {}).items()}
        ph = {k: v for k, v in self.physical.get(pid, {}).items() if not k.startswith("_")}
        if "passes" in t and t["passes"]:
            t["pass_completion"] = round(t.get("passes_complete", 0) / t["passes"], 3)
        return {"player_id": pid, "name": p.name, "short_name": p.short_name, "team_id": p.team_id,
                "team": self.team_name.get(p.team_id), "position": p.position, "shirt": p.shirt, "age": p.age,
                "height_cm": p.height_cm, "foot": p.foot, "on_pitch": self.on_pitch.get(pid, False),
                "match": t, "physical": {k: round(v, 1) if isinstance(v, float) else v for k, v in ph.items()}}

    def top_players(self, team_id: str | None = None, n: int = 5) -> list[dict]:
        pids = [pid for pid in self.tally if pid in self.players and
                (team_id is None or self.players[pid].team_id == team_id)]
        pids.sort(key=lambda pid: -self.tally[pid].get("value_added", 0.0))
        return [{"player_id": pid, "name": self.name(pid), "team": self.team_name[self.players[pid].team_id],
                 "value_added": round(self.tally[pid].get("value_added", 0.0), 3)} for pid in pids[:n]]

    def explain_event(self, event_id: str) -> dict:
        e = self.by_id[event_id]
        v = self.values.get(event_id)
        out = {"event": e, "player": self.name(e.get("player_id")), "team": self.team_name.get(e.get("team_id"))}
        if v:
            out["value"] = v
        if e["type"] == "shot":
            x = shot_xg(e)
            out["xg"] = round(x, 3)
            out["chance"] = chance_label(x)
        return out

    def windows(self) -> list[dict]:
        return flow.windows(self.events, self.home)
