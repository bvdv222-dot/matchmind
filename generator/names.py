"""Fictional names for players, clubs, towns, stadiums and referees.

Surnames and towns are built from syllables so the league never borrows a real roster; a short blocklist keeps
real top-flight club names out.
"""
from __future__ import annotations

import random

FIRST = [
    "Leo", "Marco", "Samuel", "Tomas", "Ibrahim", "Kenji", "Mateo", "Elias", "Noah", "Rafael", "Jonah", "Felix",
    "Andre", "Nico", "Oscar", "Lucas", "Milan", "Yusuf", "Adrian", "Theo", "Emil", "Dario", "Hugo", "Kwame", "Joel",
    "Ruben", "Silas", "Owen", "Victor", "Aleksander", "Kofi", "Tariq", "Lars", "Iker", "Bruno", "Callum", "Pavel",
    "Diego", "Arlo", "Mikel", "Sami", "Jules", "Ezra", "Tobias", "Idris", "Luca", "Rory", "Anton", "Kai", "Malik",
]
_SUR_A = ["Ash", "Bel", "Cor", "Dun", "El", "Far", "Gar", "Hal", "Is", "Jor", "Kel", "Lan", "Mor", "Nor", "Or",
          "Pel", "Quin", "Ros", "Sal", "Tor", "Ul", "Var", "Wes", "Yar", "Zel", "Bran", "Cas", "Del", "Fen", "Gil"]
_SUR_B = ["ford", "ley", "ton", "ani", "ez", "ovic", "sen", "berg", "ini", "ard", "well", "by", "son", "ado",
          "ier", "ek", "mann", "eau", "ski", "oni", "ara", "ström", "ides", "ou", "ama", "elli", "ow", "ano"]
_TOWN_A = ["Ash", "Brack", "Cald", "Dun", "Elm", "Fair", "Glen", "Harl", "Ivy", "Kirk", "Lyn", "Mar", "Neth",
           "Oak", "Pen", "Raven", "Stan", "Thorn", "Wex", "Wyn", "Hollo", "Brin", "Cran", "Stow"]
_TOWN_B = ["bridge", "mouth", "field", "wick", "stead", "borough", "port", "dale", "minster", "ham", "by",
           "combe", "ford", "haven", "moor", "gate"]
_CLUB_SUFFIX = ["United", "City", "Athletic", "Rovers", "Wanderers", "Albion", "Town", "FC", "County", "Rangers"]
_STADIUM = ["Park", "Road", "Ground", "Lane", "Stadium", "Meadow", "Arena"]
_BLOCK = {"Southampton", "Middlesbrough", "Bournemouth", "Brentford", "Burnley", "Fulham", "Watford", "Wolverhampton",
          "Sunderland", "Everton", "Chelsea", "Arsenal", "Tottenham", "Leicester", "Liverpool", "Brighton", "Ipswich"}

PALETTE = [("#C8102E", "#FFFFFF"), ("#003399", "#FFFFFF"), ("#FDB913", "#231F20"), ("#6CABDD", "#1C2C5B"),
           ("#00A650", "#FFFFFF"), ("#7A263A", "#1BB1E7"), ("#000000", "#FFFFFF"), ("#E03A3E", "#000000"),
           ("#FFFFFF", "#132257"), ("#F78F1E", "#0B0B0B"), ("#5C2D91", "#F2C200"), ("#0E7C61", "#F4E04D"),
           ("#B30838", "#F9C00C"), ("#1D428A", "#C8102E"), ("#2E2D88", "#FFFFFF"), ("#7F7F7F", "#D7263D"),
           ("#00539F", "#FFD100"), ("#8B0000", "#F5F5DC"), ("#0B3D2E", "#E8E8E8"), ("#E4007C", "#111111")]


def surname(rng: random.Random) -> str:
    return rng.choice(_SUR_A) + rng.choice(_SUR_B)


def person(rng: random.Random) -> tuple[str, str]:
    first, last = rng.choice(FIRST), surname(rng)
    return f"{first} {last}", f"{first[0]}. {last}"


def town(rng: random.Random, taken: set[str]) -> str:
    """A new town; each prefix is used once per league so club names don't blur together."""
    used_prefixes = {p for p in _TOWN_A for t in taken if t.startswith(p)}
    while True:
        a = rng.choice(_TOWN_A)
        t = a + rng.choice(_TOWN_B)
        if a not in used_prefixes and t not in _BLOCK:
            taken.add(t)
            return t


def club(rng: random.Random, town_name: str) -> tuple[str, str]:
    suffix = rng.choice(_CLUB_SUFFIX)
    name = f"{town_name} {suffix}" if suffix != "FC" else f"FC {town_name}"
    return name, town_name[:3].upper()


def stadium(rng: random.Random) -> str:
    return f"{surname(rng)} {rng.choice(_STADIUM)}"
