"""Fact sheets: the only material the narrative agents may write from.

Each sheet is a list of short, deterministic lines. Every number is already rendered and every comparison is
already in words (direction, size, standing), because a language model misreads raw ranks and small differences.
The Verifier checks generated text against the numbers in these lines.
"""
from __future__ import annotations

import re

from intel import flow
from intel.common import ordinal
from intel.live import LiveMatch

METRIC_WORDS = {
    "xg": ("xG", "{:.2f}"), "shots": ("shots", "{:.0f}"), "passes": ("passes", "{:.0f}"),
    "pass_completion": ("pass completion", "{:.0%}"), "possession_share": ("possession", "{:.0%}"),
    "field_tilt": ("field tilt (share of final-third passes)", "{:.0%}"),
    "progressive_passes": ("progressive passes", "{:.0f}"), "ppda": ("PPDA (passes allowed per defensive action)",
                                                                     "{:.1f}"),
    "pressures": ("pressures", "{:.0f}"), "crosses": ("crosses", "{:.0f}"), "big_chances": ("big chances", "{:.0f}"),
    "long_ball_share": ("long-ball share", "{:.0%}"), "take_ons": ("take-ons", "{:.0f}"),
    "corners": ("corners", "{:.0f}"),
}
HEADLINE_METRICS = ("xg", "possession_share", "field_tilt", "ppda", "shots")
COUNTS = {"shots", "passes", "progressive_passes", "pressures", "crosses", "big_chances", "take_ons", "corners"}


def plural(n: float, word: str) -> str:
    return f"{n:g} {word}" if n == 1 else f"{n:g} {word}s"


def _fmt(metric: str, v: float) -> str:
    return METRIC_WORDS[metric][1].format(v)


def _line(key: str, text: str) -> dict:
    return {"key": key, "text": text}


def _pct(x: float) -> str:
    return f"{round(100 * x)}%"


def _sheet(lm: LiveMatch, scope: str, lines: list[dict], data: dict, subject: str | None = None) -> dict:
    return {"scope": scope, "subject": subject, "match_id": lm.match_id, "as_of": {"clock": lm.clock(),
            "minute": round(lm.minute(), 2)}, "lines": lines, "data": data}


def match_lines(lm: LiveMatch) -> list[dict]:
    st = lm.state()
    h, a = st["home"], st["away"]
    hn, an = h["name"], a["name"]
    lines = [_line("score", f"{hn} {h['goals']}-{a['goals']} {an} at {st['clock']}.")]
    hs, as_ = flow.team_stats(lm.events, lm.home), flow.team_stats(lm.events, lm.away)
    lines.append(_line("xg", f"xG: {hn} {hs['xg']:.2f}, {an} {as_['xg']:.2f}."))
    diff = hs["xg"] - as_["xg"]
    if abs(diff) >= 0.3:
        lead = hn if diff > 0 else an
        lines.append(_line("chances", f"{lead} have created the better chances so far."))
    lines.append(_line("shots", f"Shots: {hn} {hs['shots']} ({hs['shots_on_target']} on target), "
                                f"{an} {as_['shots']} ({as_['shots_on_target']} on target)."))
    lines.append(_line("possession", f"Possession: {hn} {_pct(hs['possession_share'])}, "
                                     f"{an} {_pct(as_['possession_share'])}."))
    lines.append(_line("field_tilt", f"Field tilt: {hn} {_pct(hs['field_tilt'])} of final-third passes, "
                                     f"{an} {_pct(as_['field_tilt'])}."))
    wp = st["win_probability"]
    lines.append(_line("win_probability", f"Win probability: {hn} {_pct(wp['home'])}, draw {_pct(wp['draw'])}, "
                                          f"{an} {_pct(wp['away'])}."))
    pre = lm.winprob_history[0] if lm.winprob_history else None
    if pre:
        lines.append(_line("win_probability_start",
                           f"At kick-off it was {hn} {_pct(pre['home'])}, draw {_pct(pre['draw'])}, "
                           f"{an} {_pct(pre['away'])}."))
    win = lm.windows()
    if win:
        mom = flow.momentum(win)
        if mom["side"] == "neither":
            lines.append(_line("momentum", "Neither side has been on top over the last 10 minutes."))
        else:
            team = hn if mom["side"] == "home" else an
            tilt = mom["home_field_tilt"] if mom["side"] == "home" else 1 - mom["home_field_tilt"]
            lines.append(_line("momentum", f"{team} have been on top over the last 10 minutes "
                                           f"({_pct(tilt)} of final-third passes)."))
        label = flow.rhythm_label(win[-1]["chaos_index"])
        lines.append(_line("rhythm", f"The last five minutes have been {label} "
                                     f"(chaos index {win[-1]['chaos_index']:.2f}, where 1.00 is a typical match)."))
    for tid, name in ((lm.home, hn), (lm.away, an)):
        att = lm.team_view(tid)["attack_standing"]
        best = f"{ordinal(att['rank'])}-best"
        lines.append(_line(f"standing_{tid}", f"{name} came in with the {best} attack of the {att['of']} clubs on "
                                              f"last season's chance creation ({att['band']})."))
    return lines


