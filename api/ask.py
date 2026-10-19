"""Ask about this view: a viewer's question, answered only from the facts behind what is on their screen.

The view (tab, team, player) decides which fact sheets are sent; the answer is verified like any note, retried once,
and otherwise replaced by the most relevant fact lines. The response includes exactly what was sent to the model.
"""
from __future__ import annotations

import asyncio
import re

from pydantic import BaseModel, Field

from agents import verify
from agents.config import chat_client
from agents.personas import LANGUAGES
from agents.roles import SPORT, Translation

MAX_WORDS = 70


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=300)
    tab: str = "broadcast"
    team_id: str | None = None
    player_id: str | None = None
    persona: str = "casual"
    lang: str = "en"


class Answer(BaseModel):
    answerable: bool = Field(description="false if the facts do not contain the answer")
    answer: str
    used_keys: list[str] = Field(default_factory=list)


ANSWERER = f"""You are MatchMind's match assistant, answering a viewer's question about what is on their screen. {SPORT}
Rules:
- Answer ONLY from the facts given, in at most {MAX_WORDS} words. Every number must appear in the facts as written.
- If the facts do not answer the question, set answerable to false and say briefly what the screen can tell them
  instead. Never guess, and never invent statistics we do not have.
- The match may be in progress: no final results, no forecasts.
- Match the viewer's style: {{style}}
Reply with JSON."""

STYLE = {"casual": "plain words, no jargon", "analyst": "precise, metrics welcome"}


def context_lines(tools, match_id: str, req: AskRequest) -> list[dict]:
    lines = [{**x, "key": f"match.{x['key']}"} for x in
             tools.get_fact_sheet(match_id=match_id, scope="match")["lines"]]
    if req.team_id:
        lines += [{**x, "key": f"team.{x['key']}"} for x in
                  tools.get_fact_sheet(match_id=match_id, scope="team", subject_id=req.team_id)["lines"]]
    if req.player_id:
        lines += [{**x, "key": f"player.{x['key']}"} for x in
                  tools.get_fact_sheet(match_id=match_id, scope="player", subject_id=req.player_id)["lines"]]
    seen, out = set(), []
    for x in lines:
        if x["text"] not in seen:
            seen.add(x["text"])
            out.append(x)
    return out


def _relevant(question: str, lines: list[dict], n: int = 2) -> list[str]:
    words = {w for w in re.findall(r"[a-z]{3,}", question.lower())}
    scored = sorted(lines, key=lambda x: -len(words & set(re.findall(r"[a-z]{3,}", x["text"].lower()))))
    return [x["text"] for x in scored[:n]]


async def answer(req: AskRequest, lines: list[dict], state: dict, names: dict, agents_on: bool) -> dict:
    teams = [state["home"]["name"], state["away"]["name"]]
    texts = [x["text"] for x in lines]

    def check(text: str, language: str = "en") -> verify.Verdict:
        return verify.check(text, texts, roster=names["roster"], league_names=names["league"],
                            minute_now=state.get("minute", 0.0), finished=state.get("finished", False),
                            max_words=MAX_WORDS, language=language, teams=teams)

    facts_block = "\n".join(f"[{x['key']}] {x['text']}" for x in lines)
    result = {"source": "fallback", "verified": True, "context_sent": texts, "problems": []}
    text = None
    if agents_on:
        from agent_framework import Agent
        agent = Agent(chat_client("narrator"), name="ask",
                      instructions=ANSWERER.replace("{style}", STYLE.get(req.persona, "friendly and clear")))
        problems: list[str] = []
        for attempt in (1, 2):
            prompt = f"Clock: {state.get('clock')}. Facts:\n{facts_block}\n\nViewer's question: {req.question}"
            if problems:
                prompt += "\n\nYour previous answer was rejected for: " + "; ".join(problems) + ". Answer again."
            try:
                resp = await asyncio.wait_for(agent.run(prompt, options={"response_format": Answer,
                                                                         "temperature": 0.2}), timeout=60)
                ans = resp.value or Answer.model_validate_json(resp.text)
            except Exception as e:
                problems = [f"model error: {str(e)[:100]}"]
                continue
            v = check(ans.answer)
            if v.ok:
                text = ans.answer
                result.update(source="assistant", answerable=ans.answerable, attempts=attempt)
                break
            problems = v.problems
        result["problems"] = problems if text is None else []
    if text is None:
        rel = _relevant(req.question, lines)
        text = "Here is what the data on this screen shows: " + " ".join(rel)
        result["answerable"] = False
    if req.lang != "en" and agents_on:
        from agents.roles import build
        try:
            tr = build("translator")
            resp = await asyncio.wait_for(tr.run(f"Translate into {LANGUAGES.get(req.lang, req.lang)}. The text field "
                                                 f"must hold only the translation.\nText: {text}",
                                                 options={"response_format": Translation}), timeout=60)
            translated = (resp.value or Translation.model_validate_json(resp.text)).text
            if not verify.numbers_preserved(text, translated):
                result["answer_en"], text = text, translated
                result["lang"] = req.lang
        except Exception:
            pass
    result["answer"] = text
    result.setdefault("lang", "en")
    return result
