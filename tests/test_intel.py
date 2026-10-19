"""Interpret layer: models, live ingestion, fact sheets, and the match-intel MCP server."""
import json
import statistics as st

import anyio
import pytest

from generator.engine import simulate
from generator.feed import messages
from generator.frames import build_frames
from generator.league import build_league
from intel import facts, value
from intel.common import is_goal, match_minute
from intel.live import LiveMatch, league_models
from intel.winprob import probabilities
from intel.xg import shot_xg, xg_at


@pytest.fixture(scope="module")
def league():
    return build_league(2026)


@pytest.fixture(scope="module")
def played(league):
    """A full match (with frames) through LiveMatch, plus a copy stopped at half-time."""
    home, away = league.teams[4], league.teams[13]
    meta, events = simulate(home, away, seed=77)
    frames = build_frames(meta, events, {home.team_id: home, away.team_id: away})
    full, half = None, None
    for m in messages(meta, events, frames):
        if m["kind"] == "meta":
            full, half = LiveMatch(m["data"], league), LiveMatch(m["data"], league)
            continue
        full.ingest(m)
        if match_minute(m["data"]) < 46 and m["data"]["period"] == 1:
            half.ingest(m)
    return meta, events, full, half


def test_xg_model():
    assert xg_at(99, 34) > xg_at(88, 34) > xg_at(80, 34) > xg_at(80, 5)
    assert xg_at(99, 34, header=True) < xg_at(99, 34)
    assert shot_xg({"type": "shot", "subtype": "penalty", "start": {"x": 94, "y": 34}}) == pytest.approx(0.7, abs=0.05)


def test_value_grid_rises_towards_goal():
    assert value.value_at(100, 34) > value.value_at(80, 34) > value.value_at(52, 34) > value.value_at(10, 34)
    assert value.value_at(100, 34) > value.value_at(100, 3)        # central beats the corner flag
    goal = {"event_id": "x", "type": "shot", "outcome": "goal", "start": {"x": 98, "y": 34}}
    assert value.action_value(goal)["added"] > 0.8


def test_win_probability():
    for minute in (0, 45, 80):
        assert sum(probabilities(minute, (1, 0), (1.4, 1.2))) == pytest.approx(1.0)
    ph, _, pa = probabilities(0, (0, 0), (1.3, 1.3))
    assert ph == pytest.approx(pa, abs=1e-9)
    assert probabilities(88, (2, 0), (1.3, 1.3))[0] > 0.97
    assert probabilities(30, (0, 1), (2.5, 0.8))[0] > probabilities(30, (0, 1), (1.0, 1.6))[0]


def test_fitted_ratings_track_the_hidden_truth(league):
    """The analyst's ratings come from last season's results only; they should still rank clubs like the truth."""
    fitted = league_models(2026)["ratings"]["attack"]
    truth = {t.team_id: t.ratings.attack * t.ratings.quality for t in league.teams}
    ids = sorted(truth)
    assert st.correlation([fitted[i] for i in ids], [truth[i] for i in ids]) > 0.6


def test_live_match_counts_and_moments(played):
    meta, events, full, _ = played
    goals = [e for e in events if is_goal(e)]
    st_ = full.state()
    assert st_["home"]["goals"] + st_["away"]["goals"] == len(goals)
    assert st_["finished"]
    goal_moments = [m for m in full.moments if m["kind"] in ("goal", "brace", "hat_trick")]
    assert len(goal_moments) == len(goals)
    assert all(m["win_prob_after"] != m["win_prob_before"] for m in goal_moments)
    assert full.physical and max(p["distance_m"] for p in full.physical.values()) > 8000
    json.dumps(st_)


def test_nothing_from_the_future(played):
    _, _, _, half = played
    now = half.minute()
    assert now < 46
    assert all(m["minute"] <= now + 1e-6 for m in half.moments)
    sheet = facts.match_sheet(half)
    assert sheet["as_of"]["minute"] == pytest.approx(now, abs=0.01)


def test_fact_sheets_are_plain_and_numeric(played):
    _, _, full, _ = played
    for sheet in (facts.match_sheet(full), facts.team_sheet(full, full.home),
                  facts.player_sheet(full, full.top_players(n=1)[0]["player_id"])):
        assert sheet["lines"] and all(line["text"].strip() for line in sheet["lines"])
        assert facts.numbers(sheet)
        assert "rank 1" not in json.dumps(sheet["lines"])      # standings are in words, not raw ranks
    moment = next(m for m in full.moments if m["priority"] >= 5)
    assert facts.moment_sheet(full, moment["moment_id"])["lines"][0]["text"] == facts.headline(full, moment)


def _call(name, **args):
    from mcp_server.server import server

    async def go():
        r = await server.call_tool(name, args)
        sc = getattr(r, "structuredContent", None)
        if sc is None:
            sc = json.loads(r.content[0].text)
        return sc.get("result", sc)
    return anyio.run(go)


def test_mcp_tools_end_to_end():
    from mcp_server.server import server
    names = {t.name for t in anyio.run(server.list_tools)}
    assert {"get_fact_sheet", "get_moments", "compare_to_expected", "explain_event"} <= names
    fx = _call("list_fixtures", round=2)["fixtures"][0]
    state = _call("advance_match", match_id=fx["match_id"], to_minute=30)
    assert 29 <= state["minute"] < 31
    sheet = _call("get_fact_sheet", match_id=fx["match_id"], scope="team", subject_id=fx["away_id"])
    assert sheet["scope"] == "team" and sheet["lines"]
    cmp_ = _call("compare_to_expected", match_id=fx["match_id"], team_id=fx["home_id"], metric="xg")
    assert cmp_["comparisons"][0]["metric"] == "xg"
    later = _call("advance_match", match_id=fx["match_id"], to_minute=95)
    assert later["finished"]
