# Status

Updated at the end of each working session so any tool (Claude Code, Copilot) can pick up from here.

## 2026-10-19 — Day 1 setup

Done
- Repo scaffold: AGENTS.md (shared agent rules), plan, data provenance, calibration parameters (Wyscout CC BY 4.0).
- Local tooling: Azure CLI, azd, Node LTS installed; Python 3.12 venv.
- Azure MCP Server configured for Claude Code (`.mcp.json`) and Copilot (`.vscode/mcp.json`); it starts working after `az login`.
- **C1 contract** (`contracts/`, `schema/`): league, match meta, events, position frames, overlay messages.
- **C2 generator v0** (`generator/`): fictional 20-club league, possession-level engine, CLI (league / match / real-time stream), validation **41/41 metrics in band** over 1,140 matches ([validation/generator_v0.md](validation/generator_v0.md)). Docs: [GENERATOR.md](GENERATOR.md).

Waiting on the owner
- Create an Azure account → upgrade to pay-as-you-go → `az login`.
- Set up GitHub Copilot (Education if eligible, else Pro).

Next
- Budget alert, resource group, Foundry project + OpenAI deployment + Claude (Marketplace) deployment, smoke-test both.
- Day 2: generator v1 (position frames at 2 Hz, fixtures/season mode, fatigue), CI workflow running pytest + validate.
