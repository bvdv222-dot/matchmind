"""The MatchMind note workflow (Microsoft Agent Framework graph).

    Gather -> Analyst -> Facts -> Narrator -> Verifier --ok--> Personaliser -> Translator -> Publish
                 |                    ^          |  \\--fail, 1st time--> Narrator (with the problems)
                 |                    |          \\--fail again---------> Fallback (text built from the facts)
                 \\--nothing worth saying----------------------------------------------------------> Publish

Shared state is the Job: each step reads what earlier steps wrote and adds its own part, plus a trace entry (who,
how long, outcome, problems). Every model step has a fallback, so a slow or failing model degrades the wording,
never the accuracy: whatever is published has passed the Verifier or was built from the facts.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field

from agent_framework import Case, Default, Executor, WorkflowBuilder, WorkflowContext, handler

from agents import verify
from agents.personas import LANGUAGES, Persona
from agents.roles import Note, PersonaText, StoryPlan, Translation

NOTE_WORDS = {"live_note": 45, "recap": 120}
FORCE_PRIORITY = 7          # goals, red cards and penalties always get a note; the Analyst still picks the angle
MAX_ATTEMPTS = 2


@dataclass
class Trigger:
    match_id: str
    kind: str                         # live_note | recap
    moments: list[dict]               # new moments since the last note (from get_moments)
    personas: list[Persona]
    languages: list[str]
    names: dict                       # {"roster": set, "league": set, "ids": {id: name}}
    reason: str = "moment"            # moment | check_in (nothing said for a while) | half_time | full_time


@dataclass
class Job:
    trigger: Trigger
    state: dict = field(default_factory=dict)
    match_lines: list[dict] = field(default_factory=list)
    plan: dict = field(default_factory=dict)
    facts: list[dict] = field(default_factory=list)
    note: str = ""
    note_source: str = ""
    attempts: int = 0
    problems: list[str] = field(default_factory=list)
    verdict: dict = field(default_factory=dict)
    persona_notes: dict = field(default_factory=dict)
    translations: dict = field(default_factory=dict)
    overlays: list[dict] = field(default_factory=list)
    trace: list[dict] = field(default_factory=list)
    skipped: bool = False

    def log(self, step: str, t0: float, outcome: str, **extra) -> None:
        self.trace.append({"step": step, "ms": round(1000 * (time.monotonic() - t0)), "outcome": outcome, **extra})

    def fact_texts(self) -> list[str]:
        return [f["text"] for f in self.facts]

    def check(self, text: str, max_words: int, language: str = "en", we_team: str | None = None) -> verify.Verdict:
        st = self.state
        teams = [st["home"]["name"], st["away"]["name"]] if st else None
        return verify.check(text, self.fact_texts(), roster=self.trigger.names["roster"],
                            league_names=self.trigger.names["league"], minute_now=st.get("minute", 0.0),
                            finished=st.get("finished", False), max_words=max_words, language=language,
                            teams=teams, we_team=we_team)


def _facts_block(lines: list[dict]) -> str:
    return "\n".join(f"[{f['key']}] {f['text']}" for f in lines)


async def _ask(agent, prompt: str, schema, timeout: float = 90.0):
    resp = await asyncio.wait_for(agent.run(prompt, options={"response_format": schema, "temperature": 0.3}),
                                  timeout=timeout)
    value = resp.value
    if value is None:                 # some local models return JSON as plain text
        value = schema.model_validate(json.loads(resp.text))
    return value


# ------------------------------------------------------------------ executors

class Gather(Executor):
    def __init__(self, intel):
        super().__init__(id="gather")
        self.intel = intel

    @handler
    async def run(self, trig: Trigger, ctx: WorkflowContext[Job]) -> None:
        t0 = time.monotonic()
        job = Job(trig)
        job.state = await self.intel.call("get_match_state", match_id=trig.match_id)
        sheet = await self.intel.call("get_fact_sheet", match_id=trig.match_id, scope="match")
        job.match_lines = sheet["lines"]
        job.log("gather", t0, "ok", moments=len(trig.moments))
        await ctx.send_message(job)


class Analyst(Executor):
    def __init__(self, agent):
        super().__init__(id="analyst")
        self.agent = agent

    def fallback_plan(self, job: Job) -> StoryPlan:
        ms = sorted(job.trigger.moments, key=lambda m: (-m["priority"], -m["minute"]))
        if job.trigger.kind == "recap":
            return StoryPlan(publish=True, angle="How the match has gone so far and why", importance=4)
        if job.trigger.reason == "check_in":
            return StoryPlan(publish=True, angle="The state of play: who is on top and what the numbers say",
                             importance=2)
        if not ms or ms[0]["priority"] < 5:
            return StoryPlan(publish=False)
        m = ms[0]
        return StoryPlan(publish=True, moment_id=m["moment_id"], angle=m["headline"], focus_team_id=m.get("team_id"),
                         importance=min(5, max(1, m["priority"] // 2)))

    @handler
    async def run(self, job: Job, ctx: WorkflowContext[Job]) -> None:
        t0 = time.monotonic()
        trig = job.trigger
        moments = [{k: m.get(k) for k in ("moment_id", "kind", "priority", "clock", "team_id", "player_ids",
                                          "headline")} for m in trig.moments]
        must = " A note is due (nothing has been said for a while): set publish to true and pick the state of play " \
               "or the most telling moment." if trig.reason == "check_in" else ""
        if any(m["priority"] >= FORCE_PRIORITY for m in trig.moments):
            must += " A goal, red card or penalty is among the moments: publish a note about it."
        prompt = (f"Note type: {trig.kind}.{must} Match {trig.match_id} at {job.state.get('clock')}.\n"
                  f"Match facts:\n{_facts_block(job.match_lines[:8])}\n\nNew moments:\n{json.dumps(moments)}")
        ids = {m["moment_id"] for m in trig.moments}
        try:
            plan = await _ask(self.agent, prompt, StoryPlan)
            if plan.moment_id and plan.moment_id not in ids:
                raise ValueError(f"unknown moment {plan.moment_id}")
            must = trig.kind == "recap" or trig.reason == "check_in" or \
                any(m["priority"] >= FORCE_PRIORITY for m in trig.moments)
            if must and not plan.publish:
                plan = self.fallback_plan(job) if not plan.angle else plan
                plan.publish = True
            job.log("analyst", t0, "ok", publish=plan.publish)
        except Exception as e:     # a slow or confused model must not stop the broadcast
            plan = self.fallback_plan(job)
            job.log("analyst", t0, "fallback", error=str(e)[:200])
        job.plan = plan.model_dump()
        job.skipped = not plan.publish
        await ctx.send_message(job)


class Facts(Executor):
    def __init__(self, intel):
        super().__init__(id="facts")
        self.intel = intel

    @handler
    async def run(self, job: Job, ctx: WorkflowContext[Job]) -> None:
        t0 = time.monotonic()
        p, mid = job.plan, job.trigger.match_id
        lines: list[dict] = []
        if p.get("moment_id"):
            s = await self.intel.call("get_fact_sheet", match_id=mid, scope="moment", subject_id=p["moment_id"])
            lines += [{**x, "key": f"moment.{x['key']}"} for x in s["lines"]]
        for scope, sid in (("team", p.get("focus_team_id")), ("player", p.get("focus_player_id"))):
            if sid:
                try:
                    s = await self.intel.call("get_fact_sheet", match_id=mid, scope=scope, subject_id=sid)
                    lines += [{**x, "key": f"{scope}.{x['key']}"} for x in s["lines"][:6]]
                except Exception:
                    pass
        n_match = 30 if job.trigger.kind == "recap" else 8
        lines += [{**x, "key": f"match.{x['key']}"} for x in job.match_lines[:n_match]]
        seen, job.facts = set(), []
        for x in lines:
            if x["text"] not in seen:
                seen.add(x["text"])
                job.facts.append(x)
        job.log("facts", t0, "ok", lines=len(job.facts))
        await ctx.send_message(job)


class Narrator(Executor):
    def __init__(self, agent):
        super().__init__(id="narrator")
        self.agent = agent

    @handler
    async def run(self, job: Job, ctx: WorkflowContext[Job]) -> None:
        t0 = time.monotonic()
        job.attempts += 1
        limit = NOTE_WORDS[job.trigger.kind]
        prompt = (f"Write a {job.trigger.kind.replace('_', ' ')} of at most {limit} words.\n"
                  f"Angle: {job.plan.get('angle')}\nMatch clock: {job.state.get('clock')}"
                  f"{' (full time)' if job.state.get('finished') else ' (match in progress)'}\n"
                  f"Facts:\n{_facts_block(job.facts)}")
        if job.problems:
            prompt += "\n\nYour previous draft was rejected by the Verifier for:\n- " + "\n- ".join(job.problems) + \
                      "\nFix every problem."
        try:
            note = await _ask(self.agent, prompt, Note)
            job.note, job.note_source = note.text.strip(), "narrator"
            job.log("narrator", t0, "ok", attempt=job.attempts)
        except Exception as e:
            job.note, job.note_source = "", "narrator-error"
            job.log("narrator", t0, "error", attempt=job.attempts, error=str(e)[:200])
        await ctx.send_message(job)


class Verifier(Executor):
    def __init__(self):
        super().__init__(id="verifier")

    @handler
    async def run(self, job: Job, ctx: WorkflowContext[Job]) -> None:
        t0 = time.monotonic()
        v = job.check(job.note, NOTE_WORDS[job.trigger.kind])
        job.verdict, job.problems = v.as_dict(), v.problems
        job.log("verifier", t0, "pass" if v.ok else "reject", problems=v.problems, attempt=job.attempts)
        await ctx.send_message(job)


class Fallback(Executor):
    """Builds the note from fact lines directly: always accurate, plainer to read."""

    def __init__(self):
        super().__init__(id="fallback")

    @handler
    async def run(self, job: Job, ctx: WorkflowContext[Job]) -> None:
        t0 = time.monotonic()
        keys = ["moment.headline", "moment.swing", "match.score"] if job.plan.get("moment_id") else \
            ["match.score", "match.xg", "match.momentum", "match.win_probability"]
        by_key = {f["key"]: f["text"] for f in job.facts}
        job.note = " ".join(by_key[k] for k in keys if k in by_key) or job.facts[0]["text"]
        job.note_source = "fallback"
        job.verdict = job.check(job.note, 10_000).as_dict()
        job.log("fallback", t0, "ok", replaced_problems=job.problems)
        await ctx.send_message(job)


class Personaliser(Executor):
    def __init__(self, agent):
        super().__init__(id="personaliser")
        self.agent = agent

    async def one(self, job: Job, p: Persona, names: dict) -> tuple[str, dict]:
        style = p.style.format(club=names.get(p.club_id, ""), player=names.get(p.player_id, ""))
        limit = p.max_words * (3 if job.trigger.kind == "recap" else 1)
        live = "full time" if job.state.get("finished") else f"in progress, {job.state.get('clock')}"
        base = (f"Viewer: {p.label}. Style: {style}\nAt most {limit} words. Match: {live}.\n"
                f"Verified note: {job.note}\n"
                f"Facts:\n{_facts_block(job.facts)}")
        problems: list[str] = []
        for attempt in (1, 2):
            prompt = base + ("\n\nRejected for:\n- " + "\n- ".join(problems) + "\nFix them." if problems else "")
            try:
                text = (await _ask(self.agent, prompt, PersonaText)).text.strip()
            except Exception as e:
                problems = [f"model error: {str(e)[:120]}"]
                continue
            v = job.check(text, limit, we_team=names.get(p.club_id))
            if v.ok:
                return p.persona_id, {"text": text, "source": "personaliser", "attempts": attempt}
            problems = v.problems
        return p.persona_id, {"text": job.note, "source": "fallback", "problems": problems}

    @handler
    async def run(self, job: Job, ctx: WorkflowContext[Job]) -> None:
        t0 = time.monotonic()
        names = {self_id: name for self_id, name in job.trigger.names.get("ids", {}).items()}
        results = await asyncio.gather(*(self.one(job, p, names) for p in job.trigger.personas))
        job.persona_notes = dict(results)
        job.log("personaliser", t0, "ok", fallbacks=sum(r["source"] == "fallback" for _, r in results))
        await ctx.send_message(job)


class Translator(Executor):
    def __init__(self, agent):
        super().__init__(id="translator")
        self.agent = agent

    async def one(self, job: Job, pid: str, lang: str) -> tuple[tuple[str, str], dict]:
        src = job.persona_notes[pid]["text"]
        problems: list[str] = []
        for attempt in (1, 2):
            language = LANGUAGES.get(lang, lang)
            prompt = f"Translate into {language}. The text field must hold only the translation.\nText: {src}"
            if problems:
                prompt += ("\n\nA previous translation was rejected (" + "; ".join(problems) + "). Translate again; "
                           "do not mention the rejection.")
            try:
                text = (await _ask(self.agent, prompt, Translation)).text.strip()
            except Exception as e:
                problems = [f"model error: {str(e)[:120]}"]
                continue
            problems = verify.numbers_preserved(src, text)
            other = job.check(text, 10_000, language=lang).problems
            problems += [p for p in other if "number" not in p]       # numbers are checked against the source
            ratio = len(text) / max(1, len(src))
            if not 0.5 <= ratio <= 1.7:      # something appended or dropped (Japanese / Arabic are shorter in chars)
                if lang not in ("ja", "ar") or ratio > 1.7:
                    problems.append(f"length is {ratio:.1f}x the original")
            if not problems:
                return (pid, lang), {"text": text, "source": "translator", "attempts": attempt}
        return (pid, lang), {"text": src, "source": "fallback-english", "problems": problems}

    @handler
    async def run(self, job: Job, ctx: WorkflowContext[Job]) -> None:
        t0 = time.monotonic()
        langs = [lang for lang in job.trigger.languages if lang != "en"]
        tasks = [self.one(job, pid, lang) for pid in job.persona_notes for lang in langs]
        job.translations = dict(await asyncio.gather(*tasks)) if tasks else {}
        failed = {f"{pid}/{lang}": r.get("problems") for (pid, lang), r in job.translations.items()
                  if r["source"] != "translator"}
        job.log("translator", t0, "ok", count=len(tasks), fallbacks=failed)
        await ctx.send_message(job)


class Publish(Executor):
    def __init__(self):
        super().__init__(id="publish")

    @handler
    async def run(self, job: Job, ctx: WorkflowContext[None, Job]) -> None:
        if not job.skipped:
            st = job.state
            at = {"period": st.get("period", 1), "t": round(60 * (st.get("minute", 0.0) - (45 if st.get("period") == 2
                                                                                        else 0)), 1),
                  "clock": st.get("clock", "")}
            kind = "recap" if job.trigger.kind == "recap" else "narrative"
            moment = job.plan.get("moment_id")
            base = {"match_id": job.trigger.match_id, "kind": kind, "at": at,
                    "ttl_s": 25.0 if kind == "narrative" else 60.0, "priority": job.plan.get("importance", 3) + 3,
                    "source_event_ids": [m for m in [moment] if m], "verified": True,
                    "data": {"angle": job.plan.get("angle"), "note_source": job.note_source}}
            n = 0

            def add(audience: str, lang: str, text: str, source: str) -> None:
                nonlocal n
                job.overlays.append({**base, "msg_id": f"{job.trigger.match_id}-{at['clock']}-{n}",
                                     "audience": [audience], "lang": lang, "body": text,
                                     "data": {**base["data"], "text_source": source}})
                n += 1

            add("all", "en", job.note, job.note_source)
            for pid, r in job.persona_notes.items():
                add(pid, "en", r["text"], r["source"])
            for (pid, lang), r in job.translations.items():
                add(pid, lang if r["source"] == "translator" else "en", r["text"], r["source"])
        await ctx.yield_output(job)


def build_workflow(intel, agents: dict):
    gather, analyst = Gather(intel), Analyst(agents["analyst"])
    facts, narrator, verifier = Facts(intel), Narrator(agents["narrator"]), Verifier()
    fallback, personaliser = Fallback(), Personaliser(agents["personaliser"])
    translator, publish = Translator(agents["translator"]), Publish()
    return (WorkflowBuilder(name="matchmind-notes", start_executor=gather, max_iterations=40)
            .add_edge(gather, analyst)
            .add_switch_case_edge_group(analyst, [Case(condition=lambda j: j.skipped, target=publish),
                                                  Default(target=facts)])
            .add_edge(facts, narrator)
            .add_edge(narrator, verifier)
            .add_switch_case_edge_group(verifier, [
                Case(condition=lambda j: j.verdict.get("ok", False), target=personaliser),
                Case(condition=lambda j: j.attempts < MAX_ATTEMPTS, target=narrator),
                Default(target=fallback)])
            .add_edge(fallback, personaliser)
            .add_edge(personaliser, translator)
            .add_edge(translator, publish)
            .build())
