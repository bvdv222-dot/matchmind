"""match-intel: an MCP server exposing MatchMind's interpret layer as tools.

Agents (and coding assistants) call these tools to read live match intelligence. Every figure they return comes
from deterministic analysis of the synthetic feed; narrative text must be written only from `get_fact_sheet` lines.

  python -m mcp_server                      # stdio (Claude Code, GitHub Copilot)
  python -m mcp_server --http --port 8765   # streamable HTTP (agents on Azure)
"""
from __future__ import annotations

import argparse
import os

# MCP SDK v1 (FastMCP): Agent Framework 1.x requires mcp>=1.24,<2
from mcp.server.fastmcp import FastMCP

from intel import expect, facts
from mcp_server.registry import Registry

INSTRUCTIONS = """MatchMind match-intel: live, explainable intelligence for a fictional football league
(synthetic data).
Start or fast-forward a match (start_match / advance_match), then read it: get_match_state, get_fact_sheet,
get_moments, compare_to_expected, get_player_card, explain_event, get_win_probability, get_rhythm.
Write narrative ONLY from get_fact_sheet lines: every number in your text must appear in those lines.
Times are match minutes; nothing returned is from later than the match's current clock."""

server = FastMCP("match-intel", instructions=INSTRUCTIONS,
                 host=os.environ.get("MM_MCP_HOST", "127.0.0.1"), port=int(os.environ.get("MM_MCP_PORT", "8765")))
_registry: Registry | None = None


def registry() -> Registry:
    global _registry
    if _registry is None:
        _registry = Registry(int(os.environ.get("MM_LEAGUE_SEED", "2026")))
    return _registry


def _live(match_id: str):
    return registry().get(match_id)


@server.tool()
def list_fixtures(round: int | None = None) -> dict:
    """Fixtures of the current season (optionally one round) with their status in this server."""
    reg = registry()
    rows = [{"match_id": f.match_id, "round": f.round, "home": reg.teams[f.home].name, "home_id": f.home,
             "away": reg.teams[f.away].name, "away_id": f.away, "kickoff_utc": f.kickoff_utc,
             "status": reg.status(f)} for f in reg.fixtures if round is None or f.round == round]
    return {"league": reg.league.name, "season": reg.league.season, "fixtures": rows[:60]}


@server.tool()
def start_match(match_id: str | None = None, home: str | None = None, away: str | None = None,
                speed: float = 10.0, with_frames: bool = False) -> dict:
    """Start playing a fixture live in the background (speed 10 = 90 minutes in about 9). Give a match_id, or home
    and away team ids / short codes. with_frames adds 2 Hz player positions (speed and distance tags)."""
    reg = registry()
    fx = reg.find_fixture(match_id, home, away)
    run = reg.start(fx, speed, with_frames)
    return {"started": fx.match_id, "speed": speed, "state": run.live.state()}


@server.tool()
def advance_match(match_id: str | None = None, to_minute: float = 45.0, home: str | None = None,
                  away: str | None = None) -> dict:
    """Fast-forward a fixture to a match minute (loads it first if needed). Use 95 for full time."""
    reg = registry()
    fx = reg.find_fixture(match_id, home, away)
    run = reg.advance(fx, to_minute)
    return run.live.state()


@server.tool()
def get_match_state(match_id: str) -> dict:
    """Score, clock, xG, red cards, who has the ball and the live win probability."""
    run = _live(match_id)
    with run.lock:
        return run.live.state()


@server.tool()
def get_fact_sheet(match_id: str, scope: str = "match", subject_id: str | None = None) -> dict:
    """Deterministic fact lines to write from. scope: match | team (subject_id = team id) | player (player id) |
    moment (moment id). Every number a narrative uses must come from these lines."""
    run = _live(match_id)
    with run.lock:
        lm = run.live
        if scope == "match":
            sheet = facts.match_sheet(lm)
        elif scope == "team":
            sheet = facts.team_sheet(lm, subject_id or lm.home)
        elif scope == "player":
            sheet = facts.player_sheet(lm, _player_id(lm, subject_id))
        elif scope == "moment":
            sheet = facts.moment_sheet(lm, subject_id)
        else:
            raise ValueError("scope must be match, team, player or moment")
    sheet.pop("data", None)
    return sheet


