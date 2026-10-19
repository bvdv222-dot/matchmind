"""Which model each agent runs on.

MM_AI_PROVIDER=ollama (default until Foundry is connected) or foundry. Each role uses a tier: "fast" for the
high-volume writing roles, "strong" for the Analyst's judgement. Foundry needs FOUNDRY_PROJECT_ENDPOINT plus the
two deployment names and uses DefaultAzureCredential (az login locally, managed identity on Azure): no keys.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

ROLE_TIER = {"analyst": "strong", "narrator": "fast", "personaliser": "fast", "translator": "fast"}


@dataclass(frozen=True)
class Provider:
    name: str
    fast: str
    strong: str


def provider() -> Provider:
    name = os.environ.get("MM_AI_PROVIDER", "ollama").lower()
    if name == "foundry":
        fast = os.environ.get("FOUNDRY_FAST_DEPLOYMENT", "")
        # until a strong deployment (e.g. Claude via the Marketplace) exists, the Analyst uses the fast model
        return Provider("foundry", fast, os.environ.get("FOUNDRY_STRONG_DEPLOYMENT") or fast)
    # one 7B model for both tiers by default: an 8 GB GPU can't hold 7B and 14B together, and swapping costs ~10 s
    return Provider("ollama", os.environ.get("MM_OLLAMA_FAST", "qwen2.5:7b-instruct"),
                    os.environ.get("MM_OLLAMA_STRONG", "qwen2.5:7b-instruct"))


def chat_client(role: str):
    p = provider()
    model = p.strong if ROLE_TIER[role] == "strong" else p.fast
    if p.name == "foundry":
        from agent_framework.foundry import FoundryChatClient
        from azure.identity.aio import DefaultAzureCredential
        return FoundryChatClient(project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"], model=model,
                                 credential=DefaultAzureCredential())
    from agent_framework.openai import OpenAIChatCompletionClient
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    return OpenAIChatCompletionClient(model=model, base_url=f"{host}/v1", api_key="ollama")


def describe() -> dict:
    p = provider()
    models = {role: (p.strong if tier == "strong" else p.fast) for role, tier in ROLE_TIER.items()}
    return {"provider": p.name, "models": models}
