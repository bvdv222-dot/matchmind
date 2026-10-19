# Interpret layer and match-intel MCP server

`intel/` turns the live feed into football meaning: what's happening, why it matters, and how it compares with normal. Everything is deterministic and computed only from what the feed has shown so far. The language models in `agents/` write from its fact sheets and never compute numbers themselves.

## Modules

| Module | What it does |
|---|---|
| `xg.py` | Shot xG from the logistic model fitted on 8,451 real Premier League shots (distance, goal angle, header); penalties and direct free kicks at their real conversion rates. Over a synthetic season the app's xG matches goals 1.01 : 1. |
| `possessions.py` | Live possession tracking: start type (open play, interception, tackle won, throw-in, corner...), end type (shot, goal, intercepted, out of play...), passes, duration, final-third and box entries, xG and value per possession. |
| `value.py` | **Possession value.** Pitch cells are states; each on-ball action moves to the same team's next cell, the opponent's next cell, or a goal. One zero-sum linear system `(I - γ(Ps - Po)) V = r` (γ = 0.9, a horizon of about ten actions) gives every cell a value in goals. An action's value added = value after - value before. This is the "why it mattered" engine: *"that pass raised the team's possession value by 0.04 goals"*. |
| `ratings.py` | Team strength fitted on **last season's** results (a goals/xG blend, multiplicative Poisson with home advantage): what an analyst would know before kick-off, never the generator's hidden ratings. The fitted ratings track the hidden truth (tested: correlation > 0.6). |
| `winprob.py` | Live win/draw/loss: Poisson goals still to come from pre-match expectation × minutes left, adjusted for red cards and late game state. Checked on 760 held-out matches at 7 points in each match: Brier 0.456, calibrated decile by decile ([../intel/models/winprob.json](../intel/models/winprob.json)). Blending in live xG made Brier slightly *worse*, so it's off; momentum is shown separately. |
| `flow.py` | Team stats (xG, big chances, possession, field tilt, progressive passes, PPDA, pressures, long-ball share...); game phases per possession (build-up, counter-attack, direct, set piece, sustained attack); 5-minute windows with momentum and a **chaos index** (contested-ball rate vs a typical match: controlled / steady / scrappy / chaotic); pass networks (hub, busiest pair, average height). |
| `expect.py` | **Expectation baselines.** Per metric, a ridge fit on last season's team-matches, `y = mu + offence[team] + defence[opponent] + home`. Live values are compared at the same stage of the match with a widening noise band early on, and put into words: about / above / well above their usual, good for them or a concern. Standings come in words too ("6th-best attack of the 20 clubs"). |
| `shifts.py` | **Tactical shifts.** The last 15 minutes against the 30 before, on share metrics (possession, field tilt, high pressing): a two-proportion z-test per metric, then Benjamini-Hochberg across them. Only clear changes (q < 0.10) are announced, from the side of the team whose share grew. |
| `live.py` | `LiveMatch`: ingests StreamMessages one by one. It keeps score, possessions, value added, player tallies and physical maxima from frames, and detects **moments**: goals / braces / hat-tricks with win-probability swing and build-up, big chances missed, big saves, penalties, cards, substitutions, sustained pressure, momentum swings, chaotic spells, tactical shifts, speed tags (≥ 33 km/h) and 10 km distance milestones. A full match with frames ingests in about 0.1 s. |
| `facts.py` | **Fact sheets** (match, team, player, moment): deterministic sentences with every number already rendered and every comparison already in words. The narrative agents write only from these, and the Verifier checks their output against them. |
| `train.py` | `python -m intel.train` rebuilds every model in about a minute (below). |

## Models (`intel/models/`, small JSON, committed)

| File | Fitted on |
|---|---|
| `value_grid.json` | Two training leagues (seeds 9001, 9002), never the demo league |
| `norms.json` | The same training leagues: league norms for the chaos index and per-metric means |
| `winprob.json` | Parameters plus held-out evaluation (Brier, calibration deciles) |
| `league_2026.json` | The demo league's **previous** season (`season_offset=-1`): team ratings and expectation baselines |

Rebuild after any generator change: `python -m intel.train`.

## Lessons carried over from earlier work

- Give the language model words, not ranks: standings and directions are pre-computed ("well above their usual", "6th-best attack").
- Keep each sheet small and on one subject (match / team / player / moment) instead of one big prompt.
- Check the writing with code, not with another model (the Verifier in `agents/`).

## match-intel MCP server

`python -m mcp_server` (stdio, for Claude Code and GitHub Copilot; registered in `.mcp.json` and `.vscode/mcp.json`) or `python -m mcp_server --http --port 8765` (streamable HTTP, for agents on Azure).

| Tool | Returns |
|---|---|
| `list_fixtures(round?)` | Season fixtures with their status |
| `start_match(match_id or home+away, speed, with_frames)` | Plays a fixture live in the background |
| `advance_match(match_id or home+away, to_minute)` | Fast-forwards a fixture (95 = full time) |
| `get_match_state(match_id)` | Score, clock, xG, red cards, possession, live win probability |
| `get_fact_sheet(match_id, scope, subject_id?)` | Fact lines for match / team / player / moment |
| `get_moments(match_id, since_minute?, min_priority?)` | Detected moments with deterministic headlines |
| `compare_to_expected(match_id, team_id, metric?)` | Actual vs usual, with z-scores and words |
| `get_player_card(match_id, player)` | Profile, match tallies, possession value, physical |
| `explain_event(match_id, event_id)` | Possession value before/after/added; xG for shots |
| `get_win_probability(match_id)` | Now plus history |
| `get_rhythm(match_id)` | 5-minute windows: xG, field tilt, possession, tempo, chaos |
| `get_team_profile(team_id)` | Club identity and last-season standing |

The registry replays fixtures from the generator in-process today. From day 3 it reads the live feed from Event Hubs; the tools stay the same.
