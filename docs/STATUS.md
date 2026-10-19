# Status

Updated at the end of each working session so any tool (Claude Code, Copilot) can pick up from here.

## 2026-10-19 — Day 1 setup

Done
- Repo scaffold: AGENTS.md (shared agent rules), plan, data provenance, calibration parameters (Wyscout CC BY 4.0).
- Local tooling: Azure CLI, azd, Node LTS installed; Python 3.12 venv.
- Azure MCP Server configured for Claude Code (`.mcp.json`) and Copilot (`.vscode/mcp.json`); it starts working after `az login`.
- **C1 contract** (`contracts/`, `schema/`): league, match meta, events, position frames, overlay messages.
- **C2 generator v0** (`generator/`): fictional 20-club league, possession-level engine, CLI (league / match / real-time stream).
- **Generator v1:** events stamped at action start with `duration_s`; fatigue (stamina, late-game effects, tired players subbed); season mode (balanced double round robin, table, form); **2 Hz position frames** for all players and the ball; live feed envelope (`StreamMessage`). Validation **48/48 in band** (1,140 matches + 8 framed matches; [validation/GENERATOR_VALIDATION.md](validation/GENERATOR_VALIDATION.md)), stable across 5 seeds. Docs: [GENERATOR.md](GENERATOR.md).
- **CI** (`.github/workflows/ci.yml`): ruff, schema drift check, pytest, then generator validation (2 seasons + 4 framed matches) with the report in the job summary and as an artifact.


## 2026-10-19 — Day 3 work (started early)

Done
- **C4 interpret layer** (`intel/`): xG (real-fitted; matches synthetic goals 1.01 : 1 after a generator shot-location fix), live possessions, possession value (two-team Markov), team ratings from last season, calibrated live win probability (Brier 0.456 on 760 held-out matches), team stats / phases / rhythm & chaos index / pass networks, ridge expectation baselines, BH-controlled tactical shifts, moment detection, fact sheets. Docs: [INTEL.md](INTEL.md).
- **C5 match-intel MCP server** (`mcp_server/`): 12 tools, stdio + streamable HTTP, registered for Claude Code and Copilot; checked with a real stdio client.
- Tests: 20 passing; generator validation re-run 48/48.

Waiting on the owner
- Create an Azure account → upgrade to pay-as-you-go → `az login`.
- Set up GitHub Copilot (Education if eligible, else Pro).

Next
- Budget alert, resource group, Foundry project + OpenAI deployment + Claude (Marketplace) deployment, smoke-test both.
- Walking-skeleton deploy once Azure is ready: Container Apps (generator job, intel + MCP over HTTP), Event Hubs, Cosmos DB, App Insights via `azd up`; registry reads the bus instead of replaying in-process.
- Day 4: agents (Analyst, Narrator, Verifier, Personaliser, Translator) on Agent Framework + Foundry, calling match-intel.
