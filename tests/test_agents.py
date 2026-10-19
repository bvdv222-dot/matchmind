"""Agents: the Verifier's checks and the workflow's handoffs, revisions and fallbacks (offline: scripted models)."""
import asyncio
from types import SimpleNamespace

import pytest

from agents.personas import default_personas
from agents.roles import Note, PersonaText, StoryPlan, Translation
from agents.verify import check, numbers_preserved
from agents.workflow import Trigger, build_workflow

FACTS = ["xG: Kirkminster United 0.55, Nethdale Town 0.12.", "Possession: Kirkminster United 61%, Nethdale Town 39%.",
         "Win probability: Kirkminster United 18%, draw 27%, Nethdale Town 55%.",
         "Kirkminster United 0-0 Nethdale Town at 35'.", "Nethdale Town's xG is 0.124, about their usual."]
TEAMS = ["Kirkminster United", "Nethdale Town"]
KW = dict(roster=set(TEAMS), league_names=set(TEAMS) | {"FC Marby"}, minute_now=35, finished=False, max_words=60,
          teams=TEAMS)


@pytest.mark.parametrize("text,we,ok", [
    ("Kirkminster United lead xG 0.55 to 0.12 but Nethdale Town are at 55% to win.", None, True),
    ("We have just 39% of the ball.", "Nethdale Town", True),
    ("Nethdale Town's xG is 0.1.", None, True),
    ("Nethdale Town have 0.55 xG and 61% of the ball.", None, False),          # wrong team
    ("We have 61% possession.", "Nethdale Town", False),                         # wrong 'we'
    ("Nethdale Town have 0.31 xG.", None, False),                                # invented number
    ("Kirkminster United won it in the 80th minute.", None, False),              # future + final result
    ("Despite the scoreless draw, both sides push on.", None, False),            # result language mid-match
    ("FC Marby would love this.", None, False),                                  # name from another match
    ("Big night for Nethdale Town #NethdaleStrong", None, False),                # decoration
    ("Kirkminster United, like Arsenal, keep the ball.", None, False),           # real club
    ("Nethdale Town are looking for a touchdown.", None, False),                 # wrong sport
    ("Kirkminster United will score soon, surely.", None, False),                # forecasting
    ("Kirkminster United are likely to break the deadlock.", None, False),
])
def test_verifier(text, we, ok):
    assert check(text, FACTS, we_team=we, **KW).ok is ok


def test_translation_numbers():
    assert not numbers_preserved("Nethdale Town 55%, xG 0.12.", "Nethdale Town 55%, xG 0,12.")
    assert numbers_preserved("Nethdale Town 55%.", "Nethdale Town 50%.")


# --------------------------------------------------------------------------- workflow with scripted models

class StubIntel:
    async def call(self, tool, **args):
        if tool == "get_match_state":
            return {"clock": "35'", "minute": 35.0, "period": 1, "finished": False,
                    "home": {"name": TEAMS[0], "team_id": "T01"}, "away": {"name": TEAMS[1], "team_id": "T09"}}
        if tool == "get_fact_sheet" and args["scope"] == "match":
            keys = ["xg", "possession", "win_probability", "score", "expect"]
            return {"lines": [{"key": k, "text": t} for k, t in zip(keys, FACTS)]}
        if tool == "get_fact_sheet" and args["scope"] == "moment":
            return {"lines": [{"key": "headline", "text": "Emil Pelani misses a big chance for Kirkminster United "
                                                          "(0.38 xG)."}]}
        return {"lines": []}


class Scripted:
    """Stands in for an Agent: returns queued replies (or raises) per call."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    async def run(self, prompt, options=None):
        self.prompts.append(prompt)
        r = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(r, Exception):
            raise r
        return SimpleNamespace(value=r, text=r.model_dump_json())


def _trigger(langs=("es",)):
    moment = {"moment_id": "M-1", "kind": "big_chance_missed", "priority": 6, "minute": 34.0, "clock": "35'",
              "team_id": "T01", "player_ids": ["T01-P07"], "headline": "Emil Pelani misses a big chance."}
    names = {"roster": set(TEAMS) | {"Emil Pelani"}, "league": set(TEAMS) | {"Emil Pelani", "FC Marby"},
             "ids": {"T01": TEAMS[0], "T09": TEAMS[1]}}
    return Trigger("M", "live_note", [moment], default_personas("T01", "T09"), list(langs), names)


def _run(agents):
    wf = build_workflow(StubIntel(), agents)
    return asyncio.run(wf.run(_trigger())).get_outputs()[0]


GOOD_NOTE = Note(text="Emil Pelani misses a big chance for Kirkminster United (0.38 xG); Nethdale Town are at 55% "
                      "to win.", used_keys=["moment.headline"])
BAD_NOTE = Note(text="Emil Pelani misses a 0.61 xG chance and Kirkminster United have won it.", used_keys=[])
PLAN = StoryPlan(publish=True, moment_id="M-1", angle="A big miss keeps it level", focus_team_id="T01", importance=4)


def test_revision_loop_then_publish():
    narrator = Scripted(BAD_NOTE, GOOD_NOTE)
    job = _run({"analyst": Scripted(PLAN), "narrator": narrator,
                "personaliser": Scripted(PersonaText(text="Pelani misses a big chance; it stays level.")),
                "translator": Scripted(Translation(text="Pelani falla una gran ocasión."))})
    steps = [(t["step"], t["outcome"]) for t in job.trace]
    assert ("verifier", "reject") in steps and ("verifier", "pass") in steps
    assert "Verifier for" in narrator.prompts[1]                    # the problems were handed back
    assert job.note == GOOD_NOTE.text and job.note_source == "narrator"
    personas = len(job.trigger.personas)
    assert len(job.overlays) == 1 + personas + personas            # neutral + personas + one language each
    assert all(o["verified"] for o in job.overlays)


def test_fallback_when_the_narrator_keeps_failing():
    job = _run({"analyst": Scripted(PLAN), "narrator": Scripted(BAD_NOTE),
                "personaliser": Scripted(RuntimeError("model down")),
                "translator": Scripted(RuntimeError("model down"))})
    assert job.note_source == "fallback"
    assert "0.38 xG" in job.note                                   # built from the facts
    assert all(r["source"] == "fallback" for r in job.persona_notes.values())
    assert all(r["source"] == "fallback-english" for r in job.translations.values())
    assert job.overlays


def test_analyst_failure_uses_the_deterministic_plan():
    job = _run({"analyst": Scripted(TimeoutError("slow")), "narrator": Scripted(GOOD_NOTE),
                "personaliser": Scripted(PersonaText(text="Pelani misses a big chance.")),
                "translator": Scripted(Translation(text="Pelani falla una gran ocasión."))})
    assert job.plan["moment_id"] == "M-1"
    assert ("analyst", "fallback") in [(t["step"], t["outcome"]) for t in job.trace]
