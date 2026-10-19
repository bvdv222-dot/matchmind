# Synthetic match generator

`generator/` produces a fictional league, its season and its matches, with events and 2 Hz position frames whose statistics track a real Premier League season (Wyscout PL 2017/18, CC BY 4.0) and real physical profiles (SkillCorner, MIT). The app only ever sees this synthetic data.

## Pieces

| File | Role |
|---|---|
| `contracts/models.py` | The data contract: league, match metadata, events, position frames, overlay messages and the stream envelope. JSON Schemas are exported to `schema/` with `python -m contracts.export`; CI fails if they drift. |
| `generator/params.py` | Every number the generator samples. **CALIBRATED** values come from `calibration/params_wyscout_pl1718.json`; **ASSUMED** values have no clean open-data source and are marked with their reasoning. |
| `generator/names.py` | Fictional names: syllable-built surnames and towns, one town prefix per club, real top-flight club names blocked. |
| `generator/league.py` | 20 clubs with correlated attack / defence / chance-quality ratings and 24-man squads drawn from real height, weight, age and footedness distributions by role, plus physical profiles and stamina. |
| `generator/engine.py` | The possession-level match engine (below). |
| `generator/season.py` | Double round-robin fixtures (circle method, greedy venue balancing), simulated results, and the league table with form. |
| `generator/frames.py` | 2 Hz positions for all players and the ball, built from a match's events. |
| `generator/feed.py` | The live feed: meta, events and frames merged in match-time order, optionally paced in real time. |
| `generator/validate.py` | Simulates full seasons, checks 44 match and season metrics (plus 4 physical ones with `--frames`), and exits non-zero on any miss. |
| `generator/__main__.py` | CLI: `league`, `season`, `match`, `stream`. |

## How a match is simulated

- **One action per step by the ball holder:** a shot, pass, carry or take-on, sometimes after a defender's **pressure** event. Each event is stamped when the action *starts* and carries `duration_s` (ball travel or carry time).
- **Shots:**
  - Propensity is set by distance band and goal angle, then scaled by team strength and home advantage.
  - Game state shifts it too: trailing sides ×1.06, leaders ×0.92, both amplified after 75'.
  - Goal probability uses the xG model fitted on 8,451 real shots (distance, angle, header). It's then scaled by player finishing, team chance quality, defensive fatigue and a half-of-match factor.
- **Passes:**
  - Type mix (ground, high, head, cross, launch, through) depends on the third and lane.
  - Lengths are lognormal around the real medians.
  - Completion starts from the real by-type rate and is adjusted for pressure, length, passer skill, passer fatigue and team strength.
  - Failed passes become interceptions, contested loose balls or balls out of play. Failed crosses are cleared, sometimes for a corner.
- **Restarts:**
  - Each takes dead-ball time and runs a short script.
  - Corners lead to a shot about 30% of the time, as in the real data.
  - Free kicks become a direct shot, a cross or a short pass depending on position.
  - Penalties convert about 70%.
- **Fatigue:**
  - Grows with minutes on the pitch, divided by the player's stamina.
  - Lowers pass and duel odds, and raises the quality of chances a tired defence concedes.
  - Slows players in the frames, and decides who gets substituted.
- **Discipline and subs:**
  - Fouls are rare in the box.
  - Yellows rise through the match. Booked players are more careful, so second yellows are rare.
  - A red card brings a numbers-down penalty.
  - Each team makes 2–3 substitutions, from about the 52nd minute.
- **Clock:** time on the ball, ball travel and dead-ball time add up to real half lengths (median 47.1 and 49.1 minutes).
- **League strength:** ratings are top-heavy, like real top flights. Strong clubs pull away further than weak ones fall behind, which gives a realistic table: champions around 90–100 points, bottom around 20–30.

## Position frames

Every 0.5 s, each player's position is the sum of four layers, then capped by speed:

1. **Team shape:** formation spots compressed into a realistic block. The block slides with the ball, stretches in possession and squeezes out of it. Measured block: ~38 m wide × ~34 m deep, against SkillCorner's 37 × 31.
2. **Involvement:** the player is pulled to the exact spot of every event he takes part in (passer, receiver, tackler, carrier).
3. **Off-ball wandering:** smooth movement whose size is solved per player so total distance matches his profile (per-90 m/min, reduced by fatigue). Measured: 97% of profile.
4. **Sprint bursts:** attacking runs in possession, recovery runs out of it, at the player's per-90 sprint rate and between 25.2 km/h and his top speed. Outside a burst, players are capped at 22 km/h, so sprint counts are controlled (measured: 96% of profile). Top speeds never exceed the player's attribute.

The ball interpolates between event locations, with height (`z`) on lofted passes. Frames use the absolute frame (the home team's first-half attacking frame), and carry each player's speed and cumulative distance for the "speed and distance indicators" overlays. Building them takes about 1.4 s per match.

## Live feed

`python -m generator stream --home KIR --away RAV --frames --speed 10` writes one `StreamMessage` per line, `{"kind": "meta" | "event" | "frame", "data": ...}`, in match-time order. Events come before frames at the same instant. It's paced so 90 minutes play in about 9. Downstream components read the same lines from a pipe now and from Event Hubs from day 3.

## Validation

All 48 metrics are within band: [validation/GENERATOR_VALIDATION.md](validation/GENERATOR_VALIDATION.md). They cover:
- results: goals, the home/draw/away split
- shots: volume, distance shares, conversion
- passing: volume and completion by type
- flow: possessions, corners, throw-ins, goal kicks, free kicks
- discipline: fouls, cards, offsides, subs, penalties
- set pieces: corner-to-shot rate
- strength: team strength spread, season table spread
- timing: half lengths
- physical: frame distance, sprints and team shape

CI repeats the check on every push.

## Usage

```
python -m generator league --out data/league.json
python -m generator season --out data/season                 # fixtures, results, table
python -m generator match --home KIR --away RAV --seed 3 --frames
python -m generator stream --home KIR --away RAV --seed 3 --speed 10 --frames
python -m generator.validate --seasons 3 --frames 8
```

## Known assumptions and gaps

- **Pressure:** its effect on completion, and the pressure rates, are assumptions (shape informed by SkillCorner engagements). Re-check them against the DFL tracking set (CC BY 4.0) if time allows.
- **Home advantage:** the home volume edge is set slightly above the observed net ratio, because home sides lead more often and leaders shoot less.
- **Fatigue and late-game effects** are plausible shapes, validated only through their effect on outcome metrics (second-half goal share, draws).
- **Not modelled yet:** injuries, weather, in-match tactical changes beyond the red-card penalty, goalkeeper distribution styles.
