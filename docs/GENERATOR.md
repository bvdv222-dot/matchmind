# Synthetic match generator

`generator/` produces a fictional league and matches whose statistics track a real Premier League season (Wyscout PL 2017/18, CC BY 4.0). The app only ever sees these synthetic events.

## Pieces

| File | Role |
|---|---|
| `contracts/models.py` | The data contract: league, match metadata, events, position frames, overlay messages. JSON Schemas are exported to `schema/` with `python -m contracts.export`. |
| `generator/params.py` | Every number the engine samples. **CALIBRATED** values come from `calibration/params_wyscout_pl1718.json`; **ASSUMED** values have no clean open-data source yet and are marked with their reasoning. |
| `generator/names.py` | Fictional names: syllable-built surnames and towns, with real top-flight club names blocked. |
| `generator/league.py` | 20 clubs with correlated attack / defence / quality ratings (log-sds and correlations from the real team-strength fit) and 24-man squads drawn from the real height, weight, age and footedness distributions by role, plus SkillCorner-based physical profiles. |
| `generator/engine.py` | The possession-level match engine (below). |
| `generator/validate.py` | Simulates full seasons and checks 41 metrics against the real targets; exits non-zero if any falls outside its band. |
| `generator/__main__.py` | CLI: `league`, `match`, `stream`. |

## How a match is simulated

- **One action per step by the ball holder:** a shot, pass, carry or take-on, sometimes after a defender's **pressure** event.
- **Shots:** propensity by distance band and goal angle, scaled by team strength, home advantage and game state (trailing ×1.06, leading ×0.92). Goal probability uses the xG model fitted on 8,451 real shots (distance, angle, header), times player finishing, team chance quality and a half-of-match factor. Second halves carry 58% of goals.
- **Passes:**
  - The type mix (ground, high, head, cross, launch, through) depends on the third and lane.
  - Lengths are lognormal around the real medians.
  - Completion starts from the real by-type rate, adjusted for pressure, length, the passer's skill and team strength.
  - Failed passes become interceptions, contested loose balls or the ball going out. Out-of-play balls produce throw-ins and goal kicks.
  - Failed crosses are cleared, sometimes for a corner.
- **Restarts** take dead-ball time and run short scripts:
  - Corners lead to a shot about 30% of the time, matching the real rate.
  - Free kicks become a direct shot, a cross or a short pass depending on position.
  - Penalties convert about 70%.
  - Kick-offs follow goals.
- **Discipline and subs:** fouls (rare in the box), yellows rising through the match, second yellows and reds with a numbers-down penalty, and 2–3 substitutions per team from about the 52nd minute.
- **Clock:** time comes from decision time on the ball, ball travel time and dead-ball time. Half lengths land on the real medians (47.1 and 49.1 minutes).

Coordinates are metres on a 105 × 68 pitch in the acting team's attacking frame. Every event carries the period, `t` (seconds into the period), a broadcast `clock` ("45+2'"), a possession counter and tags (`under_pressure`, `set_piece`, `key_pass`, `assist`, `counter_attack`). Passes and shots include ball speed.

## Validation

All 41 metrics are within band over 1,140 matches: [validation/generator_v0.md](validation/generator_v0.md). They cover goals, the home/draw/away split, shots and their distance shares, conversion, passes and completion by type, possessions (counted the way the calibration counted them), corners, throw-ins, goal kicks, free kicks, fouls, cards, offsides, subs, penalties, corner-to-shot rate, team strength spread and half lengths.

## Usage

```
python -m generator league --out data/league.json
python -m generator match --home KIR --away RAV --seed 3
python -m generator stream --home KIR --away RAV --seed 3 --speed 10    # JSON lines, 90 min in ~9
python -m generator.validate --seasons 3
```

## Not yet modelled

- Position frames: the contract exists, but the engine doesn't emit them yet (day 3, for overlays and player focus).
- Fatigue, tactical changes after subs and red cards beyond a flat penalty, injuries, weather.
- Pressure's effect on completion is an assumption (no licence-clean source yet). Re-check it against the DFL tracking set if time allows.
