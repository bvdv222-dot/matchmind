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

## 2026-10-19 — Day 4 work (started early)

Done
- **C6 agents** (`agents/`): Agent Framework workflow Gather -> Analyst -> Facts -> Narrator -> Verifier (revise once / fall back) -> Personaliser (4-5 personas) -> Translator -> Publish, with a trace per note. The Verifier is code: numbers, attribution, time, result language, forecasting, names, real clubs, tone, length. Local provider: Ollama `qwen2.5:7b-instruct` via the OpenAI-compatible client; Foundry switch ready. The Analyst calls match-intel tools over MCP (HTTP). Full match run locally: 11 notes, real catches (invented 71%, a draw probability given to a team, hashtags); see [examples/agents_local_run.md](examples/agents_local_run.md). Docs: [AGENT_SYSTEM.md](AGENT_SYSTEM.md).
- MCP SDK pinned to 1.30 (Agent Framework needs `mcp<2`); match-intel ported to FastMCP.
- Tests: 38 passing (agent workflow tested offline with scripted models).

- Create an Azure account → upgrade to pay-as-you-go → `az login`.
- Set up GitHub Copilot (Education if eligible, else Pro).

Next
- Budget alert, resource group, Foundry project + OpenAI deployment + Claude (Marketplace) deployment, smoke-test both.
- Walking-skeleton deploy once Azure is ready: Container Apps (generator job, intel + MCP over HTTP), Event Hubs, Cosmos DB, App Insights via `azd up`; registry reads the bus instead of replaying in-process.
- Switch agents to Foundry models; Foundry evaluations on a fixed eval set (incl. refusal cases); tracing to App Insights.
- C7 API + C8 web: overlay feed, persona/language switch, ask-this-view.
