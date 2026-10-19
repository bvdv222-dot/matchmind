"""match-intel in-process: the same tool functions the MCP server exposes, called directly.

The API process hosts the registry, the MCP endpoint and the agents together, so the workflow's deterministic steps
call the tools without a network hop, while the Analyst agent still reaches them over MCP.
"""
from __future__ import annotations

import asyncio

from mcp_server import server as tools


class LocalIntel:
    async def call(self, tool: str, **args) -> dict:
        fn = getattr(tools, tool)
        return await asyncio.to_thread(fn, **{k: v for k, v in args.items() if v is not None})
