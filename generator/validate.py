"""Simulate full seasons and compare the synthetic matches with the real calibration targets.

usage: python -m generator.validate [--seasons 3] [--seed 2026] [--frames 4] [--json out.json]
Seasons are played on the real fixture list (generator/season.py). --frames N also builds position frames for N
matches and checks distance, sprints and team shape against the SkillCorner physical profiles.
Exits non-zero if any metric falls outside its band, so CI can gate generator changes.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics as st
import sys
import time
from collections import Counter, defaultdict

import numpy as np

from generator import params as P
from generator.engine import L, W
from generator.frames import build_frames
from generator.league import build_league
from generator.season import play_season

LAST_TABLES: list = []        # final tables from the last run(), for the standings metric


def run(seasons: int, seed: int):
    out = []
    LAST_TABLES.clear()
    for s in range(seasons):
        league = build_league(seed + s)
        _, _, table, matches = play_season(league, keep_events=True)
        LAST_TABLES.append(table)
        out.extend((league.seed, meta, ev) for meta, ev in matches)
    return out


def measure_frames(matches, n: int) -> dict:
    """Physical realism of the position frames, relative to each player's own profile."""
    dist_ratio, sprint_ratio, width, depth = [], [], [], []
    for league_seed, meta, ev in matches[:n]:
        league = build_league(league_seed)
        teams = {t.team_id: t for t in league.teams if t.team_id in (meta.home.team_id, meta.away.team_id)}
        players = {p.player_id: p for t in teams.values() for p in t.players}
        frames = build_frames(meta, ev, teams)
        speeds: dict[str, list[float]] = {}
        last: dict[str, float] = {}
        for i, f in enumerate(frames):
            for p in f["players"]:
                speeds.setdefault(p["player_id"], []).append(p["speed_kmh"])
                last[p["player_id"]] = p["distance_m"]
            if i % 10 == 0:
                for tid in teams:
                    pts = [(p["x"], p["y"]) for p in f["players"]
                           if p["team_id"] == tid and players[p["player_id"]].position != "GK"]
                    if len(pts) >= 9:
                        xs, ys = zip(*pts)
                        width.append(max(ys) - min(ys))
                        depth.append(max(xs) - min(xs))
        for pid, sp in speeds.items():
            pl = players[pid]
            minutes = len(sp) / 120
            if minutes < 80 or pl.position == "GK":
                continue
            dist_ratio.append(last[pid] / minutes / pl.attributes.distance_m_per_min)
            a = np.array(sp) > 25.2
            sprints = int((np.diff(np.concatenate([[0], a.astype(int)])) == 1).sum())
            sprint_ratio.append(sprints / minutes * 90 / (pl.attributes.sprints_per90 * P.PHYSICAL_SCALE))
    return {"frames_distance_vs_profile": st.mean(dist_ratio), "frames_sprints_vs_profile": st.mean(sprint_ratio),
            "frames_team_width_m": st.median(width), "frames_team_depth_m": st.median(depth)}


def wyscout_possessions(ev: list[dict]) -> int:
    """Possessions counted the way calibration/profile_wyscout.py counted them: the ball changes hands only when
    the other team takes control (accurate pass, shot, carry or a restart), not on every touch it wins."""
    count, team, period = 0, None, None
    for e in ev:
        t = e["type"]
        if t not in ("pass", "shot", "carry", "take_on"):
            continue
        control = t in ("shot", "carry") or (t == "pass" and (e.get("outcome") == "complete"
                                                               or "set_piece" in e.get("tags", [])))
        if team is None or e["period"] != period:
            count, team, period = count + 1, e["team_id"], e["period"]
        elif e["team_id"] != team and control:
            count, team = count + 1, e["team_id"]
    return count


