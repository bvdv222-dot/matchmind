# MatchMind

Live, explainable match intelligence for every kind of fan. Built for the Microsoft *Inside the Game* hackathon.

A calibrated generator streams synthetic, Premier-League-realistic match events. An interpret layer turns them into possessions, xG, possession value, phases, tempo and win probability. A team of AI agents (Microsoft Agent Framework on Microsoft Foundry) picks the moments that matter and explains *why* in verified prose. That prose is personalised for casual fans, analysts, club fans and player-focus viewers, in several languages, and rendered as timed overlays beside the match.

> Work in progress: see [docs/BUILD_PLAN.md](docs/BUILD_PLAN.md) and [docs/STATUS.md](docs/STATUS.md).

## Run it locally

```
py -3.12 -m venv .venv && .venv\Scripts\activate && pip install -e .[dev]
cd web && npm install && npm run build && cd ..
python -m intel.train          # rebuild the analysis models (already committed)
python -m api                  # http://127.0.0.1:8000, then pick a fixture
```

The agents use a local model through Ollama by default (`qwen2.5:7b-instruct`); `MM_AGENTS=off` runs without
models (deterministic overlays and fact-based answers), and `MM_AI_PROVIDER=foundry` switches to Microsoft Foundry.

## How it fits together

| Part | Docs |
|---|---|
| Synthetic league, matches and position frames, validated against a real season | [docs/GENERATOR.md](docs/GENERATOR.md) |
| Interpret layer (xG, possession value, win probability, expectations, shifts, moments, fact sheets) and the match-intel MCP server | [docs/INTEL.md](docs/INTEL.md) |
| Agent workflow (Analyst, Narrator, Verifier, Personaliser, Translator) on Microsoft Agent Framework | [docs/AGENT_SYSTEM.md](docs/AGENT_SYSTEM.md) |
| API, live WebSocket feed, ask-this-view and the web app | [docs/API_AND_WEB.md](docs/API_AND_WEB.md) |

## Data

All match data is synthetic. Calibration sources and licences: [docs/DATA_PROVENANCE.md](docs/DATA_PROVENANCE.md).

## License

[MIT](LICENSE)
