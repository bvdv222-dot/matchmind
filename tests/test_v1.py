"""Season mode, position frames, fatigue and the live feed."""
from collections import Counter

import pytest

from contracts.models import PositionFrame, StreamMessage
from generator.engine import MatchSim, simulate
from generator.feed import messages
from generator.frames import build_frames
from generator.league import build_league
from generator.season import fixtures, play_season


@pytest.fixture(scope="module")
def league():
    return build_league(2026)


def test_fixtures_are_a_balanced_double_round_robin(league):
    fx = fixtures(league)
    assert len(fx) == 380
    assert max(f.round for f in fx) == 38
    assert set(Counter(f.round for f in fx).values()) == {10}
    assert len({(f.home, f.away) for f in fx}) == 380
    for t in league.teams:
        venues = "".join("H" if f.home == t.team_id else "A" for f in sorted(fx, key=lambda f: f.round)
                         if t.team_id in (f.home, f.away))
        assert venues.count("H") == 19
        # real fixture lists have the odd three-match run (here at the half-season join), never four
        assert "HHHH" not in venues and "AAAA" not in venues
        assert sum(venues[i:i + 3] in ("HHH", "AAA") for i in range(len(venues) - 2)) <= 2


def test_table_after_three_rounds(league):
    _, results, table, _ = play_season(league, rounds=3)
    assert len(results) == 30
    assert all(r.played == 3 for r in table)
    assert sum(r.points for r in table) == sum(3 if x["home_goals"] != x["away_goals"] else 2 for x in results)
    assert [r.points for r in table] == sorted((r.points for r in table), reverse=True)


def test_fatigue_grows_with_minutes(league):
    sim = MatchSim(league.teams[0], league.teams[1], seed=1)
    op = sim.sides[0].on[5]
    sim.period, sim.t = 1, 60.0
    early = sim.fatigue(op)
    sim.period, sim.t = 2, 44 * 60.0
    late = sim.fatigue(op)
    assert early < 0.01 < late <= 0.30


@pytest.fixture(scope="module")
def match_with_frames(league):
    home, away = league.teams[3], league.teams[8]
    meta, events = simulate(home, away, seed=21)
    return meta, events, build_frames(meta, events, {home.team_id: home, away.team_id: away})


def test_frames_shape_and_contract(match_with_frames):
    meta, events, frames = match_with_frames
    first_half = next(e["t"] for e in events if e["type"] == "period_end")
    assert abs(sum(f["period"] == 1 for f in frames) / 2 - first_half) < 1.0      # 2 Hz
    for f in frames[::500]:
        PositionFrame.model_validate(f)
        assert 18 <= len(f["players"]) <= 22
        assert len({p["player_id"] for p in f["players"]}) == len(f["players"])
        for p in f["players"]:
            assert 0 <= p["x"] <= 105 and 0 <= p["y"] <= 68


def test_frames_respect_top_speed(match_with_frames, league):
    _, _, frames = match_with_frames
    top = {p.player_id: p.attributes.top_speed_kmh for t in league.teams for p in t.players}
    fastest = Counter()
    for f in frames:
        for p in f["players"]:
            fastest[p["player_id"]] = max(fastest[p["player_id"]], p["speed_kmh"])
    assert all(v <= top[pid] + 0.5 for pid, v in fastest.items())


def test_feed_is_ordered_and_typed(match_with_frames):
    meta, events, frames = match_with_frames
    msgs = list(messages(meta, events, frames))
    assert msgs[0]["kind"] == "meta"
    assert Counter(m["kind"] for m in msgs) == {"meta": 1, "event": len(events), "frame": len(frames)}
    keys = [(m["data"]["period"], m["data"]["t"]) for m in msgs[1:]]
    assert keys == sorted(keys)
    StreamMessage.model_validate(msgs[1])
