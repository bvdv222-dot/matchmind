"""MatchMind generator CLI.

  python -m generator league  [--seed 2026] [--out data/league.json]
  python -m generator season  [--league-seed 2026] [--rounds 38] [--out data/season]
  python -m generator match   --home KIR --away RAV [--seed 1] [--frames] [--out data/matches]
  python -m generator stream  --home KIR --away RAV [--seed 1] [--speed 10] [--frames]
  python -m generator.validate [--seasons 3] [--frames 8]

`stream` writes the live feed to stdout, one StreamMessage per line ({"kind": "meta" | "event" | "frame",
"data": ...}), paced like the real match divided by --speed (10 plays 90 minutes in about 9). --frames adds the
2 Hz position frames. Downstream components read the same lines from a pipe now and from the event bus later.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from generator.engine import simulate
from generator.feed import messages, paced
from generator.frames import build_frames
from generator.league import build_league
from generator.season import play_season


def _teams(league, home: str, away: str):
    by_id = {t.team_id: t for t in league.teams}
    by_code = {t.short_name: t for t in league.teams}
    try:
        return (by_id.get(home) or by_code[home]), (by_id.get(away) or by_code[away])
    except KeyError as e:
        sys.exit(f"unknown team {e}; teams: " + ", ".join(f"{t.team_id}/{t.short_name}" for t in league.teams))


def _dump_lines(path: Path, rows) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(r, separators=(",", ":")) + "\n" for r in rows)


def cmd_league(a) -> None:
    league = build_league(a.seed)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(league.model_dump_json(indent=1), encoding="utf-8")
    for t in league.teams:
        print(f"{t.team_id} {t.short_name:4s} {t.name:26s} {t.formation:8s} att {t.ratings.attack:.2f} "
              f"def {t.ratings.defence:.2f}")
    print(f"wrote {out}")


def cmd_season(a) -> None:
    league = build_league(a.league_seed)
    names = {t.team_id: t for t in league.teams}
    fixtures, results, table, _ = play_season(league, rounds=a.rounds)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "league.json").write_text(league.model_dump_json(indent=1), encoding="utf-8")
    (out / "fixtures.json").write_text(json.dumps([f.__dict__ for f in fixtures], indent=1), encoding="utf-8")
    (out / "results.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    rows = [{"pos": i, "team_id": r.team_id, "team": names[r.team_id].name, "played": r.played, "won": r.won,
             "drawn": r.drawn, "lost": r.lost, "gf": r.gf, "ga": r.ga, "gd": r.gd, "points": r.points,
             "form": "".join(r.form)} for i, r in enumerate(table, start=1)]
    (out / "table.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    for r in rows:
        print(f"{r['pos']:2d} {r['team']:26s} {r['played']:2d} {r['won']:2d} {r['drawn']:2d} {r['lost']:2d} "
              f"{r['gf']:3d}-{r['ga']:<3d} {r['points']:3d}  {r['form']}")
    print(f"wrote {out}/ (league, fixtures, results, table)")


def _match(a):
    league = build_league(a.league_seed)
    home, away = _teams(league, a.home, a.away)
    meta, events = simulate(home, away, seed=a.seed)
    frames = build_frames(meta, events, {home.team_id: home, away.team_id: away}) if a.frames else None
    return home, away, meta, events, frames


def cmd_match(a) -> None:
    home, away, meta, events, frames = _match(a)
    out = Path(a.out) / meta.match_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "meta.json").write_text(meta.model_dump_json(indent=1), encoding="utf-8")
    _dump_lines(out / "events.jsonl", events)
    if frames:
        _dump_lines(out / "frames.jsonl", frames)
    goals = [e for e in events if e["type"] == "shot" and e.get("outcome") == "goal"]
    hs = sum(e["team_id"] == home.team_id for e in goals)
    print(f"{home.name} {hs}-{len(goals) - hs} {away.name}: {len(events)} events"
          f"{f', {len(frames)} frames' if frames else ''} -> {out}")


def cmd_stream(a) -> None:
    _, _, meta, events, frames = _match(a)
    try:
        for m in paced(messages(meta, events, frames), events, a.speed):
            print(json.dumps(m, separators=(",", ":")), flush=True)
    except (BrokenPipeError, OSError):
        # the reader went away (e.g. `| head`); Windows reports that as OSError 22
        sys.stdout = None


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m generator")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("league")
    p.add_argument("--seed", type=int, default=2026)
    p.add_argument("--out", default="data/league.json")
    p = sub.add_parser("season")
    p.add_argument("--league-seed", type=int, default=2026)
    p.add_argument("--rounds", type=int, default=None)
    p.add_argument("--out", default="data/season")
    for name in ("match", "stream"):
        p = sub.add_parser(name)
        p.add_argument("--home", required=True)
        p.add_argument("--away", required=True)
        p.add_argument("--seed", type=int, default=1)
        p.add_argument("--league-seed", type=int, default=2026)
        p.add_argument("--frames", action="store_true", help="include 2 Hz position frames")
        if name == "match":
            p.add_argument("--out", default="data/matches")
        else:
            p.add_argument("--speed", type=float, default=10.0)
    a = ap.parse_args()
    {"league": cmd_league, "season": cmd_season, "match": cmd_match, "stream": cmd_stream}[a.cmd](a)


if __name__ == "__main__":
    main()
