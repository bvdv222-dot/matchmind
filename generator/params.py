"""Calibration targets (from the Wyscout profile) plus the generator's own modelling assumptions.

Everything the engine samples lives here, so tuning never touches engine logic. CALIBRATED values come from
calibration/params_wyscout_pl1718.json. ASSUMED values have no clean open-data source yet (marked, with the
reasoning); generator/validate.py checks the outputs they drive.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

CALIBRATION = Path(__file__).resolve().parents[1] / "calibration" / "params_wyscout_pl1718.json"
GENERATOR_VERSION = "0.1.0"


@lru_cache(maxsize=1)
def calibration() -> dict:
    return json.loads(CALIBRATION.read_text(encoding="utf-8"))


def xg_coefficients() -> tuple[float, float, float, float]:
    m = calibration()["shots"]["xg_model"]
    return m["b0"], m["b1"], m["b2"], m["b3"]


# --------------------------------------------------------------------------- league structure

TEAMS = 20
SQUAD = {"GK": 2, "CB": 4, "LB": 2, "RB": 2, "DM": 2, "CM": 3, "AM": 2, "LW": 2, "RW": 2, "ST": 3}
ROLE_OF = {"GK": "GK", "CB": "DF", "LB": "DF", "RB": "DF", "DM": "MD", "CM": "MD", "AM": "MD",
           "LW": "FW", "RW": "FW", "ST": "FW"}

# Formations as starting positions. Home spots (attacking frame, metres) are where each slot sits when the ball is
# on halfway; the block shifts with the ball (engine.Team.spots).
FORMATIONS = {
    "4-3-3": ["GK", "LB", "CB", "CB", "RB", "DM", "CM", "CM", "LW", "ST", "RW"],
    "4-2-3-1": ["GK", "LB", "CB", "CB", "RB", "DM", "DM", "LW", "AM", "RW", "ST"],
    "4-4-2": ["GK", "LB", "CB", "CB", "RB", "LW", "CM", "CM", "RW", "ST", "ST"],
    "3-5-2": ["GK", "CB", "CB", "CB", "LB", "DM", "CM", "CM", "RB", "ST", "ST"],
}
FORMATION_WEIGHTS = {"4-3-3": 0.35, "4-2-3-1": 0.35, "4-4-2": 0.18, "3-5-2": 0.12}
# Slot spots by formation; y = 0 is the team's left touchline.
SPOTS = {
    "4-3-3": [(5, 34), (38, 8), (27, 24), (27, 44), (38, 60), (42, 34), (55, 22), (55, 46), (76, 10), (84, 34),
              (76, 58)],
    "4-2-3-1": [(5, 34), (38, 8), (27, 24), (27, 44), (38, 60), (44, 26), (44, 42), (72, 10), (66, 34), (72, 58),
                (84, 34)],
    "4-4-2": [(5, 34), (36, 8), (27, 24), (27, 44), (36, 60), (58, 8), (50, 26), (50, 42), (58, 60), (80, 26),
              (80, 42)],
    "3-5-2": [(5, 34), (28, 18), (26, 34), (28, 50), (55, 6), (44, 34), (56, 24), (56, 44), (55, 62), (80, 26),
              (80, 42)],
}

# --------------------------------------------------------------------------- team strength (CALIBRATED)
# Log-space sds and correlation from the multiplicative Poisson fit on shots (volume) and goals (volume x quality).
ATTACK_LOG_SD = 0.27   # wider than the fitted 0.22 because the skew below shortens the weak tail
DEFENCE_LOG_SD = 0.19
ATTACK_DEFENCE_CORR = -0.86
# goals attack sd 0.39 vs shots 0.22 -> the rest is chance quality; kept below the raw gap because part of that gap
# is finishing noise over one season.
QUALITY_LOG_SD = 0.27
QUALITY_ATTACK_CORR = 0.8
# ASSUMED: asymmetric strength (season points: real champions ~100, bottom ~31 vs a symmetric draw)
STRENGTH_SKEW_UP = 1.25
STRENGTH_SKEW_DOWN = 0.55
HOME_SHOT_MULT = 1.255      # shots home multiplier; split as sqrt on each side
HOME_GOAL_MULT = 1.335      # goals home multiplier: the extra over shots is better home finishing
# ASSUMED: the calibrated ratios are net of game state (home sides lead more, and leaders shoot less), so the
# underlying home edge has to be a little larger than the observed one
HOME_VOLUME_EXTRA = 1.08

# --------------------------------------------------------------------------- players
# Height / weight / age / left-foot share by role: CALIBRATED (Wyscout PL squads).
# Physical per-90 profiles: SkillCorner A-League aggregates (MIT) scaled +6% toward PL intensity (ASSUMED scale).
PHYSICAL = {   # position -> (m/min, sprints per 90, top speed km/h)
    "GK": (65, 0.5, 25.0), "CB": (106, 6.2, 29.8), "LB": (113, 11.0, 30.7), "RB": (113, 11.0, 30.7),
    "DM": (123, 6.4, 28.7), "CM": (123, 6.4, 28.7), "AM": (121, 7.5, 29.3), "LW": (119, 10.5, 30.5),
    "RW": (119, 10.5, 30.5), "ST": (118, 9.3, 30.0),
}
PHYSICAL_SCALE = 1.06
TEAM_WIDTH_M = 37.0          # SkillCorner (MIT): median outfield block width / depth from one match of tracking
TEAM_DEPTH_M = 31.0
FINISHING_LOG_SD = 0.15      # CALIBRATED-ish: player goals/xG spread minus noise, capped near +-30% (2 sd)

# --------------------------------------------------------------------------- match flow
HALF_STOPPAGE_MIN = {1: (1.9, 0.9), 2: (4.1, 1.4)}   # CALIBRATED from half lengths (mean, sd)

# Per-touch action mix by third (pass types normalised inside the engine). ASSUMED shapes, tuned in validation.
ACTION_MIX = {
    "def": {"pass": 0.87, "carry": 0.11, "take_on": 0.02},
    "mid": {"pass": 0.81, "carry": 0.15, "take_on": 0.04},
    "att": {"pass": 0.77, "carry": 0.14, "take_on": 0.09},
}
PASS_MIX = {   # third -> pass subtype weights (wide lanes add crosses in the final third)
    "def": {"ground": 0.80, "launch": 0.10, "high": 0.10},
    "mid": {"ground": 0.84, "high": 0.09, "through": 0.05, "launch": 0.02},
    "att": {"ground": 0.82, "through": 0.07, "high": 0.04, "cross": 0.07},
}
CROSS_WIDE_BONUS = 0.20       # extra cross weight with the ball in a wide final-third lane

# Pass completion by type: CALIBRATED (Wyscout). "ground" = simple pass, "through" = smart pass.
PASS_COMPLETION = {"ground": 0.917, "high": 0.537, "head": 0.625, "cross": 0.307, "launch": 0.538,
                   "through": 0.392, "throw_in": 0.85, "goal_kick": 0.70, "free_kick": 0.88, "kick_off": 0.98,
                   "corner": 0.30}
PASS_MEDIAN_LENGTH = {"ground": 15.5, "high": 39.8, "head": 14.7, "cross": 28.6, "launch": 45.7, "through": 19.4,
                      "throw_in": 14.0, "free_kick": 22.0, "kick_off": 10.0, "goal_kick": 50.0}
PRESSURE_RATE = {"def": 0.30, "mid": 0.26, "att": 0.36}   # ASSUMED (SkillCorner engagement-rate shape)
PRESSURE_ODDS = 0.62          # ASSUMED: odds multiplier on completion when pressed (re-centred by the engine)

TAKE_ON = {"won": 0.486, "lost": 0.224, "neutral": 0.290}  # CALIBRATED (ground attacking duel)
CARRY_LOSS = 0.03             # ASSUMED

# Shots: per-touch shot propensity by distance band (m), ASSUMED and tuned so band shares match CALIBRATED ones.
SHOT_PROPENSITY = [(6, 0.027), (11, 0.08), (16.5, 0.146), (22, 0.132), (30, 0.115), (36, 0.044)]
SHOT_OUTCOME_GIVEN_MISS = {"saved": 0.275, "blocked": 0.30, "off_target": 0.425}   # CALIBRATED (rescaled)
SAVE_RESULT = {"held": 0.62, "corner": 0.12, "loose": 0.26}                          # ASSUMED
BLOCK_RESULT = {"corner": 0.25, "loose": 0.75}                                        # ASSUMED
OFF_TARGET_POST = 0.05
HALF_CONVERSION = {1: 0.84, 2: 1.13}    # CALIBRATED: 42% of goals in the first half on 47% of shots
GAME_STATE_SHOTS = {"leading": 0.916, "level": 1.02, "trailing": 1.059}   # CALIBRATED (within-team)
LATE_GAME_STATE = {"from_minute": 75, "leading": 0.85, "trailing": 1.15}    # ASSUMED: score effects grow late

# Set pieces: CALIBRATED targets (shot within 15 s); engine probabilities are tuned to hit them.
CORNER_DIRECT_SHOT = 0.26
CORNER_SECOND_BALL = 0.35
FK_CROSS_DIRECT_SHOT = 0.15
DIRECT_FK_CONVERSION = 0.051
PENALTY_CONVERSION = 0.70
XG_SCALE = 0.81               # ASSUMED: absorbs the within-band location mix vs real shots; re-check on changes
BOOKED_CAUTION = 0.22         # ASSUMED: booked players foul less recklessly (second yellows are rare)

# Fouls & discipline: CALIBRATED rates, ASSUMED split across situations.
FOUL_ON_TAKE_ON = 0.10
FOUL_PER_TOUCH = 0.016       # possessor fouled (free kick to possessor)
ATTACKING_FOUL_PER_TOUCH = 0.0025
YELLOW_PER_FOUL = 0.145
RED_PER_FOUL = 0.0018
OFFSIDE_THROUGH = 0.11
OFFSIDE_HIGH = 0.03
# Fatigue (ASSUMED shape): f = FATIGUE_AT_90 * (minutes on / 90) ** 1.6 / stamina, capped at FATIGUE_CAP.
# It lowers pass and duel odds, raises chances conceded, slows players in the position frames and decides
# who is substituted.
FATIGUE_AT_90 = 0.12
FATIGUE_CAP = 0.30
FATIGUE_PASS = 0.8
FATIGUE_DUEL = 1.0
FATIGUE_DEFENCE_XG = 1.0
SUBS = {"three": 0.74, "minute_mean": 72.0, "minute_sd": 11.0, "earliest": 46, "latest": 89}

# Timing (seconds): ASSUMED, tuned so possessions/match and half lengths match.
DECISION_TIME = (1.60, 0.55)          # lognormal median, sigma: time on the ball before acting
RESTART_TIME = {"throw_in": (11, 4), "goal_kick": (24, 7), "corner": (32, 8), "free_kick": (24, 9),
                "direct_free_kick": (48, 12), "penalty": (65, 15), "kick_off_goal": (70, 15), "substitution": (32, 8),
                "card": (25, 8), "offside": (18, 5)}
BALL_SPEED_KMH = {"ground": (45, 9), "high": (62, 10), "launch": (70, 9), "cross": (65, 10), "through": (52, 9),
                  "head": (38, 8), "throw_in": (35, 6), "goal_kick": (75, 9), "free_kick": (55, 10),
                  "corner": (68, 9), "kick_off": (30, 5), "shot": (88, 16), "header_shot": (48, 10)}   # ASSUMED
