"""The data contract every MatchMind component builds against.

Change a model here first, re-export the JSON Schemas (`python -m contracts.export`), then update producers and
consumers. Event coordinates are metres on a 105 x 68 pitch in the ACTING team's frame (attacking towards x = 105,
y = 0 on that team's left touchline). Position frames are the exception: absolute, home team attacking towards
x = 105 in period 1.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PITCH_LENGTH = 105.0
PITCH_WIDTH = 68.0

Position = Literal["GK", "CB", "LB", "RB", "DM", "CM", "AM", "LW", "RW", "ST"]
Role = Literal["GK", "DF", "MD", "FW"]
Foot = Literal["left", "right", "both"]

EventType = Literal[
    "period_start", "period_end",
    "pass", "carry", "take_on", "pressure", "tackle", "interception", "clearance", "aerial_duel", "ball_recovery",
    "shot", "save", "foul", "card", "substitution", "offside", "ball_out",
]
PassSubtype = Literal["ground", "high", "head", "cross", "launch", "through", "throw_in", "goal_kick", "corner",
                      "free_kick", "kick_off"]
ShotSubtype = Literal["open_play", "free_kick", "penalty"]
CardSubtype = Literal["yellow", "second_yellow", "red"]
Outcome = Literal[
    "complete", "incomplete", "out", "offside",      # pass
    "goal", "saved", "blocked", "off_target", "post",  # shot
    "won", "lost", "neutral",                         # take_on, tackle, aerial_duel
    "held", "parried",                                # save
]
BodyPart = Literal["left_foot", "right_foot", "head", "other"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Point(_Model):
    x: float = Field(ge=0, le=PITCH_LENGTH)
    y: float = Field(ge=0, le=PITCH_WIDTH)


class Colors(_Model):
    primary: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    secondary: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")


# --------------------------------------------------------------------------- league (fictional)

class PlayerAttributes(_Model):
    """Generator inputs. Multipliers centre on 1.0; physical values are per-90 profiles."""
    passing: float = Field(gt=0, description="completion odds multiplier")
    finishing: float = Field(gt=0, description="goal probability multiplier vs the xG model")
    dribbling: float = Field(gt=0, description="take-on odds multiplier")
    defending: float = Field(gt=0, description="tackle / interception odds multiplier")
    aerial: float = Field(gt=0, description="aerial duel odds multiplier")
    top_speed_kmh: float
    distance_m_per_min: float
    sprints_per90: float


class Player(_Model):
    player_id: str
    team_id: str
    name: str
    short_name: str
    shirt: int = Field(ge=1, le=99)
    position: Position
    role: Role
    foot: Foot
    height_cm: int
    weight_kg: int
    age: int
    attributes: PlayerAttributes


class TeamRatings(_Model):
    """Multiplicative, league geometric mean 1.0. attack/defence act on chance volume, quality on chance value."""
    attack: float = Field(gt=0)
    defence: float = Field(gt=0, description="> 1 = concedes more")
    quality: float = Field(gt=0, description="finishing / chance-quality multiplier")


class Team(_Model):
    team_id: str
    name: str
    short_name: str
    city: str
    stadium: str
    colors: Colors
    formation: str
    ratings: TeamRatings
    players: list[Player]


class League(_Model):
    league_id: str
    name: str
    season: str
    seed: int
    teams: list[Team]


# --------------------------------------------------------------------------- match

class SheetPlayer(_Model):
    player_id: str
    name: str
    short_name: str
    shirt: int
    position: Position


class TeamSheet(_Model):
    team_id: str
    name: str
    short_name: str
    colors: Colors
    formation: str
    starting: list[SheetPlayer] = Field(min_length=11, max_length=11)
    bench: list[SheetPlayer]


class Venue(_Model):
    name: str
    city: str
    pitch_length: float = PITCH_LENGTH
    pitch_width: float = PITCH_WIDTH


class MatchMeta(_Model):
    match_id: str
    competition: str
    season: str
    round: int
    kickoff_utc: str
    venue: Venue
    referee: str
    home: TeamSheet
    away: TeamSheet
    seed: int
    generator_version: str


class Event(_Model):
    """One match event. `t` is seconds since the period started; `minute` is 0-based (StatsBomb style, so 45+2 in
    the first half is 47); `clock` is the broadcast display ("45+2'")."""
    event_id: str
    match_id: str
    seq: int = Field(ge=0)
    period: Literal[1, 2]
    t: float = Field(ge=0)
    minute: int = Field(ge=0)
    clock: str
    type: EventType
    subtype: str | None = None
    outcome: Outcome | None = None
    team_id: str | None = None
    player_id: str | None = None
    related_player_id: str | None = Field(None, description="receiver, opponent in a duel, player fouled, sub on")
    start: Point | None = None
    end: Point | None = None
    body_part: BodyPart | None = None
    speed_kmh: float | None = Field(None, ge=0, description="ball speed for passes and shots")
    possession: int = Field(ge=0, description="possession counter; increments when the team in control changes")
    possession_team_id: str | None = None
    tags: list[str] = Field(default_factory=list)


class Ball3(_Model):
    x: float
    y: float
    z: float = 0.0


class PlayerPosition(_Model):
    player_id: str
    team_id: str
    x: float
    y: float
    speed_kmh: float = 0.0


class PositionFrame(_Model):
    """Low-rate positions for overlays and player-focus mode (absolute frame, see module docstring)."""
    match_id: str
    period: Literal[1, 2]
    t: float
    ball: Ball3
    players: list[PlayerPosition]


# --------------------------------------------------------------------------- overlays (what the screen renders)

OverlayKind = Literal["score_bug", "stat_tile", "moment_card", "player_tag", "win_prob", "narrative", "recap"]


class OverlayTime(_Model):
    period: Literal[1, 2]
    t: float
    clock: str


class OverlayMessage(_Model):
    msg_id: str
    match_id: str
    kind: OverlayKind
    at: OverlayTime
    ttl_s: float = Field(gt=0, description="how long to keep it on screen")
    priority: int = Field(ge=0, le=9, description="9 = interrupt everything (goal)")
    audience: list[str] = Field(default_factory=lambda: ["all"], description="persona ids, or 'all'")
    lang: str = "en"
    title: str | None = None
    body: str | None = None
    data: dict = Field(default_factory=dict)
    source_event_ids: list[str] = Field(default_factory=list)
    verified: bool = Field(False, description="passed the Verifier's grounding checks")
