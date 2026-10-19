"""Team statistics, game phases, rhythm ("control vs chaos"), pressing and pass networks.

Everything here is a pure function of the events seen so far (plus possessions from intel.possessions), so the live
layer can recompute it at any moment. League norms for the rhythm index come from intel/models/norms.json.
"""
from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

from intel.common import L, W, goal_distance, is_goal, match_minute, pt, third
from intel.possessions import Possession
from intel.xg import shot_xg

NORMS = Path(__file__).resolve().parent / "models" / "norms.json"
DEFENSIVE_ACTIONS = ("tackle", "interception", "foul")      # the standard PPDA set
CHAOS_TYPES = ("interception", "tackle", "ball_recovery", "aerial_duel", "clearance", "take_on")


@lru_cache(maxsize=1)
def norms() -> dict:
    return json.loads(NORMS.read_text(encoding="utf-8")) if NORMS.exists() else {}


def _progressive(e: dict) -> bool:
    """A completed pass that moves the ball at least 25% closer to goal and 10 m upfield."""
    s, t = pt(e), pt(e, "end")
    if not (s and t) or e.get("outcome") != "complete":
        return False
    return t[0] - s[0] >= 10 and goal_distance(*t) <= 0.75 * goal_distance(*s)


def team_stats(events: list[dict], team_id: str, possessions: list[Possession] | None = None) -> dict:
    mine = [e for e in events if e.get("team_id") == team_id]
    theirs = [e for e in events if e.get("team_id") and e.get("team_id") != team_id]
    passes = [e for e in mine if e["type"] == "pass" and e.get("outcome") != "offside"]
    opp_passes = [e for e in theirs if e["type"] == "pass" and e.get("outcome") != "offside"]
    done = [e for e in passes if e.get("outcome") == "complete"]
    shots = [e for e in mine if e["type"] == "shot"]
    xgs = [shot_xg(e) for e in shots]
    final3 = sum(1 for e in passes if third(e["start"]["x"]) == 2)
    opp_final3 = sum(1 for e in opp_passes if third(e["start"]["x"]) == 2)
    # PPDA: opponent passes in their own 60% of the pitch per defensive action we make in that area
    opp_build = sum(1 for e in opp_passes if e["start"]["x"] < 0.6 * L)
    def_actions = sum(1 for e in mine if e["type"] in DEFENSIVE_ACTIONS and pt(e) and pt(e)[0] > 0.4 * L)
    lengths = [math.dist(pt(e), pt(e, "end")) for e in passes if "end" in e]
    out = {
        "goals": sum(is_goal(e) for e in shots),
        "shots": len(shots),
        "shots_on_target": sum(e.get("outcome") in ("goal", "saved") for e in shots),
        "xg": round(sum(xgs), 3),
        "big_chances": sum(x >= 0.25 for x in xgs),
        "xg_per_shot": round(sum(xgs) / len(shots), 3) if shots else 0.0,
        "passes": len(passes),
        "pass_completion": round(len(done) / len(passes), 3) if passes else 0.0,
        "possession_share": round(len(passes) / max(1, len(passes) + len(opp_passes)), 3),
        "field_tilt": round(final3 / max(1, final3 + opp_final3), 3),
        "progressive_passes": sum(_progressive(e) for e in passes),
        "crosses": sum(e.get("subtype") == "cross" for e in passes),
        "long_ball_share": round(sum(x >= 30 for x in lengths) / max(1, len(lengths)), 3),
        "avg_pass_length_m": round(sum(lengths) / max(1, len(lengths)), 1),
        "take_ons_won": sum(e["type"] == "take_on" and e.get("outcome") == "won" for e in mine),
        "take_ons": sum(e["type"] == "take_on" for e in mine),
        "pressures": sum(e["type"] == "pressure" for e in mine),
        "ppda": round(opp_build / max(1, def_actions), 2),
        "tackles_won": sum(e["type"] == "tackle" and e.get("outcome") == "won" for e in mine),
        "interceptions": sum(e["type"] == "interception" for e in mine),
        "corners": sum(e["type"] == "pass" and e.get("subtype") == "corner" for e in mine),
        "fouls": sum(e["type"] == "foul" for e in mine),
        "yellow_cards": sum(e["type"] == "card" and e.get("subtype") == "yellow" for e in mine),
        "red_cards": sum(e["type"] == "card" and e.get("subtype") in ("red", "second_yellow") for e in mine),
        "offsides": sum(e["type"] == "offside" for e in mine),
        "counter_attack_shots": sum("counter_attack" in e.get("tags", []) for e in shots),
        "set_piece_xg": round(sum(x for e, x in zip(shots, xgs) if "set_piece" in e.get("tags", [])), 3),
    }
    if possessions is not None:
        from intel.possessions import summarise
        out.update({f"poss_{k}": v for k, v in summarise(possessions, team_id).items()})
    return out


# --------------------------------------------------------------------------- phases

PHASES = ("build-up", "counter-attack", "direct", "set piece", "sustained attack", "short spell")


def phase_of(p: Possession) -> str:
    if p.start_type in ("corner", "free kick", "throw in") and (p.start_x or 0) >= 2 * L / 3:
        return "set piece"
    if p.start_type in ("interception", "tackle won", "loose ball won") and p.final_third and p.duration_s <= 15:
        return "counter-attack"
    if p.actions <= 2 and not p.shots:
        return "short spell"
    if (p.start_x or 0) < L / 2 and p.final_third and p.passes <= 3 and p.duration_s <= 14:
        return "direct"
    if p.final_third and p.duration_s >= 20:
        return "sustained attack"
    return "build-up"


