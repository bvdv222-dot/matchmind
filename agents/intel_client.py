"""A small MCP client for match-intel, used by the workflow's deterministic steps (gathering facts).

Connects over streamable HTTP when MM_MCP_URL is set (Azure, or a local `python -m mcp_server --http`), otherwise
spawns the server over stdio. The Analyst agent reaches the same server through Agent Framework's MCP tool.
"""
from __future__ import annotations

import json
import os
import sys
from contextlib import AsyncExitStack

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamablehttp_client


class IntelClient:
    def __init__(self, url: str | None = None):
        self.url = url or os.environ.get("MM_MCP_URL")
        self._stack = AsyncExitStack()
        self.session: ClientSession | None = None

    async def __aenter__(self) -> IntelClient:
        if self.url:
            read, write, _ = await self._stack.enter_async_context(streamablehttp_client(self.url))
        else:
            params = StdioServerParameters(command=sys.executable, args=["-m", "mcp_server"])
            read, write = await self._stack.enter_async_context(stdio_client(params))
        self.session = await self._stack.enter_async_context(ClientSession(read, write))
        await self.session.initialize()
        return self

    async def __aexit__(self, *exc) -> None:
        await self._stack.aclose()

    async def call(self, tool: str, **args) -> dict:
        res = await self.session.call_tool(tool, {k: v for k, v in args.items() if v is not None})
        if res.isError:
            raise RuntimeError(f"match-intel {tool} failed: {res.content[0].text if res.content else ''}")
        data = res.structuredContent
        if data is None:
            data = json.loads(res.content[0].text)
        return data.get("result", data) if isinstance(data, dict) else data