def measure(matches) -> dict:
    n = len(matches)
    c = Counter()
    hg, ag, res = [], [], Counter()
    shot_rows, pass_by = [], defaultdict(lambda: [0, 0])
    corner_shot = [0, 0]
    half_end = {1: [], 2: []}
    goals_half = Counter()
    team_shots = defaultdict(lambda: [0, 0])      # (league, team) -> shots, matches
    pens = [0, 0]
    for league_seed, meta, ev in matches:
        h, a = meta.home.team_id, meta.away.team_id
        goals = Counter()
        for i, e in enumerate(ev):
            t = e["type"]
            c[t] += 1
            sub = e.get("subtype")
            if t == "pass":
                c["pass:" + sub] += 1
                if e.get("outcome") != "offside":
                    pass_by[sub][0] += 1
                    pass_by[sub][1] += e.get("outcome") == "complete"
                    if sub not in ("throw_in", "goal_kick", "corner", "free_kick", "kick_off"):
                        pass_by["open_play"][0] += 1
                        pass_by["open_play"][1] += e.get("outcome") == "complete"
                if "free_kick_cross" in e.get("tags", []):
                    c["fk_cross"] += 1
                if sub == "corner":
                    corner_shot[0] += 1
                    for f in ev[i + 1:i + 12]:
                        if f["t"] - e["t"] > 15 or f["period"] != e["period"]:
                            break
                        if f["type"] == "shot" and f["team_id"] == e["team_id"]:
                            corner_shot[1] += 1
                            break
            elif t == "shot":
                team_shots[(league_seed, e["team_id"])][0] += 1
                if e.get("outcome") == "goal":
                    goals[e["team_id"]] += 1
                    goals_half[e["period"]] += 1
                if sub == "penalty":
                    pens[0] += 1
                    pens[1] += e.get("outcome") == "goal"
                elif sub == "free_kick":
                    c["fk_shot"] += 1
                else:
                    x, y = e["start"]["x"], e["start"]["y"]
                    shot_rows.append((math.hypot(L - x, y - W / 2), e.get("outcome"), e.get("body_part") == "head"))
            elif t == "card":
                c["card:" + sub] += 1
            elif t == "period_end":
                half_end[e["period"]].append(e["t"] / 60)
        for tid in (h, a):
            team_shots[(league_seed, tid)][1] += 1
        hg.append(goals[h])
        ag.append(goals[a])
        res["H" if goals[h] > goals[a] else ("A" if goals[a] > goals[h] else "D")] += 1
    nshots = len(shot_rows)
    bands = [(0, 6), (6, 11), (11, 16.5), (16.5, 22), (22, 30), (30, 99)]
    spread = [math.log(s / m) for s, m in team_shots.values() if s]
    m = {
        "goals_per_match": (sum(hg) + sum(ag)) / n,
        "home_goals": sum(hg) / n, "away_goals": sum(ag) / n,
        "home_win": res["H"] / n, "draw": res["D"] / n, "away_win": res["A"] / n,
        "shots_per_match": c["shot"] / n,
        "open_play_conversion": sum(r[1] == "goal" for r in shot_rows) / nshots,
        "on_target_share": sum(r[1] in ("goal", "saved") for r in shot_rows) / nshots,
        "header_share": sum(r[2] for r in shot_rows) / nshots,
        "second_half_goal_share": goals_half[2] / max(1, sum(goals_half.values())),
        "passes_per_match": c["pass"] / n,
        "pass_completion_open_play": pass_by["open_play"][1] / pass_by["open_play"][0],
        "possessions_per_match": sum(wyscout_possessions(ev) for _, _, ev in matches) / n,
        "corners_per_match": c["pass:corner"] / n, "throw_ins_per_match": c["pass:throw_in"] / n,
        "goal_kicks_per_match": c["pass:goal_kick"] / n + 0.0,
        "free_kicks_per_match": (c["pass:free_kick"] + c["fk_cross"] + c["fk_shot"]) / n,
        "fouls_per_match": c["foul"] / n, "yellows_per_match": c["card:yellow"] / n,
        "reds_per_match": (c["card:red"] + c["card:second_yellow"]) / n,
        "offsides_per_match": c["offside"] / n, "subs_per_team": c["substitution"] / (2 * n),
        "penalties_per_match": pens[0] / n, "penalty_conversion": pens[1] / max(1, pens[0]),
        "corner_shot_15s": corner_shot[1] / max(1, corner_shot[0]),
        "team_shots_log_sd": st.pstdev(spread),
        "half1_minutes": st.median(half_end[1]), "half2_minutes": st.median(half_end[2]),
    }
    for sub in ("ground", "high", "head", "cross", "launch", "through"):
        a_, c_ = pass_by[sub]
        m[f"completion_{sub}"] = c_ / a_ if a_ else float("nan")
    for lo, hi in bands:
        m[f"shot_share_{lo}-{hi}"] = sum(lo <= r[0] < hi for r in shot_rows) / nshots
    return m