def phase_breakdown(possessions: list[Possession], team_id: str) -> dict:
    out = {ph: {"count": 0, "xg": 0.0, "shots": 0, "goals": 0} for ph in PHASES}
    for p in possessions:
        if p.team_id != team_id or p.actions == 0:
            continue
        d = out[phase_of(p)]
        d["count"] += 1
        d["xg"] = round(d["xg"] + p.xg, 3)
        d["shots"] += p.shots
        d["goals"] += p.goals
    return out


# --------------------------------------------------------------------------- rhythm: windows, momentum, chaos

def windows(events: list[dict], home_id: str, size_min: float = 5.0) -> list[dict]:
    """Per-window xG, field tilt, possession, tempo and the chaos index (1.0 = league-typical)."""
    buckets: dict[int, list[dict]] = defaultdict(list)
    for e in events:
        if e.get("team_id"):
            buckets[int(match_minute(e) // size_min)].append(e)
    chaos_norm = norms().get("chaos_per_min", 1.0)
    out = []
    for b in sorted(buckets):
        es = buckets[b]
        row = {"from_min": b * size_min, "to_min": (b + 1) * size_min}
        for side, key in ((True, "home"), (False, "away")):
            mine = [e for e in es if (e["team_id"] == home_id) == side]
            row[f"{key}_xg"] = round(sum(shot_xg(e) for e in mine if e["type"] == "shot"), 3)
            row[f"{key}_passes"] = sum(e["type"] == "pass" for e in mine)
            row[f"{key}_final_third"] = sum(e["type"] == "pass" and third(e["start"]["x"]) == 2 for e in mine)
        ft = row["home_final_third"] + row["away_final_third"]
        row["home_field_tilt"] = round(row["home_final_third"] / ft, 3) if ft else 0.5
        tp = row["home_passes"] + row["away_passes"]
        row["home_possession"] = round(row["home_passes"] / tp, 3) if tp else 0.5
        span = max(1.0, max(match_minute(e) for e in es) - min(match_minute(e) for e in es))
        row["passes_per_min"] = round(tp / span, 1)
        churn = sum(e["type"] in CHAOS_TYPES for e in es) / span
        row["chaos_index"] = round(churn / chaos_norm, 2)
        out.append(row)
    return out


def rhythm_label(chaos_index: float) -> str:
    if chaos_index >= 1.3:
        return "chaotic"
    if chaos_index >= 1.1:
        return "scrappy"
    if chaos_index <= 0.8:
        return "controlled"
    return "steady"


def momentum(win: list[dict], last_n: int = 2) -> dict:
    """Who is on top over the last few windows (field tilt and xG), in words and numbers."""
    recent = win[-last_n:]
    if not recent:
        return {"side": "neither", "home_field_tilt": 0.5, "home_xg": 0.0, "away_xg": 0.0}
    tilt = sum(w["home_field_tilt"] for w in recent) / len(recent)
    hx, ax = sum(w["home_xg"] for w in recent), sum(w["away_xg"] for w in recent)
    score = (tilt - 0.5) * 2 + (hx - ax)
    side = "home" if score > 0.25 else ("away" if score < -0.25 else "neither")
    return {"side": side, "home_field_tilt": round(tilt, 3), "home_xg": round(hx, 3), "away_xg": round(ax, 3),
            "minutes": recent[0]["from_min"], "to": recent[-1]["to_min"]}


# --------------------------------------------------------------------------- pass networks

def pass_network(events: list[dict], team_id: str, min_passes: int = 3) -> dict:
    loc = defaultdict(list)
    edges = Counter()
    involve = Counter()
    for e in events:
        if e.get("team_id") != team_id or e["type"] != "pass" or e.get("outcome") != "complete":
            continue
        a, b = e["player_id"], e.get("related_player_id")
        if not b:
            continue
        loc[a].append(pt(e))
        loc[b].append(pt(e, "end"))
        edges[(a, b)] += 1
        involve[a] += 1
        involve[b] += 1
    nodes = {p: {"x": round(sum(x for x, _ in v) / len(v), 1), "y": round(sum(y for _, y in v) / len(v), 1),
                 "involvement": involve[p]} for p, v in loc.items()}
    pairs = Counter()
    for (a, b), n in edges.items():
        pairs[tuple(sorted((a, b)))] += n
    total = sum(involve.values()) / 2 or 1
    hub = involve.most_common(1)[0] if involve else (None, 0)
    top = pairs.most_common(1)[0] if pairs else ((None, None), 0)
    return {"nodes": nodes,
            "edges": [{"from": a, "to": b, "passes": n} for (a, b), n in edges.items() if n >= min_passes],
            "hub": {"player_id": hub[0], "share": round(hub[1] / (2 * total), 3)},
            "top_pair": {"players": list(top[0]), "passes": top[1]},
            "width_m": round(max((n["y"] for n in nodes.values()), default=0)
                             - min((n["y"] for n in nodes.values()), default=0), 1),
            "avg_height_m": round(sum(n["x"] for n in nodes.values()) / max(1, len(nodes)), 1)}


def flip_y_for_display(y: float) -> float:
    return W - y