def expectation_lines(lm: LiveMatch, team_id: str, metrics=HEADLINE_METRICS) -> list[dict]:
    tv = lm.team_view(team_id)
    name = tv["name"]
    out = []
    for m in metrics:
        c = tv["vs_expected"][m]
        label = METRIC_WORDS[m][0]
        verdict = " (good for them)" if c["good_for_team"] else (" (a concern for them)" if c["concern"] else "")
        if m == "ppda":
            verdict += "; lower means more intense pressing"
        if m in COUNTS:
            text = (f"{name} have {_fmt(m, c['actual'])} {label}, {c['words']} at this stage "
                    f"(expected {_fmt(m, c['expected'])}){verdict}.")
        else:
            text = (f"{name}'s {label} is {_fmt(m, c['actual'])}, {c['words']} at this stage "
                    f"(expected {_fmt(m, c['expected'])}){verdict}.")
        out.append(_line(f"expect_{team_id}_{m}", text))
    return out


def match_sheet(lm: LiveMatch) -> dict:
    lines = match_lines(lm)
    lines += expectation_lines(lm, lm.home) + expectation_lines(lm, lm.away)
    for i, p in enumerate(lm.top_players(n=3), start=1):
        rank = "Most valuable player so far" if i == 1 else f"{ordinal(i)} most valuable so far"
        lines.append(_line(f"top_player_{i}", f"{rank}: {p['name']} ({p['team']}), {p['value_added']:+.2f} goals "
                                              f"of possession value added."))
    recent = [m for m in lm.moments if m["priority"] >= 5][-3:]
    for m in recent:
        lines.append(_line(f"recent_{m['moment_id']}", f"Recent moment ({m['clock']}): {headline(lm, m)}"))
    return _sheet(lm, "match", lines, {"state": lm.state(), "moments": recent})


def team_sheet(lm: LiveMatch, team_id: str) -> dict:
    tv = lm.team_view(team_id)
    name, s = tv["name"], tv["stats"]
    lines = [_line("summary", f"{name}: {plural(s['goals'], 'goal')} from {plural(s['shots'], 'shot')} worth "
                              f"{s['xg']:.2f} xG ({plural(s['big_chances'], 'big chance')}), "
                              f"{_pct(s['possession_share'])} possession, "
                              f"{_pct(s['pass_completion'])} pass completion.")]
    lines += expectation_lines(lm, team_id, tuple(METRIC_WORDS))
    ph = tv["phases"]
    best = max(ph, key=lambda k: ph[k]["xg"])
    if ph[best]["xg"] > 0:
        lines.append(_line("phases", f"Most of {name}'s xG has come from {best} possessions "
                                     f"({ph[best]['xg']:.2f} xG from {ph[best]['count']})."))
    net = tv["network"]
    if net["hub"]["player_id"]:
        lines.append(_line("hub", f"{lm.name(net['hub']['player_id'])} is the hub of {name}'s passing, involved in "
                                  f"{_pct(net['hub']['share'])} of completed passes."))
    if net["top_pair"]["players"][0]:
        a, b = net["top_pair"]["players"]
        lines.append(_line("pair", f"{name}'s busiest passing pair: {lm.name(a)} and {lm.name(b)} "
                                   f"({net['top_pair']['passes']} passes between them)."))
    for i, p in enumerate(lm.top_players(team_id, n=3), start=1):
        lines.append(_line(f"top_player_{i}", f"{p['name']}: {p['value_added']:+.2f} goals of possession value."))
    return _sheet(lm, "team", lines, tv, subject=team_id)


def player_sheet(lm: LiveMatch, pid: str) -> dict:
    pv = lm.player_view(pid)
    m, ph = pv["match"], pv["physical"]
    name = pv["name"]
    lines = [_line("bio", f"{name} ({pv['team']}), {pv['position']}, number {pv['shirt']}, age {pv['age']}, "
                          f"{pv['foot']}-footed, {pv['height_cm']} cm.")]
    if m.get("passes"):
        lines.append(_line("passing", f"{name} has completed {m.get('passes_complete', 0)} of {m['passes']} passes "
                                      f"({_pct(m['pass_completion'])}), {m.get('progressive_passes', 0)} of them "
                                      f"progressive and {m.get('key_passes', 0)} leading to a shot."))
    if m.get("shots"):
        lines.append(_line("shooting", f"{name}: {plural(m.get('goals', 0), 'goal')} from "
                                       f"{plural(m['shots'], 'shot')} ({m.get('xg', 0):.2f} xG)."))
    if m.get("take_ons"):
        lines.append(_line("dribbling", f"{name} has won {m.get('take_ons_won', 0)} of {m['take_ons']} take-ons."))
    if m.get("tackles_won") or m.get("interceptions"):
        lines.append(_line("defending", f"{name}: {m.get('tackles_won', 0)} tackles won, "
                                        f"{m.get('interceptions', 0)} interceptions."))
    if "value_added" in m:
        lines.append(_line("value", f"{name} has added {m['value_added']:+.2f} goals of possession value."))
    if ph:
        lines.append(_line("physical", f"{name} has covered {ph['distance_m'] / 1000:.1f} km with "
                                       f"{ph['sprints']} sprints and a top speed of {ph['top_speed_kmh']:.1f} km/h."))
    if not pv["on_pitch"]:
        lines.append(_line("status", f"{name} is no longer on the pitch."))
    return _sheet(lm, "player", lines, pv, subject=pid)


