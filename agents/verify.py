"""The Verifier: deterministic checks on every piece of generated text before it can be shown.

Code checks, not a second model: a model reviewer flags correct text and misses real errors, while these checks are
exact and explainable. A failed check returns its reasons so the writer can revise once; after that the workflow
falls back to text built from the facts themselves.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_NUM = re.compile(r"(?<![\w.])[-+]?\d+(?:,\d{3})*(?:\.\d+)?%?")
_MINUTE = re.compile(r"(\d{1,3})(?:\+(\d{1,2}))?(?:'|’|(?:st|nd|rd|th)? minute)")
FINAL_WORDS = re.compile(r"\b(won|wins the match|victory|victorious|defeated|beat|clinched|secured (?:the|a) "
                         r"(?:win|victory|three points)|full[- ]time|final score|final whistle|"
                         r"(?:scoreless|goalless) draw|ended (?:in )?(?:a )?draw|(?:will|would) (?:end|finish))\b",
                         re.I)
BANNED = re.compile(r"\b(odds|bet|bets|betting|bookmakers?|wager|accumulator)\b", re.I)
REAL_CLUBS = re.compile(r"\b(Arsenal|Chelsea|Liverpool|Manchester (?:United|City)|Tottenham|Everton|Newcastle|"
                        r"Aston Villa|West Ham|Leicester|Southampton|Brighton|Wolves|Crystal Palace|Brentford|"
                        r"Fulham|Bournemouth|Nottingham Forest|Burnley|Leeds|Sunderland|"
                        r"Premier League(?! Synthetic))\b")
WRONG_SPORT = re.compile(r"\b(touchdown|scrimmage|quarterback|end zone|field goal|innings|wicket)\b", re.I)
PREDICTION = re.compile(r"\b(?:will|(?:is|are|looks?) (?:likely|set|bound) to|(?:probably|surely) (?:will|going to)|"
                        r"going to|should) (?:score|win|equali[sz]e|break the deadlock|come back|hold on|lose)\b|"
                        r"\bgoals? (?:is|are) (?:likely|coming)\b", re.I)
DECORATION = re.compile(r"#\w+|[\U0001F300-\U0001FAFF☀-➿]")
WE = re.compile(r"\b(we|we've|we're|us|our|ours)\b", re.I)
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def _subject_spans(text: str, subjects: list[str]) -> list[tuple[int, str]]:
    """(position, subject) for every team mention in text, plus 'draw' (win-probability lines)."""
    spans = []
    for s in subjects + ["draw"]:
        for m in re.finditer(rf"\b{re.escape(s)}\b", text, re.I):
            spans.append((m.start(), s))
    return sorted(spans)


_PAIRING = re.compile(r"^\s*(?:to|vs\.?|versus|-|–)\s*$", re.I)


def _owners_in(text: str, subjects: list[str], we_team: str | None = None) -> list[tuple[float, bool, int, str | None]]:
    """(value, is_percent, decimals, owner) for each number: the owner is the nearest team named before it, except in
    "A ... 0.55 to 0.12" pairings, where the second number belongs to the other team."""
    out = []
    for sentence in _SENTENCE.split(text):
        spans = _subject_spans(sentence, subjects)
        if we_team:
            spans = sorted(spans + [(m.start(), we_team) for m in WE.finditer(sentence)])
        prev = None
        for m in _NUM.finditer(sentence):
            s = m.group(0)
            body = s.rstrip("%").replace(",", "").lstrip("+")
            owner = next((t for p, t in reversed(spans) if p < m.start()), None)
            if prev and _PAIRING.match(sentence[prev[0]:m.start()]) and prev[1] in subjects and owner == prev[1]:
                others = [t for t in subjects if t != prev[1]]
                owner = others[0] if len(others) == 1 else owner
            out.append((float(body), s.endswith("%"), len(body.split(".")[1]) if "." in body else 0, owner))
            prev = (m.end(), owner)
    return out


def _misattributed(text: str, lines: list[str], subjects: list[str], we_team: str | None) -> list[str]:
    facts = [x for line in lines for x in _owners_in(line, subjects)]
    problems = []
    for v, pct, dec, owner in _owners_in(text, subjects, we_team):
        if (dec == 0 and not pct and abs(v) <= 10) or not owner or owner == "draw":
            continue            # scores and small counts are too ambiguous to attribute
        owners = {o for fv, fp, _, o in facts if fp == pct and round(fv, dec) == v}
        if owners and None not in owners and owner not in owners:
            shown = f"{v:g}{'%' if pct else ''}"
            problems.append(f"gives {shown} to {owner}, but the facts give it to {' / '.join(sorted(owners))}")
    return problems


DIRECTIONS = ("well above their usual", "above their usual", "about their usual", "below their usual",
              "well below their usual")


@dataclass
class Verdict:
    ok: bool
    problems: list[str] = field(default_factory=list)
    numbers_checked: int = 0

    def as_dict(self) -> dict:
        return {"ok": self.ok, "problems": self.problems, "numbers_checked": self.numbers_checked}


def _numbers(text: str) -> list[tuple[str, float, int, bool]]:
    out = []
    for m in _NUM.finditer(text):
        s = m.group(0)
        body = s.rstrip("%").replace(",", "").lstrip("+")
        out.append((s, float(body), len(body.split(".")[1]) if "." in body else 0, s.endswith("%")))
    return out


def _fact_values(facts_text: str) -> list[tuple[float, int]]:
    """Every fact number with its own precision, also as a percentage / fraction (0.42 <-> 42%)."""
    out = []
    for _, v, dec, pct in _numbers(facts_text):
        out += [(v, dec), (-v, dec)]
        out += [(v / 100, dec + 2)] if pct else [(v * 100, max(0, dec - 2))]
    return out


def _supported(v: float, dec: int, facts: list[tuple[float, int]]) -> bool:
    """A text number is supported if some fact rounds to it at the text's precision, or (when the fact is more
    precise) sits within one unit of it."""
    for f, fdec in facts:
        if abs(round(f, dec) - v) < 1e-9:
            return True
        if fdec > dec and abs(f - v) <= 10 ** -dec + 1e-9:
            return True
    return False


def check(text: str, facts_lines: list[str], *, roster: set[str], league_names: set[str], minute_now: float,
          finished: bool, max_words: int, language: str = "en", teams: list[str] | None = None,
          we_team: str | None = None) -> Verdict:
    """facts_lines: the fact-sheet sentences the text was written from. roster: player and club names in this match.
    league_names: every player and club name in the league (to catch names from other matches). teams: the two club
    names, for the attribution check; we_team: the club a fan persona's "we" means."""
    problems: list[str] = []
    facts = " ".join(facts_lines)
    values = _fact_values(facts)
    # numbers: each must come from the facts, at the text's own precision
    nums = _numbers(text)
    for s_, v, dec, _ in nums:
        if v in (45, 90) and dec == 0:
            continue
        if not _supported(v, dec, values):
            problems.append(f"number {s_} is not in the facts")
    # minutes: nothing from the future
    for m in _MINUTE.finditer(text):
        base, extra = int(m.group(1)), int(m.group(2) or 0)
        if base > 120:
            continue
        if base + extra > minute_now + 1.5:
            problems.append(f"mentions minute {m.group(0)}, but it is only {minute_now:.0f}'")
    # names: no players or clubs from outside this match
    for name in league_names - roster:
        if len(name) > 4 and re.search(rf"\b{re.escape(name)}\b", text):
            problems.append(f"names {name}, who is not in this match")
    if not finished and language == "en" and FINAL_WORDS.search(text):
        problems.append(f"talks about a final result ('{FINAL_WORDS.search(text).group(0)}') but the match is "
                        f"still going")
    if BANNED.search(text):
        problems.append("mentions betting")
    if REAL_CLUBS.search(text):
        problems.append(f"mentions a real club or competition ({REAL_CLUBS.search(text).group(0)}); this league is "
                        f"fictional")
    if language == "en" and teams:
        problems += _misattributed(text, facts_lines, teams, we_team)
    if language == "en" and PREDICTION.search(text):
        problems.append(f"predicts what will happen ('{PREDICTION.search(text).group(0)}'); report, don't forecast")
    if DECORATION.search(text):
        problems.append("uses hashtags or emoji")
    if WRONG_SPORT.search(text):
        problems.append(f"uses another sport's vocabulary ('{WRONG_SPORT.search(text).group(0)}')")
    # comparisons: a stated direction vs "usual" must match a fact line that says the same
    for d in DIRECTIONS:
        if language == "en" and d in text.lower() and d not in facts.lower():
            problems.append(f"says '{d}' but no fact says that")
    words = len(text.split())
    if words > max_words:
        problems.append(f"too long ({words} words, limit {max_words})")
    if not text.strip():
        problems.append("empty")
    return Verdict(not problems, problems, len(nums))


def numbers_preserved(source: str, translated: str) -> list[str]:
    """For translations: the same numbers must survive (allowing a decimal comma)."""
    src = sorted(round(v, 3) for _, v, _, _ in _numbers(source))
    out = sorted(round(v, 3) for _, v, _, _ in _numbers(translated.replace(",", ".")))
    missing = [str(x) for x in src if x not in out]
    extra = [str(x) for x in out if x not in src]
    return ([f"lost number(s) {', '.join(missing)}"] if missing else []) + \
        ([f"added number(s) {', '.join(extra)}"] if extra else [])
