"""Build a seeded fictional league: 20 clubs with correlated strength ratings and calibrated squads."""
from __future__ import annotations

import math
import random

from contracts.models import Colors, League, Player, PlayerAttributes, Team, TeamRatings
from generator import names
from generator import params as P


def _lognormal(rng: random.Random, sd: float, shift: float = 0.0) -> float:
    return math.exp(rng.gauss(shift, sd))


def _ratings(rng: random.Random, n: int) -> list[TeamRatings]:
    raw = []
    for _ in range(n):
        z1, z2, z3 = rng.gauss(0, 1), rng.gauss(0, 1), rng.gauss(0, 1)
        a = P.ATTACK_LOG_SD * z1
        # good attacks go with good (low-conceding) defences: negative correlation in the conceded multiplier
        d = P.DEFENCE_LOG_SD * (P.ATTACK_DEFENCE_CORR * z1 + math.sqrt(1 - P.ATTACK_DEFENCE_CORR ** 2) * z2)
        q = P.QUALITY_LOG_SD * (P.QUALITY_ATTACK_CORR * z1 + math.sqrt(1 - P.QUALITY_ATTACK_CORR ** 2) * z3)
        raw.append((a, d, q))
    # centre so the league's geometric mean is exactly 1 and calibrated totals hold
    means = [sum(r[i] for r in raw) / n for i in range(3)]
    return [TeamRatings(attack=round(math.exp(a - means[0]), 4), defence=round(math.exp(d - means[1]), 4),
                        quality=round(math.exp(q - means[2]), 4)) for a, d, q in raw]


def _player(rng: random.Random, team_id: str, idx: int, position: str, shirt: int) -> Player:
    role = P.ROLE_OF[position]
    cal = P.calibration()["players"][role]
    name, short = names.person(rng)
    left = cal["foot"].get("left", 0.2)
    u = rng.random()
    foot = "both" if u < 0.02 else ("left" if u < 0.02 + left else "right")
    # wide positions lean to the matching foot
    if position in ("LB", "LW") and rng.random() < 0.35:
        foot = "left"
    if position in ("RB", "RW") and rng.random() < 0.35:
        foot = "right"
    mpm, sprints, top = P.PHYSICAL[position]
    shifts = {  # role tilts on the generic multipliers (log scale); finishing stays mean 1 overall
        "GK": dict(passing=-0.05, dribbling=-0.4, defending=0.0, aerial=0.2, finishing=-1.0),
        "DF": dict(passing=-0.02, dribbling=-0.1, defending=0.15, aerial=0.15, finishing=-0.15),
        "MD": dict(passing=0.06, dribbling=0.0, defending=0.0, aerial=-0.05, finishing=0.0),
        "FW": dict(passing=-0.03, dribbling=0.15, defending=-0.2, aerial=0.0, finishing=0.08),
    }[role]
    attrs = PlayerAttributes(
        passing=round(_lognormal(rng, 0.10, shifts["passing"]), 3),
        finishing=round(_lognormal(rng, P.FINISHING_LOG_SD, shifts["finishing"]), 3),
        dribbling=round(_lognormal(rng, 0.15, shifts["dribbling"]), 3),
        defending=round(_lognormal(rng, 0.15, shifts["defending"]), 3),
        aerial=round(_lognormal(rng, 0.15, shifts["aerial"]), 3),
        top_speed_kmh=round(rng.gauss(top * P.PHYSICAL_SCALE, 1.2), 1),
        distance_m_per_min=round(rng.gauss(mpm * P.PHYSICAL_SCALE, 6), 1),
        sprints_per90=round(max(0.0, rng.gauss(sprints * P.PHYSICAL_SCALE, 2.0)), 1),
    )
    return Player(
        player_id=f"{team_id}-P{idx:02d}", team_id=team_id, name=name, short_name=short, shirt=shirt,
        position=position, role=role, foot=foot,
        height_cm=int(round(rng.gauss(cal["height_cm"]["mean"], cal["height_cm"]["sd"]))),
        weight_kg=int(round(rng.gauss(cal["weight_kg"]["mean"], cal["weight_kg"]["sd"]))),
        age=int(min(38, max(17, round(rng.gauss(cal["age"]["mean"], cal["age"]["sd"]))))),
        attributes=attrs,
    )


def _squad(rng: random.Random, team_id: str) -> list[Player]:
    shirts = {"GK": [1, 13], "CB": [4, 5, 15, 26], "LB": [3, 23], "RB": [2, 22], "DM": [6, 16], "CM": [8, 14, 18],
              "AM": [10, 20], "LW": [11, 17], "RW": [7, 19], "ST": [9, 21, 29]}
    out, idx = [], 1
    for position, count in P.SQUAD.items():
        for k in range(count):
            out.append(_player(rng, team_id, idx, position, shirts[position][k]))
            idx += 1
    return out


def build_league(seed: int = 2026, name: str = "Premier Synthetic League", season: str = "2026/27") -> League:
    rng = random.Random(seed)
    taken: set[str] = set()
    codes: set[str] = set()
    ratings = _ratings(rng, P.TEAMS)
    palette = rng.sample(names.PALETTE, P.TEAMS)
    formations, weights = zip(*P.FORMATION_WEIGHTS.items())
    teams = []
    for i in range(P.TEAMS):
        team_id = f"T{i + 1:02d}"
        city = names.town(rng, taken)
        club, code = names.club(rng, city)
        while code in codes:   # short codes must be unique on a scoreboard
            code = (city[:2] + rng.choice("ABCDEFGHKLMNPRSTUVWXYZ")).upper()
        codes.add(code)
        teams.append(Team(
            team_id=team_id, name=club, short_name=code, city=city, stadium=names.stadium(rng),
            colors=Colors(primary=palette[i][0], secondary=palette[i][1]),
            formation=rng.choices(formations, weights)[0], ratings=ratings[i], players=_squad(rng, team_id),
        ))
    return League(league_id=f"PSL-{seed}", name=name, season=season, seed=seed, teams=teams)
