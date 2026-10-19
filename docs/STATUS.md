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

Waiting on the owner
- Create an Azure account → upgrade to pay-as-you-go → `az login`.
- Set up GitHub Copilot (Education if eligible, else Pro).

Next
- Budget alert, resource group, Foundry project + OpenAI deployment + Claude (Marketplace) deployment, smoke-test both.
- Day 3: interpret layer (C4: possessions, xG, possession value, phases, tempo, win probability, fact sheets) and the match-intel MCP server (C5); walking-skeleton deploy once Azure is ready.
