"""Generator contract and sanity checks (fast: a handful of matches; the full calibration check is validate.py)."""
import json
from pathlib import Path

import jsonschema
import pytest

from contracts.models import Event, League, MatchMeta
from generator.engine import simulate
from generator.league import build_league

SCHEMA = Path(__file__).resolve().parents[1] / "schema"


@pytest.fixture(scope="module")
def league():
    return build_league(2026)


@pytest.fixture(scope="module")
def match(league):
    return simulate(league.teams[0], league.teams[1], seed=11)


def test_league_shape(league):
    assert len(league.teams) == 20
    assert len({t.short_name for t in league.teams}) == 20
    assert all(len(t.players) == 24 for t in league.teams)
    League.model_validate(league.model_dump())


def test_events_match_the_contract(match):
    meta, events = match
    MatchMeta.model_validate(meta.model_dump())
    schema = json.loads((SCHEMA / "event.schema.json").read_text(encoding="utf-8"))
    for e in events:
        Event.model_validate(e)
    for e in events[::50]:
        jsonschema.validate(e, schema)


def test_deterministic(league):
    _, a = simulate(league.teams[2], league.teams[3], seed=5)
    _, b = simulate(league.teams[2], league.teams[3], seed=5)
    assert a == b


def test_timeline_is_ordered(match):
    _, events = match
    assert [e["seq"] for e in events] == list(range(len(events)))
    for prev, cur in zip(events, events[1:]):
        if prev["period"] == cur["period"]:
            assert cur["t"] >= prev["t"]
    assert [e["type"] for e in events if e["type"].startswith("period")] == \
        ["period_start", "period_end", "period_start", "period_end"]


def test_rough_realism(league):
    goals = shots = passes = 0
    n = 20
    for k in range(n):
        _, ev = simulate(league.teams[k % 20], league.teams[(k + 7) % 20], seed=1000 + k)
        shots += sum(e["type"] == "shot" for e in ev)
        goals += sum(e["type"] == "shot" and e.get("outcome") == "goal" for e in ev)
        passes += sum(e["type"] == "pass" for e in ev)
    assert 1.5 < goals / n < 4.0
    assert 15 < shots / n < 32
    assert 700 < passes / n < 1100
