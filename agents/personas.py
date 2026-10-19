"""Viewer personas: the same verified intelligence, told differently."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Persona:
    persona_id: str
    label: str
    style: str
    max_words: int
    club_id: str | None = None
    player_id: str | None = None


def default_personas(home_id: str, away_id: str, focus_player: str | None = None) -> list[Persona]:
    out = [
        Persona("casual", "Casual fan",
                "Plain, lively words for someone who loves the game but not the numbers. Say 'big chance' instead of "
                "xG and skip jargon like field tilt or PPDA. One or two short sentences.", 32),
        Persona("analyst", "Analyst",
                "Precise and data-led for an analyst: keep the key metrics (xG, field tilt, possession value, PPDA) "
                "and what they say about the game. Two sentences.", 50),
        Persona(f"fan_{home_id}", "Home fan",
                "Written for a supporter of {club}, from {club}'s side of the story (even when the news is about the "
                "other team): warm and partisan but fair and accurate. Use 'we', 'us' and 'our' for {club}.", 38,
                club_id=home_id),
        Persona(f"fan_{away_id}", "Away fan",
                "Written for a supporter of {club}, from {club}'s side of the story (even when the news is about the "
                "other team): warm and partisan but fair and accurate. Use 'we', 'us' and 'our' for {club}.", 38,
                club_id=away_id),
    ]
    if focus_player:
        out.append(Persona(f"player_{focus_player}", "Player focus",
                           "For a viewer following {player}: lead with what this means for {player} if involved, "
                           "otherwise give one line of context.", 35, player_id=focus_player))
    return out


LANGUAGES = {"es": "Spanish", "fr": "French", "pt": "Portuguese", "de": "German", "it": "Italian", "ja": "Japanese",
             "ar": "Arabic"}
