# Deploying MatchMind to Azure

Everything is defined in this repo:
- `azure.yaml` and `infra/` hold the Bicep for azd.
- The `Dockerfile` builds the image **in Azure Container Registry** (`remoteBuild: true`), so no local Docker is needed.
- `.github/workflows/deploy.yml` deploys on demand.

## What gets created

One resource group, `rg-<env>`, holds:

| Resource | Purpose | Notes |
|---|---|---|
| Container App (`ca-app-…`) + environment | the app: API, WebSocket feed, agents, match-intel MCP at `/intel/mcp`, web UI | 1 vCPU / 2 GiB, **one replica, always on**: live match state is in process, and judges never hit a cold start |
| Container Registry (Basic) | holds the image; builds it remotely | pulls via managed identity (AcrPull) |
| User-assigned managed identity | how the app reaches every service | no keys anywhere: local auth is disabled on every data service |
| Microsoft Foundry account + project `matchmind` | the agents' models | deploys `gpt-4.1-mini` (GlobalStandard) as the fast tier; the strong tier (Claude) is added by hand, below |
| Event Hubs namespace (Basic) + hub `match-feed` | the live feed: events, state, overlays and sampled frames, partitioned by match | `MM_EVENTHUBS_SKU=Standard` if Fabric will read it |
| Cosmos DB (serverless): `notes`, `asks`, `matches` | the audit trail: every note with its plan and agent trace; every viewer question with the context sent | partition key `/match_id` |
| Web PubSub (Free) + hub `matchmind` | fan-out for when the app scales past one replica | provisioned, not yet used (the app's own WebSocket serves one replica) |
| Application Insights + Log Analytics | traces: Agent Framework spans for every workflow, executor and model call; logs | sensitive data (prompt text) is not recorded |
| Budget alert (subscription) | email at 50%, 80% and 100% of a monthly amount, and at 100% forecast | needs `MM_BUDGET_EMAIL` |

## First deployment (you, about 30 minutes)

1. **Account.** Create an Azure account (azure.microsoft.com/free), then **upgrade the subscription to pay-as-you-go** in the portal (Subscriptions → your subscription → Upgrade). The upgrade keeps the free credit, but it's needed for model quota.
2. **Sign in** from a terminal in the repo:
   ```
   az login
   azd auth login
   ```
3. **Create the environment.** `eastus2` has the widest model availability, including Claude in Foundry:
   ```
   azd env new matchmind-dev --location eastus2
   azd env set MM_BUDGET_EMAIL you@example.com
   azd env set MM_BUDGET_AMOUNT 150
   ```
   Optional settings:

   | Setting | Default | When to change it |
   |---|---|---|
   | `MM_FAST_MODEL` / `MM_FAST_MODEL_VERSION` | `gpt-4.1-mini` / `2025-04-14` | if that model isn't offered in your region |
   | `MM_FAST_MODEL_CAPACITY` | `50` (thousand tokens per minute) | if quota is tight |
   | `MM_DEPLOY_FOUNDRY` | `true` | `false` runs without models: fact-based overlays and answers only |
   | `MM_EVENTHUBS_SKU` | `Basic` | `Standard` for Fabric |
4. **Provision and deploy:**
   ```
   azd up
   ```
   Provisioning takes roughly 5–10 minutes. Then the image builds in ACR and the Container App switches to it. azd prints the app URL (`SERVICE_APP_URI`).
5. **Check it:**
   - Open `<url>/api/config`. Expect `"store": "cosmos"`, `"bus": "eventhubs"`, `"telemetry": true` and `"provider": "foundry"`.
   - Open `<url>`, pick a fixture and watch notes arrive. On Foundry they take a few seconds each, not 15–60.

## Adding Claude as the strong tier (optional)

1. In the Foundry portal (ai.azure.com), open project **matchmind** → Model catalog → a Claude model (e.g. Claude Sonnet) → Deploy.
   - This creates an Azure Marketplace subscription.
   - **Usage is billed to your card, not the free credit.**
   - Available regions include East US 2 and Sweden Central.
2. Run:
   ```
   azd env set MM_STRONG_DEPLOYMENT <the deployment name>
   azd provision
   ```
   The Analyst then runs on Claude, and the writers stay on the fast model.

The app's identity already has *Azure AI User* on the Foundry account. Until a strong deployment is set, the Analyst uses the fast model.

## Day-to-day

| Task | Command |
|---|---|
| Ship code changes | `azd deploy` (remote build + new revision) |
| Infra changes | `azd provision` (keeps the running image) |
| Logs | `az containerapp logs show -n $(azd env get-value SERVICE_APP_NAME) -g $(azd env get-value AZURE_RESOURCE_GROUP) --follow` |
| Traces | Application Insights → Transaction search / Agents view |
| Run locally against Azure | `azd env get-values > .env`. Your user has data access to Cosmos, Event Hubs (receive) and Foundry. Set `MM_STORE=cosmos`, `MM_BUS=eventhubs`, `MM_AI_PROVIDER=foundry`, then `python -m api`. |

## Deploy from GitHub (OIDC, no secrets)

```
azd pipeline config
```

This creates a federated credential for the repo and sets the repository variables that `.github/workflows/deploy.yml` uses. Deploy with Actions → *Deploy to Azure* → Run workflow. CI already builds and smoke-tests the same image on every push.

## Rough cost while it runs

Check these estimates in the Azure pricing calculator before relying on them.

| Item | Estimate |
|---|---|
| Container Apps, 1 vCPU / 2 GiB always on | the largest line, tens of USD a month; halve the CPU and memory in `resources.bicep` after judging if needed |
| Event Hubs Basic (1 TU) | about USD 11 a month |
| ACR Basic | about USD 5 a month |
| Cosmos serverless, Web PubSub Free, App Insights within the free 5 GB | near zero |
| Foundry models | pay per token; a full 95-minute match with notes in 4 personas × 2 languages is a few hundred calls |

The free credit (USD 200 for 30 days) covers the build and the judging window. The budget alert warns before anything surprising.

## Limits built in for a public demo

- At most `MM_MAX_LIVE` (default 4) matches live at once; others can be joined.
- Ask-this-view is limited to `MM_ASK_PER_MINUTE` (default 8) questions per minute per client.

## Tearing down after judging (after 10 Nov 2026)

```
azd down --purge
```

This deletes the resource group and purges the soft-deleted Foundry account so its name can be reused. Delete the budget in Cost Management, or leave it.