@server.tool()
def get_moments(match_id: str, since_minute: float = 0.0, min_priority: int = 0) -> dict:
    """Moments detected so far (goals, big chances, saves, cards, tactical shifts, momentum swings, speed tags...),
    each with a deterministic headline. Priority 9 = goal, 2 = minor."""
    run = _live(match_id)
    with run.lock:
        lm = run.live
        out = [{**{k: v for k, v in m.items() if k not in ("win_prob_before", "win_prob_after")},
                "headline": facts.headline(lm, m)}
               for m in lm.moments if m["minute"] >= since_minute and m["priority"] >= min_priority]
    return {"match_id": match_id, "count": len(out), "moments": out}


@server.tool()
def compare_to_expected(match_id: str, team_id: str, metric: str | None = None) -> dict:
    """How a team's numbers compare with what it usually produces against this kind of opponent (ridge baseline from
    last season), scaled to the share of the match played. Metrics: """ + ", ".join(expect.METRICS)
    run = _live(match_id)
    with run.lock:
        tv = run.live.team_view(team_id)
    vs = tv["vs_expected"]
    return {"team": tv["name"], "comparisons": [vs[metric]] if metric else list(vs.values())}


def _player_id(lm, key: str | None) -> str:
    if key in lm.players:
        return key
    key_l = (key or "").lower()
    hits = [pid for pid, p in lm.players.items() if key_l and key_l in p.name.lower()]
    if len(hits) != 1:
        raise KeyError(f"player '{key}' not found uniquely; use a player_id")
    return hits[0]


@server.tool()
def get_player_card(match_id: str, player: str) -> dict:
    """A player's profile and match so far (passing, shooting, take-ons, defending, possession value, physical).
    player = player id or part of the name."""
    run = _live(match_id)
    with run.lock:
        return run.live.player_view(_player_id(run.live, player))


@server.tool()
def explain_event(match_id: str, event_id: str) -> dict:
    """Why an event mattered: possession value before / after / added, and xG for shots."""
    run = _live(match_id)
    with run.lock:
        return run.live.explain_event(event_id)


@server.tool()
def get_win_probability(match_id: str) -> dict:
    """Current win / draw / loss probability and its history (sampled every few minutes and at every goal)."""
    run = _live(match_id)
    with run.lock:
        lm = run.live
        return {"now": lm.win_probability(), "clock": lm.clock(), "history": lm.winprob_history,
                "prematch_expected_goals": [round(x, 2) for x in lm.prematch]}


@server.tool()
def get_rhythm(match_id: str) -> dict:
    """Five-minute windows: xG, field tilt, possession, passing tempo and the chaos index (1.0 = typical)."""
    run = _live(match_id)
    with run.lock:
        return {"windows": run.live.windows()}


@server.tool()
def get_team_profile(team_id: str) -> dict:
    """A club's identity and last-season standing on chance creation and chance prevention."""
    reg = registry()
    t = reg.teams[team_id]
    from intel.live import league_models
    model = league_models(reg.league.seed)["expect"]
    return {"team_id": team_id, "name": t.name, "short_name": t.short_name, "city": t.city, "stadium": t.stadium,
            "formation": t.formation, "colors": t.colors.model_dump(),
            "attack": expect.standing(model, "xg", team_id, "offence"),
            "defence": expect.standing(model, "xg", team_id, "defence"),
            "squad": [{"player_id": p.player_id, "name": p.name, "position": p.position, "shirt": p.shirt}
                      for p in t.players]}


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m mcp_server")
    ap.add_argument("--http", action="store_true", help="serve streamable HTTP instead of stdio")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    if a.http:
        server.settings.host, server.settings.port = a.host, a.port
        server.run("streamable-http")
    else:
        server.run("stdio")


if __name__ == "__main__":
    main()