def targets() -> dict:
    """(target, tolerance) per metric, from the calibration file where it has the number."""
    cal = P.calibration()
    r, s, pm, sp = cal["results"], cal["shots"], cal["per_match_subevent"], cal["set_pieces"]
    cards = cal["discipline_subs"]["cards_per_match"]
    t = {
        "goals_per_match": (r["home_goals_mean"] + r["away_goals_mean"], 0.15),
        "home_goals": (r["home_goals_mean"], 0.15), "away_goals": (r["away_goals_mean"], 0.15),
        "home_win": (r["home_win"], 0.05), "draw": (r["draw"], 0.05), "away_win": (r["away_win"], 0.05),
        "shots_per_match": (s["per_match"], 2.0),
        "open_play_conversion": (s["outcome"]["goal"], 0.015),
        "on_target_share": (s["outcome"]["on_target"], 0.04),
        "header_share": (s["body_part"]["head"], 0.04),
        "second_half_goal_share": (0.58, 0.04),
        "passes_per_match": (cal["per_match"]["Pass"]["mean"], 60),
        "pass_completion_open_play": (0.825, 0.03),
        "possessions_per_match": (cal["possessions"]["per_match"], 15),
        "corners_per_match": (pm["Corner"]["mean"], 1.5), "throw_ins_per_match": (pm["Throw in"]["mean"], 7),
        "goal_kicks_per_match": (pm["Goal kick"]["mean"], 3),
        "free_kicks_per_match": (pm["Free Kick"]["mean"] + pm["Free kick cross"]["mean"]
                                 + pm["Free kick shot"]["mean"], 4),
        "fouls_per_match": (cal["per_match"]["Foul"]["mean"], 3),
        "yellows_per_match": (cal["discipline_subs"]["cards_per_match"]["yellow"], 0.6),
        "reds_per_match": (cards["red"] + cards["second_yellow"], 0.08),
        "offsides_per_match": (cal["per_match"]["Offside"]["mean"], 1.5),
        "subs_per_team": (cal["discipline_subs"]["subs_per_team_match"], 0.2),
        "penalties_per_match": (s["penalty"]["per_match"], 0.08),
        "penalty_conversion": (s["penalty"]["conversion"], 0.10),   # ~160 penalties per 2 seasons: se ~0.035
        "corner_shot_15s": (sp["Corner"]["shot_within_15s"], 0.06),
        "team_shots_log_sd": (0.22, 0.06),
        "half1_minutes": (cal["timing"]["half_length_min"]["1H"]["median"], 1.0),
        "half2_minutes": (cal["timing"]["half_length_min"]["2H"]["median"], 1.0),
        "season_points_sd": (cal["standings"]["points_sd"], 4.5),
        # one real season, and a record one (100 points): real champions span the 80s-100, so the band is wide
        "season_points_max": (cal["standings"]["points_max"], 18),
        "season_points_min": (cal["standings"]["points_min"], 12),
    }
    for k, v in cal["passes"]["by_type"].items():
        key = {"Simple pass": "ground", "High pass": "high", "Head pass": "head", "Cross": "cross", "Launch": "launch",
               "Smart pass": "through"}.get(k)
        if key:
            t[f"completion_{key}"] = (v["completion"], 0.05)
    for band, v in s["by_distance_m"].items():
        lo, hi = band.split("-")
        hi = "99" if hi == "99" else hi
        t[f"shot_share_{lo}-{hi}"] = (v["share"], 0.04)
    return t


def report(m: dict, t: dict) -> int:
    fails = 0
    print(f"{'metric':30s} {'synthetic':>10s} {'target':>10s} {'band':>8s}  ")
    for k, (target, tol) in t.items():
        v = m.get(k, float("nan"))
        ok = abs(v - target) <= tol
        fails += not ok
        print(f"{k:30s} {v:10.3f} {target:10.3f} {tol:8.3f}  {'ok' if ok else 'FAIL'}")
    print(f"\n{len(t) - fails}/{len(t)} metrics within band")
    return fails


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", type=int, default=3)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--frames", type=int, default=0, help="also check position frames for this many matches")
    ap.add_argument("--json")
    args = ap.parse_args()
    t0 = time.time()
    matches = run(args.seasons, args.seed)
    m = measure(matches)
    pts = [[r.points for r in table] for table in LAST_TABLES]
    m["season_points_sd"] = st.mean(st.pstdev(p) for p in pts)
    m["season_points_max"] = st.mean(max(p) for p in pts)
    m["season_points_min"] = st.mean(min(p) for p in pts)
    t = targets()
    if args.frames:
        m.update(measure_frames(matches, args.frames))
        t.update({"frames_distance_vs_profile": (1.0, 0.06), "frames_sprints_vs_profile": (1.0, 0.35),
                  "frames_team_width_m": (P.TEAM_WIDTH_M, 4.0), "frames_team_depth_m": (P.TEAM_DEPTH_M, 5.0)})
    print(f"{len(matches)} matches in {time.time() - t0:.1f} s\n")
    fails = report(m, t)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"metrics": m, "targets": t}, f, indent=1)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
