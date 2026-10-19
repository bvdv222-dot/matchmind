"""MatchMind API: REST views, the live WebSocket feed, ask-this-view, and the match-intel MCP endpoint.

One process holds the match registry, so REST, WebSocket, the agents and MCP clients all see the same live state.

  python -m api            # http://127.0.0.1:8000  (web app at /, MCP at /intel/mcp)
"""
from __future__ import annotations

import asyncio
import os
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agents import config as agent_config
from agents import roles
from agents.personas import LANGUAGES
from api import ask as ask_mod
from api.channel import Channel, Viewer, agents_enabled
from api.intel_local import LocalIntel
from mcp_server import server as tools

WEB_DIST = Path(__file__).resolve().parents[1] / "web" / "dist"
CHANNELS: dict[str, Channel] = {}
_stack = AsyncExitStack()
mcp_http = tools.server.streamable_http_app()        # match-intel over streamable HTTP, served at /intel/mcp


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with tools.server.session_manager.run():
        yield
        for ch in CHANNELS.values():
            ch.stop()
        await _stack.aclose()


app = FastAPI(title="MatchMind API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])
app.mount("/intel", mcp_http)


def _names(home: str, away: str) -> dict:
    reg = tools.registry()
    league, roster, ids = set(), set(), {}
    for t in reg.league.teams:
        ns = [t.name] + [p.name for p in t.players]
        league |= set(ns)
        ids[t.team_id] = t.name
        ids.update({p.player_id: p.name for p in t.players})
        if t.team_id in (home, away):
            roster |= set(ns)
    return {"league": league, "roster": roster, "ids": ids}


def _channel(match_id: str) -> Channel:
    if match_id not in CHANNELS:
        raise HTTPException(404, f"match {match_id} is not live; POST /api/matches/start first")
    return CHANNELS[match_id]


# ------------------------------------------------------------------ REST

@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "live": list(CHANNELS)}


@app.get("/api/config")
def get_config() -> dict:
    return {"agents": agents_enabled(), "models": agent_config.describe(), "languages": {"en": "English", **LANGUAGES}}


@app.get("/api/fixtures")
def fixtures(round: int | None = None) -> dict:
    out = tools.list_fixtures(round=round)
    for f in out["fixtures"]:
        f["live"] = f["match_id"] in CHANNELS
    return out


class StartRequest(BaseModel):
    match_id: str | None = None
    home: str | None = None
    away: str | None = None
    speed: float = Field(10.0, gt=0, le=600)
    languages: list[str] = Field(default_factory=lambda: ["es"])


async def _agents(url: str | None) -> dict | None:
    if not agents_enabled():
        return None
    analyst_tools = None
    if url and os.environ.get("MM_ANALYST_MCP", "on") != "off":
        from agent_framework import MCPStreamableHTTPTool
        try:
            analyst_tools = await _stack.enter_async_context(MCPStreamableHTTPTool(
                name="match_intel", url=url, load_prompts=False,
                allowed_tools=["compare_to_expected", "explain_event", "get_player_card"]))
        except Exception:
            analyst_tools = None        # the Analyst still works from the moments it is given
    return {"analyst": roles.build("analyst", tools=[analyst_tools] if analyst_tools else None),
            "narrator": roles.build("narrator"), "personaliser": roles.build("personaliser"),
            "translator": roles.build("translator")}


@app.post("/api/matches/start")
async def start(req: StartRequest) -> dict:
    reg = tools.registry()
    try:
        fx = reg.find_fixture(req.match_id, req.home, req.away)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    if fx.match_id not in CHANNELS:
        run = await asyncio.to_thread(reg.start, fx, req.speed, True)
        langs = [x for x in req.languages if x in LANGUAGES][:3]
        ch = Channel(run, langs, agents_enabled())
        port = os.environ.get("MM_PORT", "8000")
        agents = await _agents(os.environ.get("MM_SELF_MCP_URL", f"http://127.0.0.1:{port}/intel/mcp"))
        ch.start(LocalIntel(), agents, _names(fx.home, fx.away))
        CHANNELS[fx.match_id] = ch
    ch = CHANNELS[fx.match_id]
    with ch.run.lock:
        return {"match_id": fx.match_id, "meta": ch.run.live.meta, "state": ch.run.live.state(),
                "languages": ch.languages, "agents": ch.agents_on}


