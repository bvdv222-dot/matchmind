# MatchMind — agent & contributor guide

Read by Claude Code (via CLAUDE.md) and GitHub Copilot (via .github/copilot-instructions.md). Keep it current: it is the single source of truth for both tools.

## What this is

Live match intelligence for a **fictional** football (soccer) league, built for the Microsoft *Inside the Game* hackathon.
Pipeline: **generate → ingest → interpret → explain → render → personalise**. Plan: [docs/BUILD_PLAN.md](docs/BUILD_PLAN.md). Daily state: [docs/STATUS.md](docs/STATUS.md).

## Hard rules

1. **Synthetic data only.** The app consumes events from `generator/`, never real matches. Real open data is used only to calibrate the generator, via `calibration/params_wyscout_pl1718.json` (Wyscout, CC BY 4.0, attribution in [docs/DATA_PROVENANCE.md](docs/DATA_PROVENANCE.md)). Do not add raw third-party data files to the repo, and never add StatsBomb data or numbers derived from it.
2. **Fictional names only** for clubs, players, stadiums and officials. No real club badges, kits or player likenesses.
3. **Public repo: no secrets.** Use managed identity / `DefaultAzureCredential` and GitHub OIDC. Config goes in `.env` (git-ignored); `.env.example` lists the names only.
4. **Every generated sentence is grounded.** Agents write only from fact sheets produced by `intel/`. `agents/verify.py` checks numbers, player names, minutes, standings and direction words before anything is shown. A failed check gets one revision, then a templated fallback.
5. **Original work.** Everything here is written for this project (created after 29 Sep 2026). Don't paste code from other projects. Open-source libraries are fine within their licences.

## Layout

| Path | Role |
|---|---|
| `schema/` | JSON Schemas: match metadata, events, overlay messages. The contract between components; change it first, then the code. |
| `generator/` | Synthetic league, squads, match engine, real-time publisher, validation against the calibration file |
| `intel/` | Possessions, xG, possession value, phases, tempo, networks, win probability, expectation baselines, fact sheets |
| `mcp_server/` | MCP server exposing `intel/` as tools |
| `agents/` | Microsoft Agent Framework workflow: Analyst, Narrator, Verifier, Personaliser, Translator |
| `api/` | FastAPI: REST, WebSocket / Web PubSub broadcaster, personas, "ask about this view" |
| `web/` | React + Vite + TypeScript front end |
| `evals/` | Eval sets and runners (Foundry evaluations + number-check pass rate) |
| `infra/` | Bicep for `azd` |
| `calibration/` | Generator calibration parameters and the scripts that produced them |

## Conventions

- **Python 3.12** for services (Azure SDK / Agent Framework compatibility). Create the venv with `py -3.12 -m venv .venv`.
- Pitch coordinates: metres, 105 × 68, origin bottom-left from the acting team's view, attacking towards x = 105.
- Time: `period` (1, 2) + `t` (seconds since the period started) + `minute` for display.
- Interfaces over services, so everything runs locally: `Bus` (Event Hubs / in-process), `Store` (Cosmos DB / SQLite), `Broadcaster` (Web PubSub / WebSocket), `LLM` (Foundry / Ollama, chosen per agent in config).
- Tests: `pytest` from the repo root. A generator change must keep `generator/validate.py` passing.
- Comments explain *why*, not what. Small modules, typed functions, no dead code.

## Commands

```
py -3.12 -m venv .venv && .venv\Scripts\activate && pip install -e .[dev]
pytest
docker compose up            # local stack (added on day 3)
azd up                       # Azure (added on day 3)
```
