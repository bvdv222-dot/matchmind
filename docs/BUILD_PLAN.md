# Inside the Game — full build plan

Status 19 Oct 2026: registered. Submission closes **27 Oct 23:59 PT** (28 Oct ~17:00 Brisbane). Judging runs to 10 Nov, and the app must stay up and free to test until then.
Inputs: [DATA_PROVENANCE.md](DATA_PROVENANCE.md) (sources, licences), [../calibration/params_wyscout_pl1718.json](../calibration/params_wyscout_pl1718.json) (generator calibration).

Name: **MatchMind**. Target: Grand Prize + **Best Multi-Agent System**, with Foundry as the secondary fit.

---

## 1. What we're building (one paragraph for the README)

A live match-intelligence pipeline for a fictional league. A calibrated generator streams synthetic Premier-League-realistic events. An interpret layer turns them into possessions, xG, possession value, phases, tempo and win probability. A team of agents on Microsoft Agent Framework + Foundry picks the moments that matter, explains *why* in verified prose, and rewrites it per viewer: casual fan, analyst, club fan or player-focus, in several languages. Timed overlay JSON drives a broadcast-style web view. Every generated sentence is checked against the numbers it came from.

---

## 2. Repo layout (new public repo, fresh history)

```
matchmind/
  AGENTS.md                 shared rules for Claude Code AND Copilot (.github/copilot-instructions.md points here)
  azure.yaml, infra/        azd + Bicep (all Azure resources, managed identity, no keys in code)
  schema/                   event + overlay JSON schemas (the contract everything builds against)
  generator/                synthetic league, squads, match engine, real-time publisher, validation
  intel/                    interpret layer: possessions, xG, possession value (EP), phases, tempo, networks, win prob, expectation baselines
  mcp_server/               "match-intel" MCP server exposing intel/ as tools
  agents/                   Agent Framework workflow: Analyst, Narrator, Verifier, Personaliser, Translator + orchestrator
  api/                      FastAPI: REST + WebSocket/Web PubSub broadcaster, persona endpoints, "ask this view"
  web/                      React + Vite + TypeScript: overlay, fan app, analyst dashboard, player focus
  evals/                    eval sets (incl. refusals), Foundry evaluation runner, number-check pass rate
  fabric/                   (optional) Eventstream/KQL definitions, validation notebook
  calibration/              copied from here (CC BY 4.0 Wyscout params + scripts, attribution)
  docs/                     architecture diagram, data provenance & licences, hero-tech usage, demo script
  .github/workflows/        tests, evals, deploy
```

**Methods adapted from the author's earlier sports-analytics work, re-implemented from scratch for this project:** a two-team game-state Markov value model → `intel/value.py`; a number-grounding check on generated text → `agents/verify.py`; fact-sheet-then-narrative reporting → `agents/narrator.py`; a ridge opponent-adjusted expectation model → `intel/expect.py`; a multiple-testing-controlled style-shift test → `intel/shifts.py`; calibrated outcome probabilities → `intel/winprob.py`; a retrieval/answer-quality eval harness → `evals/`.

---

## 3. Components, in build order