@app.get("/api/matches/{match_id}/state")
def state(match_id: str) -> dict:
    ch = _channel(match_id)
    with ch.run.lock:
        return {**ch.run.live.state(), "win_probability": ch.run.live.win_probability()}


@app.get("/api/matches/{match_id}/dashboard")
def dashboard(match_id: str) -> dict:
    """Everything the analyst view shows, computed from the match so far."""
    ch = _channel(match_id)
    lm = ch.run.live
    with ch.run.lock:
        teams = {}
        for tid in (lm.home, lm.away):
            tv = lm.team_view(tid)
            net = tv["network"]
            net["nodes"] = {pid: {**n, "name": lm.short(pid)} for pid, n in net["nodes"].items()}
            teams[tid] = {k: tv[k] for k in ("name", "stats", "vs_expected", "phases", "network", "attack_standing",
                                              "defence_standing")}
        from intel import facts
        moments = [{**{k: v for k, v in m.items() if k not in ("win_prob_before", "win_prob_after")},
                    "headline": facts.headline(lm, m)} for m in lm.moments[-40:]]
        return {"state": {**lm.state(), "win_probability": lm.win_probability()}, "teams": teams,
                "windows": lm.windows(), "win_probability_history": lm.winprob_history,
                "top_players": lm.top_players(n=8), "moments": moments,
                "facts": facts.match_sheet(lm)["lines"], "home": lm.home, "away": lm.away}


@app.get("/api/matches/{match_id}/players/{player_id}")
def player(match_id: str, player_id: str) -> dict:
    ch = _channel(match_id)
    with ch.run.lock:
        try:
            return ch.run.live.player_view(player_id)
        except KeyError as e:
            raise HTTPException(404, f"unknown player {player_id}") from e


@app.get("/api/matches/{match_id}/agents")
def agent_log(match_id: str) -> dict:
    """The agent workflow's trace for every note so far (transparency panel)."""
    ch = _channel(match_id)
    return {"enabled": ch.agents_on, "models": agent_config.describe(), "notes": ch.agent_log[-20:]}


@app.post("/api/matches/{match_id}/ask")
async def ask(match_id: str, req: ask_mod.AskRequest) -> dict:
    ch = _channel(match_id)
    lines = await asyncio.to_thread(ask_mod.context_lines, tools, match_id, req)
    with ch.run.lock:
        st = ch.run.live.state()
    return await ask_mod.answer(req, lines, st, ch.names, ch.agents_on)


# ------------------------------------------------------------------ WebSocket

@app.websocket("/ws/matches/{match_id}")
async def feed(ws: WebSocket, match_id: str, persona: str = "casual", lang: str = "en"):
    await ws.accept()
    if match_id not in CHANNELS:
        await ws.send_json({"type": "error", "data": f"match {match_id} is not live"})
        await ws.close()
        return
    ch = CHANNELS[match_id]
    v = Viewer(ws, persona, lang)
    await ch.add(v)
    try:
        while True:
            msg = await ws.receive_json()
            if msg.get("type") == "prefs":            # persona / language / player-focus switch
                v.persona = msg.get("persona", v.persona)
                v.lang = msg.get("lang", v.lang)
                v.focus_player = msg.get("focus_player", v.focus_player)
                for bundle in ch.notes[-6:]:
                    await ws.send_json({"type": "overlay", "data": ch.pick(bundle, v), "replay": True})
    except WebSocketDisconnect:
        pass
    finally:
        ch.remove(v)


if WEB_DIST.exists():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
