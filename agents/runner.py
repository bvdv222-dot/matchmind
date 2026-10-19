"""Run a match through the agent workflow, driven entirely through match-intel over MCP.

usage: python -m agents run --home ASH --away ELM [--langs es] [--focus-player <id>] [--max-notes 8]
                            [--step 1] [--out data/notes]

Starts match-intel as a streamable-HTTP server (unless MM_MCP_URL points at one), moves the match clock forward a
minute at a time, and runs the workflow when something worth saying happens (priority >= 5), when nothing has been
said for 15 minutes, at half-time and at full time. Overlays are printed and written as JSON lines.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from agents import config, roles
from agents.intel_client import IntelClient
from agents.personas import default_personas
from agents.workflow import Trigger, build_workflow

QUIET_MINUTES = 15
TRIGGER_PRIORITY = 5


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_intel_server() -> tuple[str, subprocess.Popen | None]:
    if os.environ.get("MM_MCP_URL"):
        return os.environ["MM_MCP_URL"], None
    port = _free_port()
    proc = subprocess.Popen([sys.executable, "-m", "mcp_server", "--http", "--port", str(port)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.1)
    return f"http://127.0.0.1:{port}/mcp", proc


async def names_for(intel: IntelClient, home: str, away: str) -> dict:
    fx = await intel.call("list_fixtures", round=1)
    team_ids = sorted({f["home_id"] for f in fx["fixtures"]} | {f["away_id"] for f in fx["fixtures"]})
    league, roster, ids = set(), set(), {}
    for tid in team_ids:
        prof = await intel.call("get_team_profile", team_id=tid)
        names = [prof["name"]] + [p["name"] for p in prof["squad"]]
        league |= set(names)
        ids[tid] = prof["name"]
        for p in prof["squad"]:
            ids[p["player_id"]] = p["name"]
        if tid in (home, away):
            roster |= set(names)
    return {"league": league, "roster": roster, "ids": ids}


def show(job, seconds: float) -> None:
    if job.skipped:
        print(f"  [{job.state.get('clock')}] analyst: nothing worth a note ({seconds:.0f} s)")
        return
    steps = " -> ".join(f"{t['step']}:{t['outcome']}" for t in job.trace)
    print(f"\n[{job.state.get('clock')}] {job.trigger.kind}/{job.trigger.reason} ({job.note_source}, {seconds:.0f} s) "
          f"{steps}")
    print(f"  ALL      {job.note}")
    for pid, r in job.persona_notes.items():
        print(f"  {pid[:12]:12s} {r['text']}  <{r['source']}>")
    for (pid, lang), r in job.translations.items():
        print(f"  {pid[:9]:9s}/{lang} {r['text']}  <{r['source']}>")


async def run_match(home: str, away: str, langs: list[str], focus_player: str | None, max_notes: int, step: float,
                    out_dir: Path) -> list:
    url, proc = start_intel_server()
    jobs = []
    try:
        async with IntelClient(url) as intel:
            from agent_framework import MCPStreamableHTTPTool
            state = await intel.call("advance_match", home=home, away=away, to_minute=0)
            mid = state["match_id"]
            h, a = state["home"]["team_id"], state["away"]["team_id"]
            names = await names_for(intel, h, a)
            personas = default_personas(h, a, focus_player)
            analyst_tools = MCPStreamableHTTPTool(name="match_intel", url=url, load_prompts=False,
                                                  allowed_tools=["compare_to_expected", "explain_event",
                                                                 "get_player_card"])
            async with analyst_tools:
                agents = {"analyst": roles.build("analyst", tools=[analyst_tools]),
                          "narrator": roles.build("narrator"), "personaliser": roles.build("personaliser"),
                          "translator": roles.build("translator")}
                wf = build_workflow(intel, agents)
                print(f"{state['home']['name']} v {state['away']['name']} ({mid}) | models: {config.describe()}")
                minute, last_note, seen, pending = 0.0, 0.0, set(), []
                half_time_done = False
                published = 0
                while published < max_notes:
                    minute += step
                    state = await intel.call("advance_match", match_id=mid, to_minute=minute)
                    new = (await intel.call("get_moments", match_id=mid, since_minute=0))["moments"]
                    fresh = [m for m in new if m["moment_id"] not in seen]
                    seen |= {m["moment_id"] for m in fresh}
                    pending += fresh
                    kind = reason = None
                    if state["finished"]:
                        kind, reason = "recap", "full_time"
                    elif state["period"] == 2 and not half_time_done:
                        half_time_done, kind, reason = True, "recap", "half_time"
                    elif any(m["priority"] >= TRIGGER_PRIORITY for m in fresh):
                        kind, reason = "live_note", "moment"
                    elif state["minute"] - last_note >= QUIET_MINUTES:
                        kind, reason = "live_note", "check_in"
                    if kind:
                        trig = Trigger(mid, kind, pending, personas, langs, names, reason)
                        t0 = time.monotonic()
                        res = await wf.run(trig)
                        job = res.get_outputs()[0]
                        show(job, time.monotonic() - t0)
                        jobs.append(job)
                        published += not job.skipped
                        if not job.skipped:
                            pending, last_note = [], state["minute"]
                    if state["finished"]:
                        break
    finally:
        if proc:
            proc.terminate()
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{jobs[0].trigger.match_id if jobs else 'match'}.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for j in jobs:
            f.write(json.dumps({"clock": j.state.get("clock"), "kind": j.trigger.kind, "skipped": j.skipped,
                                "plan": j.plan, "note": j.note, "note_source": j.note_source, "trace": j.trace,
                                "overlays": j.overlays}, default=str) + "\n")
    print(f"\nwrote {path}")
    return jobs


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m agents")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--home", required=True)
    r.add_argument("--away", required=True)
    r.add_argument("--langs", default="es")
    r.add_argument("--focus-player")
    r.add_argument("--max-notes", type=int, default=8)
    r.add_argument("--step", type=float, default=1.0)
    r.add_argument("--out", default="data/notes")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    langs = [x for x in a.langs.split(",") if x]
    asyncio.run(run_match(a.home, a.away, langs, a.focus_player, a.max_notes, a.step, Path(a.out)))


if __name__ == "__main__":
    main()
