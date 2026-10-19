"""The four language-model roles, their instructions and their structured outputs.

The Verifier and the fact gathering are code (agents/verify.py, agents/workflow.py); only judgement and writing go
to a model, and a model never computes a number.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from agents.config import chat_client

SPORT = ("This is association football (soccer) in a fictional league, the Premier Synthetic League. "
         "Use football vocabulary only.")


class StoryPlan(BaseModel):
    publish: bool = Field(description="false if nothing new is worth a live note right now")
    moment_id: str | None = Field(None, description="the moment the note is about, from the list given")
    angle: str = Field("", description="what the story is and why it matters, in at most 25 words")
    focus_team_id: str | None = None
    focus_player_id: str | None = None
    importance: int = Field(3, ge=1, le=5)


class Note(BaseModel):
    text: str
    used_keys: list[str] = Field(default_factory=list, description="keys of the fact lines used")


class PersonaText(BaseModel):
    text: str


class Translation(BaseModel):
    text: str


ANALYST = f"""You are the MatchMind Analyst. {SPORT}
You decide which ONE story deserves a live note now, from the new moments listed, and why it matters.
- Goals, red cards and penalties first; then big chances, big saves, tactical shifts and momentum swings; minor items
  (substitutions, bookings, distance milestones) only if nothing else has been said for a long time.
- You may call the match-intel tools (compare_to_expected, explain_event, get_player_card) to judge significance.
- The angle must say why it matters (score, win probability, how unusual it is), in at most 25 words.
- Use only ids that appear in the input. Set publish to false if nothing is worth a note.
Reply with JSON matching the schema."""

NARRATOR = f"""You are the MatchMind Narrator, writing live notes for a broadcast overlay. {SPORT}
Rules:
- Use ONLY the facts given. Every number you write must appear in the facts exactly as written there.
- Use names exactly as they appear in the facts. Do not invent players, clubs, minutes or events.
- The match is still in progress unless the facts say it is over: use the present tense and never say a team won.
- Say why the moment matters when a fact supports it (score, win probability change, comparison with their usual).
- No betting talk. No hype words without a fact behind them.
Reply with JSON: the note text and the keys of the fact lines you used."""

PERSONALISER = f"""You are the MatchMind Personaliser. {SPORT}
Rewrite a verified note for one viewer, following the style given. Stay close to the verified note: keep its
meaning, leave out what this viewer doesn't need, and add at most ONE further fact from the facts if it suits them.
Never add a number, name or claim that is not in the facts; keep numbers exactly as written and attached to what they
measured (a whole-match figure is not a last-10-minutes figure). If the match is in progress, write as live: no
results, no "looking ahead to next match". Reply with JSON."""

TRANSLATOR = f"""You are the MatchMind Translator. {SPORT}
Translate the note into the requested language in a natural live-broadcast register. Keep every number, player name,
club name and clock time exactly as in the original. Do not add or drop information. Reply with JSON."""


def build(role: str, tools=None):
    from agent_framework import Agent
    instructions = {"analyst": ANALYST, "narrator": NARRATOR, "personaliser": PERSONALISER,
                    "translator": TRANSLATOR}[role]
    return Agent(chat_client(role), instructions=instructions, name=role, tools=tools)