| # | Component | What "done" means | Depends on |
|---|---|---|---|
| C1 | **Event schema** (`schema/`) | JSON Schema for match metadata, events (SPADL-like: type, subtype, team, player, t, x/y start/end, outcome, body part, tags), optional low-rate positions, and overlay messages (timed, typed: `stat_tile`, `moment_card`, `player_tag`, `win_prob`, `narrative`). | — |
| C2 | **Generator** | Fictional 20-club league with correlated attack/defence ratings and squads (role, height/weight/age/foot, finishing multiplier, physical profile). Possession-level Markov engine from the transition, turnover, zone and set-piece params; xG for shots; game-state and time-of-match multipliers; cards and subs. Real-time mode (configurable speed, e.g. 90 min in 9) + batch mode. | C1 |
| C3 | **Generator validation** | 1,000 simulated matches vs `params_wyscout_pl1718.json`: goals, scorelines, H/D/A, shots, pass completion by zone, possessions, set-piece rates. Report with pass/fail bands. The judges' "optimized synthetic data creation". | C2 |
| C4 | **Interpret layer** (`intel/`) | Live state per match: score, possessions, xG, possession value (EP grid trained on synthetic matches), phases (build-up, final-third entries, transitions, set pieces, turnover cost), tempo/"control vs chaos", pass network, pass difficulty (completion model by zone/type/length), win probability (calibrated, Brier-checked), expectation baselines, segment shift tests. Emits **fact sheets** (numbers + plain-language standings + direction words). | C1, C2 (training data) |
| C5 | **Match-intel MCP server** | Tools: `get_match_state`, `get_fact_sheet(scope)`, `get_moments(since)`, `compare_to_expected(metric)`, `get_player_card(player)`, `explain_value(event_id)`. Runs over stdio locally, HTTP on Azure. | C4 |
| C6 | **Agents** | Agent Framework workflow: **Analyst** (chooses moments from EP swings, shifts, milestones), **Narrator** (writes only from the fact sheet), **Verifier** (deterministic tools: numbers, player names on pitch, minute ≤ now, standings, direction words; rejects with reasons), **Personaliser** (persona, club, player focus, reading level), **Translator**. Orchestrator: handoffs, one revision, then fallback to a templated sentence. All state in the store. Traced. | C4, C5, Foundry |
| C7 | **API** | FastAPI: start/stop match, subscribe to a match feed (WebSocket locally, Web PubSub on Azure behind one `Broadcaster` interface), persona CRUD, "ask about this view" (context = exactly what's on screen). | C4, C6 |
| C8 | **Web** | Broadcast overlay (score bug, win-prob strip, moment cards, player tags with speed/distance triggers), fan app with persona switch, analyst dashboard (xG timeline, EP map, pass network, phase/tempo charts), player-focus mode, language switch. | C7 |
| C9 | **Evals** | Eval set: factual Q&A, moment explanations, refusals (stats we don't have), translations. Metrics: number-check pass rate, Verifier rejection rate, Foundry groundedness/relevance, latency per note. Runs in CI. A regression opens a GitHub issue via `gh`. | C6 |
| C10 | **Infra + deploy** | `azd up` creates everything (§4); managed identity; Key Vault only where unavoidable; GitHub Actions deploy on main. | all |
| C11 | **Fabric** (optional) | Eventstream from Event Hubs → Eventhouse; KQL dashboard of live league stats; lakehouse with the validation run. | C2, account (§6) |
| C12 | **Submission** | README (architecture, hero-tech usage, data provenance/licences, how to test), < 2 min demo video, public URL and test instructions. | all |

---

## 4. Services: what, how, when, and who connects them

"Claude" = Claude Code in this session (writes the code/Bicep and runs CLIs once you're signed in). "You" = steps only you can or should do: account creation, payment, accepting terms, interactive sign-in.

| Service | Role | Local stand-in during build | Connect when | Who / how |
|---|---|---|---|---|
| **GitHub repo** (public) | Code, CI, issues | — | **Day 1** | Claude via `gh repo create` (you're already signed in as bvdv222-dot). |
| **Azure subscription → pay-as-you-go** | Everything | — | **Day 1, first thing** | **You.** Free-trial subscriptions get **0 quota for Azure OpenAI models**; upgrading to PAYG unlocks quota and keeps the remaining credit. Set a **budget alert** (e.g. A$100) in Cost Management. |
| **Azure CLI, azd, Functions tools, Node 20+** | Tooling | — | Day 1 | Claude installs via `winget` (with your OK); **you** run `az login` / `azd auth login` (browser sign-in). After that Claude can run az/azd commands. |
| **Microsoft Foundry** project + model deployments | Models, Agent Service, evaluations, tracing, content filters | Ollama via the `AI_PROVIDER` switch (dev only) | **Day 1–2: connect early**, not at the end (see §7) | Claude writes the Bicep/CLI to create the project and deployments; **you** accept any model terms in the portal. Two deployments: *fast* (live notes, personalisation) and *strong* (recaps, chat). |
| **Claude models in Foundry** (optional) | Use Claude as the agents' model | — | Day 2 if wanted | **You** subscribe via Azure Marketplace. This needs PAYG with a card, and **usage bills to the card, not the free credit**. Default to an OpenAI model in Foundry, which the credit covers, unless you want Claude in the app. |
| **Azure Event Hubs** | Real-time event bus (generator → intel → Fabric) | Event Hubs emulator in Docker (verify the current image), or an in-process queue behind the same `Bus` interface | Day 3 (walking-skeleton deploy) | Claude (Bicep). Basic/Standard tier; Standard if Fabric reads from it. |
| **Azure Cosmos DB** (serverless) | Shared agent state: match state, fact sheets, personas, agent outputs | Cosmos DB Linux emulator (Docker, preview) or SQLite behind a `Store` interface | Day 3 | Claude (Bicep). Serverless keeps idle cost near zero through judging. |
| **Azure Container Apps** | api, intel, mcp_server, generator (job), agents | Docker Compose | **Day 3 skeleton**, then every day | Claude (azd). Min replicas 1 for the api during judging to avoid cold starts. |
| **Azure Web PubSub** | Push overlay JSON to browsers | FastAPI WebSocket behind the `Broadcaster` interface | Day 5–6 | Claude (Bicep). Free tier is enough for judging. |
| **Azure Static Web Apps** (or Container Apps) | Web front end | Vite dev server | Day 6 | Claude (azd). |
| **Azure AI Translator / AI Speech** | Multi-language text, spoken commentary | Model-based translation; skip speech locally | Day 6 | Claude (Bicep + SDK). Speech is a stretch goal. |
| **Application Insights** | Tracing (Agent Framework / OpenTelemetry), logs | Console | Day 3 with the skeleton | Claude (Bicep). |
| **Azure MCP Server** | Lets Copilot/Claude query and manage your Azure resources while building | — | Day 1, after `az login` | Claude adds it to `.mcp.json` (Claude Code) and `.vscode/mcp.json` (Copilot). Uses your `az login`, so no secrets. |
| **GitHub Copilot** (Agent Mode / CLI) | Scored dev tool | — | Day 1 | **You**: check your plan (Free / Pro / Education). Copilot CLI is GA and offers Claude models (Sonnet/Opus 4.6+, Haiku 4.5), so building with Claude *through Copilot* counts for both. |
| **GitHub Actions** | Tests, evals, deploy (OIDC to Azure, no stored secret) | Local pytest | Day 4 | Claude writes the workflows and sets up the federated credential with `az`/`gh`. |
| **Microsoft Fabric** (optional) | Real-Time Intelligence + validation lakehouse | Validation report as HTML/markdown | Day 7, **only if account access works** | **You.** Fabric doesn't accept Gmail. Options: a work account in your Azure tenant's Entra directory (user@…onmicrosoft.com), your UQ account if the uni allows it, or a pay-as-you-go **F2 capacity** you pause when idle. Trials for new tenants may be restricted. Cut it if day 7 is tight. |

**Cost guardrails:** serverless Cosmos, Basic/Standard Event Hubs (1 TU), Container Apps consumption, Web PubSub free tier, small models, a budget alert, and **pausing the generator** when nobody is watching (replay mode for judges, §8). The free credit runs 30 days from sign-up. After that, PAYG charges apply, so keep the footprint small through 10 Nov.

---

## 5. Day-by-day (Brisbane dates; Azure connections in bold)

| Day | Build | Connections |
|---|---|---|
| **Mon 20** | Repo + AGENTS.md + Copilot instructions; schema (C1); generator v0 (teams, squads, possession engine) | **GitHub repo; Azure PAYG upgrade + budget; az/azd login; Azure MCP Server; Foundry project + 2 model deployments; smoke-test one chat call** |
| Tue 21 | Generator v1 (shots/xG, set pieces, game state, cards/subs, real-time publisher) + validation report (C3) | — |
| Wed 22 | Interpret layer (C4): possessions, xG, EP grid, phases, tempo, win prob, fact sheets; MCP server (C5) | **Walking skeleton on Azure: Container Apps + Event Hubs + Cosmos + App Insights via `azd up`**; generator → intel running in the cloud |
| Thu 23 | Agents (C6): Analyst, Narrator, Verifier, orchestrator + fallback; tracing | Agents on Foundry models; **Agent Service** if used for hosted agents |
| Fri 24 | Personaliser + Translator; evals (C9) + CI; expectation baselines + shift tests | **GitHub Actions → Azure (OIDC)**; Foundry evaluations |
| Sat 25 | Web (C8): overlay, fan app, analyst view, player focus; API (C7) | **Web PubSub; Static Web Apps** |
| Sun 26 | Polish, multi-language, Speech (stretch), Fabric (optional), README + docs, record demo footage | **Translator/Speech; Fabric** (if account works) |
| Mon 27 | Buffer: fixes, demo video edit, final deploy, submission (due 28 Oct ~17:00 Brisbane) | Freeze; confirm the judge URL works logged out |

The rule throughout: **deploy every day from day 3**. Nothing should meet Azure for the first time on day 8.

---

## 6. How the work splits between Claude Code and Copilot

- **Claude Code** (here) is good for most of the build: Python services, generator, intel models, agents, Bicep/azd, CI, evals, debugging, running az/azd/gh/docker.
- **GitHub Copilot Agent Mode / Copilot CLI with a Claude model** is a scored tool, so use it for **real, visible chunks**, e.g. the React front end (C8) and the MCP server (C5). Capture a few screenshots and prompts for the README and video.
- **One source of truth for both tools:** `AGENTS.md` (architecture, conventions, data/licence rules, test commands). Copilot reads `.github/copilot-instructions.md`, which points to it; Claude Code reads it via CLAUDE.md. Plan docs and decisions live in `docs/` so either tool can pick up where the other stopped.
- **Interactive steps stay with you:** account upgrades, payment, model terms and marketplace subscriptions, Fabric sign-up, browser sign-ins.

---

## 7. Hindrances to "build with Claude, put it on Azure at the end", and the fixes

| Risk | Why it bites late | Fix |
|---|---|---|
| **Model quota / billing** | Free-trial subscriptions have 0 Azure OpenAI quota; Claude-in-Foundry needs PAYG and bills the card; regions vary | Upgrade on day 1 and deploy both models that day |
| **Agent behaviour differs by model** | Tool calling, structured output and verbosity differ between local Ollama models and Foundry models; prompts tuned locally won't transfer | Develop the agents **against Foundry from day 4**; keep Ollama only for offline unit work |
| **Agent Service / evaluations / tracing can't be emulated** | They exist only in Foundry | Use the cloud endpoints from the start (the code still runs on your machine) |
| **Infra surprises**: RBAC/managed-identity propagation delays, Bicep errors, WebSocket idle timeouts, CORS, cold starts, Event Hubs checkpoint storage | Each costs hours and they pile up at the end | Walking-skeleton `azd up` on day 3, redeploy daily |
| **Judging credit for Copilot** | Claude Code alone isn't on the hero-tech list | Use Copilot (with Claude models) for real parts; document it |
| **Fabric access** | Gmail is rejected; trials for new tenants may be blocked | Decide on day 1; treat it as optional |
| **Secrets in a public repo** | Repo must be public | Managed identity + OIDC; `.env.example` only; GitHub push protection on |
| **Cost after the credit window / during judging** | App must stay up to 10 Nov | Serverless/consumption tiers, budget alert, replay mode with the generator off |
| **Long sessions losing context** | Eight days of build in a few chats | AGENTS.md + BUILD_PLAN.md + a running `docs/STATUS.md` updated at the end of each day |
| **Originality** | Rules require new work | Fresh repo, earlier ideas rewritten from scratch, data from CC BY 4.0 / MIT sources with attribution. AI assistance is allowed (rules permit third-party technical help; the work and ideas must be yours) |

Nothing here makes a Claude-first build a bad idea. Claude Code can write and deploy all of it. The only real problem is leaving the **Azure connection** to the end. Connect Foundry on day 1, deploy the skeleton on day 3, then build out.

---

## 8. Demo & judge experience

- **Judge URL:** landing page → pick a match → choose a persona (Casual / Analyst / Club fan / Player focus) and a language → watch a 9-minute accelerated match with overlays, moment cards and live notes → "Ask about this view". A **replay mode** serves a pre-generated match so judges see it even with the generator paused.
- **Demo video (< 2 min):** 15 s problem → 30 s the same moment shown to two personas side by side → 20 s the "why it mattered" view (EP swing + verified narrative, with the Verifier catching a wrong number) → 20 s architecture (Foundry, Agent Framework, MCP, Event Hubs, Cosmos, Container Apps) → 15 s synthetic-data validation → 10 s multi-language close.
- **README:** what's synthetic and how it's validated; data provenance and licences (Wyscout CC BY 4.0, SkillCorner MIT; no StatsBomb data shipped); hero-tech table; how to run locally (`docker compose up`) and on Azure (`azd up`).

---

## 9. Decisions (19 Oct 2026)

1. **Copilot:** not set up yet. Get a plan first (Education via the GitHub Student Developer Pack if eligible, otherwise Pro), then build the front end and MCP server through Copilot Agent Mode / Copilot CLI with a Claude model.
2. **Azure:** no account yet. Create one, upgrade to pay-as-you-go straight away, and set a budget alert.
3. **App models: both.** An OpenAI model in Foundry for fast live notes and personalisation (covered by credit); Claude in Foundry for recaps and analyst chat (Marketplace subscription, billed to the card). The provider is set per agent in config, so either can take over if quota or cost bites.
4. **Fabric: try it** on day 7 with a work account in the Azure tenant's Entra directory, or a paused F2 capacity. Optional, and cut if time is short.
5. **Name:** MatchMind (public repo `matchmind`).