def headline(lm: LiveMatch, m: dict) -> str:
    """One deterministic sentence for a moment (also the Verifier's fallback text)."""
    team = lm.team_name.get(m.get("team_id"), "")
    k = m["kind"]
    if k in ("goal", "brace", "hat_trick"):
        extra = {"brace": " - a second goal of the match", "hat_trick": " - a hat-trick"}.get(k, "")
        s = m["score"]
        return (f"{m['scorer']} scores for {team} ({m['chance']}, {m['xg']:.2f} xG){extra}: "
                f"{lm.team_name[lm.home]} {s[0]}-{s[1]} {lm.team_name[lm.away]}.")
    if k == "big_chance_missed":
        return f"{lm.name(m['player_ids'][0])} misses {m['chance']} for {team} ({m['xg']:.2f} xG)."
    if k == "big_save":
        return f"{lm.name(m['player_ids'][0])} saves from {m['shooter']} ({m['xg_faced']:.2f} xG)."
    if k == "red_card":
        return f"{m['player']} is sent off for {team}."
    if k == "penalty":
        return f"Penalty to {team}: {m['taker']} steps up."
    if k == "tactical_shift":
        return m["text"] + "."
    if k == "momentum":
        tilt = m["home_field_tilt"] if m["side"] == "home" else 1 - m["home_field_tilt"]
        return f"{team} are on top: {_pct(tilt)} " \
               f"of final-third passes over the last 10 minutes."
    if k == "rhythm":
        return f"The game has turned {m['label']} (chaos index {m['chaos_index']:.2f})."
    if k == "substitution":
        return f"{team} substitution: {m['on']} replaces {m['off']}."
    if k == "speed_tag":
        return f"{m['player']} hits {m['speed_kmh']:.1f} km/h."
    if k == "distance_milestone":
        return f"{m['player']} passes {m['distance_km']:.1f} km covered."
    if k == "sustained_pressure":
        return f"{team} keep the ball for a long spell: {m['shots']} shots worth {m['xg']:.2f} xG, no goal."
    if k == "yellow_card":
        return f"{m['player']} is booked for {team}."
    return k.replace("_", " ")


def moment_sheet(lm: LiveMatch, moment_id: str) -> dict:
    m = next(x for x in lm.moments if x["moment_id"] == moment_id)
    lines = [_line("headline", headline(lm, m))]
    if m["kind"] in ("goal", "brace", "hat_trick"):
        if m.get("assist"):
            lines.append(_line("assist", f"Assisted by {m['assist']}."))
        p = m.get("possession")
        if p:
            lines.append(_line("build_up", f"The move: {p['passes']} passes over {p['duration_s']:.0f} seconds, "
                                           f"starting from a {p['start_type']} ({p['phase']})."))
        key = "home" if m["team_id"] == lm.home else "away"
        lines.append(_line("swing", f"It moved {lm.team_name[m['team_id']]}'s win probability from "
                                    f"{_pct(m['win_prob_before'][key])} to {_pct(m['win_prob_after'][key])}."))
        if m["goal_number_for_player"] > 1:
            lines.append(_line("milestone", f"It is {m['scorer']}'s {ordinal(m['goal_number_for_player'])} goal "
                                            f"of the match."))
    ev = lm.by_id.get(m["event_ids"][0])
    v = lm.values.get(m["event_ids"][0]) if ev else None
    if v and m["kind"] not in ("goal", "brace", "hat_trick"):
        lines.append(_line("value", f"The action changed possession value by {v['added']:+.3f} goals."))
    return _sheet(lm, "moment", lines + match_lines(lm)[:2], m, subject=moment_id)


_NUM = re.compile(r"(?<![\w.])[-+]?\d+(?:,\d{3})*(?:\.\d+)?%?")


def numbers(sheet: dict) -> list[str]:
    return [n for line in sheet["lines"] for n in _NUM.findall(line["text"])]
