"""MatchMind generator CLI.

  python -m generator league  [--seed 2026] [--out data/league.json]
  python -m generator match   --home T01 --away T02 [--seed 1] [--out data/matches]
  python -m generator stream  --home T01 --away T02 [--seed 1] [--speed 10]
  python -m generator.validate [--seasons 3]

`stream` writes one JSON event per line to stdout, paced like the real match divided by --speed (10 plays 90
minutes in about 9). Downstream components read the same lines from a pipe now and from the event bus later.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from generator.engine import simulate
from generator.league import build_league


def _teams(league, home: str, away: str):
    by_id = {t.team_id: t for t in league.teams}
    by_code = {t.short_name: t for t in league.teams}
    try:
        return (by_id.get(home) or by_code[home]), (by_id.get(away) or by_code[away])
    except KeyError as e:
        sys.exit(f"unknown team {e}; teams: " + ", ".join(f"{t.team_id}/{t.short_name}" for t in league.teams))


def cmd_league(a) -> None:
    league = build_league(a.seed)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(league.model_dump_json(indent=1), encoding="utf-8")
    for t in league.teams:
        print(f"{t.team_id} {t.short_name:4s} {t.name:26s} {t.formation:8s} att {t.ratings.attack:.2f} "
              f"def {t.ratings.defence:.2f}")
    print(f"wrote {out}")


def cmd_match(a) -> None:
    league = build_league(a.league_seed)
    home, away = _teams(league, a.home, a.away)
    meta, events = simulate(home, away, seed=a.seed)
    out = Path(a.out) / meta.match_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "meta.json").write_text(meta.model_dump_json(indent=1), encoding="utf-8")
    with open(out / "events.jsonl", "w", encoding="utf-8") as f:
        f.writelines(json.dumps(e, separators=(",", ":")) + "\n" for e in events)
    goals = [e for e in events if e["type"] == "shot" and e.get("outcome") == "goal"]
    hs = sum(e["team_id"] == home.team_id for e in goals)
    print(f"{home.name} {hs}-{len(goals) - hs} {away.name}: {len(events)} events -> {out}")


def cmd_stream(a) -> None:
    league = build_league(a.league_seed)
    home, away = _teams(league, a.home, a.away)
    meta, events = simulate(home, away, seed=a.seed)
    try:
        print(json.dumps({"type": "match_meta", "meta": json.loads(meta.model_dump_json())}), flush=True)
        start, prev = time.monotonic(), None
        offset = 0.0     # match seconds already played in earlier periods (half-time is skipped)
        for e in events:
            if prev is not None and e["period"] != prev["period"]:
                offset += prev["t"]
            target = (offset + e["t"]) / a.speed
            wait = target - (time.monotonic() - start)
            if wait > 0:
                time.sleep(wait)
            print(json.dumps(e, separators=(",", ":")), flush=True)
            prev = e
    except (BrokenPipeError, OSError):
        # the reader went away (e.g. `| head`); Windows reports that as OSError 22
        sys.stdout = None


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m generator")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("league")
    p.add_argument("--seed", type=int, default=2026)
    p.add_argument("--out", default="data/league.json")
    for name in ("match", "stream"):
        p = sub.add_parser(name)
        p.add_argument("--home", required=True)
        p.add_argument("--away", required=True)
        p.add_argument("--seed", type=int, default=1)
        p.add_argument("--league-seed", type=int, default=2026)
        if name == "match":
            p.add_argument("--out", default="data/matches")
        else:
            p.add_argument("--speed", type=float, default=10.0)
    a = ap.parse_args()
    {"league": cmd_league, "match": cmd_match, "stream": cmd_stream}[a.cmd](a)


if __name__ == "__main__":
    main()
