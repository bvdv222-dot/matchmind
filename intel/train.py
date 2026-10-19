"""Train and check the interpret layer's models on synthetic data, writing intel/models/*.json.

usage: python -m intel.train [--league-seed 2026] [--quick]

- value_grid.json      possession value, fitted on two training leagues (never the demo league)
- norms.json           league norms (rhythm index, per-metric team-match means)
- winprob.json         win-probability parameters and their held-out evaluation (Brier, calibration)
- league_<seed>.json   for the demo league: team ratings and expectation baselines fitted on its PREVIOUS season
                       (season_offset=-1), i.e. the history an analyst would have before this season starts
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import time
from pathlib import Path

from generator.league import build_league
from generator.season import play_season
from intel import expect, ratings, value
from intel.common import match_minute
from intel.flow import CHAOS_TYPES, team_stats
from intel.winprob import WinProbParams, timeline

MODELS = Path(__file__).resolve().parent / "models"
TRAIN_LEAGUES = (9001, 9002)
SNAPSHOTS = (0, 15, 30, 45, 60, 75, 85)


def _season(seed: int, offset: int = 0):
    _, _, _, matches = play_season(build_league(seed), keep_events=True, season_offset=offset)
    return [(json.loads(m.model_dump_json()), ev) for m, ev in matches]


def _team_rows(matches) -> list[dict]:
    rows = []
    for meta, ev in matches:
        h, a = meta["home"]["team_id"], meta["away"]["team_id"]
        for team, opp, home in ((h, a, True), (a, h, False)):
            s = team_stats(ev, team)
            rows.append({"team": team, "opp": opp, "home": home, **{m: s[m] for m in expect.METRICS}})
    return rows


def _norms(matches) -> dict:
    per_min = []
    for _, ev in matches:
        es = [e for e in ev if e.get("team_id")]
        span = match_minute(es[-1]) - match_minute(es[0])
        per_min.append(sum(e["type"] in CHAOS_TYPES for e in es) / span)
    rows = _team_rows(matches)
    return {"chaos_per_min": round(st.mean(per_min), 4),
            "team_match_means": {m: round(st.mean(r[m] for r in rows), 4) for m in expect.METRICS},
            "matches": len(matches)}


def _brier(pairs) -> float:
    return st.mean(sum((p - y) ** 2 for p, y in zip(pr, ys)) for pr, ys in pairs)


def _evaluate_winprob(params: WinProbParams, evals) -> dict:
    full, constant, rel = [], [], []
    for r, matches in evals:
        hda = [0, 0, 0]
        for meta, ev in matches:
            h, a = meta["home"]["team_id"], meta["away"]["team_id"]
            gh = sum(1 for e in ev if e["type"] == "shot" and e.get("outcome") == "goal" and e["team_id"] == h)
            ga = sum(1 for e in ev if e["type"] == "shot" and e.get("outcome") == "goal" and e["team_id"] == a)
            hda[0 if gh > ga else (1 if gh == ga else 2)] += 1
        base = [x / len(matches) for x in hda]
        for meta, ev in matches:
            h, a = meta["home"]["team_id"], meta["away"]["team_id"]
            tl = timeline(ev, h, ratings.expected_goals(r, h, a), params=params)
            final = tl[-1]["score"]
            y = (final[0] > final[1], final[0] == final[1], final[0] < final[1])
            for s in SNAPSHOTS:
                p = tl[0] if s == 0 else [x for x in tl if x["minute"] <= s + 0.01][-1]
                full.append(((p["home"], p["draw"], p["away"]), y))
                rel.append((p["home"], y[0]))
                if s == 0:
                    constant.append((tuple(base), y))
    rel.sort()
    k = len(rel) // 10
    deciles = [{"predicted": round(st.mean(p for p, _ in rel[i * k:(i + 1) * k]), 3),
                "actual": round(st.mean(y for _, y in rel[i * k:(i + 1) * k]), 3)} for i in range(10)]
    prematch = [x for i, x in enumerate(full) if i % len(SNAPSHOTS) == 0]
    return {"brier_all_snapshots": round(_brier(full), 4), "brier_prematch": round(_brier(prematch), 4),
            "brier_prematch_constant_rates": round(_brier(constant), 4), "home_win_calibration": deciles,
            "snapshots": list(SNAPSHOTS), "matches": sum(len(m) for _, m in evals)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--league-seed", type=int, default=2026)
    ap.add_argument("--quick", action="store_true", help="one training league (CI / tests)")
    a = ap.parse_args()
    MODELS.mkdir(exist_ok=True)
    t0 = time.time()
    leagues = TRAIN_LEAGUES[:1] if a.quick else TRAIN_LEAGUES

    train = {s: _season(s) for s in leagues}
    all_train = [m for ms in train.values() for m in ms]
    vg = value.fit([ev for _, ev in all_train])
    vg["trained_on"] = [f"league {s}, season 0" for s in leagues]
    (MODELS / "value_grid.json").write_text(json.dumps(vg), encoding="utf-8")
    print(f"value grid: {vg['matches']} matches")

    (MODELS / "norms.json").write_text(json.dumps(_norms(all_train), indent=1), encoding="utf-8")

    evals = [(ratings.fit(_season(s, -1)), train[s]) for s in leagues]
    params = WinProbParams()
    wp = {"params": params.__dict__, "evaluation": _evaluate_winprob(params, evals)}
    (MODELS / "winprob.json").write_text(json.dumps(wp, indent=1), encoding="utf-8")
    ev_ = wp["evaluation"]
    print(f"win prob: Brier {ev_['brier_all_snapshots']} over snapshots; pre-match {ev_['brier_prematch']} "
          f"vs constant rates {ev_['brier_prematch_constant_rates']}")

    prev = _season(a.league_seed, -1)
    demo = {"league_seed": a.league_seed, "fitted_on": "previous season (season_offset=-1)",
            "ratings": ratings.fit(prev), "expect": expect.fit(_team_rows(prev))}
    (MODELS / f"league_{a.league_seed}.json").write_text(json.dumps(demo), encoding="utf-8")
    print(f"league {a.league_seed}: ratings + expectation baselines from {len(prev)} matches")
    print(f"done in {time.time() - t0:.0f} s -> {MODELS}")


if __name__ == "__main__":
    main()
