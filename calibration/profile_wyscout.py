"""Profile a full Wyscout season (Pappalardo et al. 2019, CC BY 4.0) into generator parameters.

usage: py -I profile_wyscout.py <wyscout_dir> <out_params.json>
<wyscout_dir> holds events_England.json, matches_England.json, players.json, teams.json.

Wyscout coords are 0-100 in the acting team's attacking frame (x -> opponent goal, y 0 = left touchline).
Converted to metres on a 105x68 pitch. No vendor xG exists, so xG is fitted to real goal outcomes.
"""
import json, sys, os, math, statistics as st
from collections import Counter, defaultdict

src, out_path = sys.argv[1], sys.argv[2]
L, W = 105.0, 68.0
GOAL_Y, HALF_GOAL = W / 2, 7.32 / 2

events = json.load(open(os.path.join(src, "events_England.json"), encoding="utf-8"))
matches = json.load(open(os.path.join(src, "matches_England.json"), encoding="utf-8"))
players = {p["wyId"]: p for p in json.load(open(os.path.join(src, "players.json"), encoding="utf-8"))}
teams = {t["wyId"]: t for t in json.load(open(os.path.join(src, "teams.json"), encoding="utf-8"))}

bym = defaultdict(list)
for e in events:
    bym[e["matchId"]].append(e)
for es in bym.values():
    es.sort(key=lambda e: (e["matchPeriod"], e["eventSec"]))
minfo = {m["wyId"]: m for m in matches}
home_of = {mid: next(int(t) for t, d in m["teamsData"].items() if d["side"] == "home") for mid, m in minfo.items()}
away_of = {mid: next(int(t) for t, d in m["teamsData"].items() if d["side"] == "away") for mid, m in minfo.items()}
N = len(bym)
P = {"source": "Wyscout soccer-logs (Pappalardo et al. 2019), Premier League 2017/18, CC BY 4.0", "matches": N}

def tags(e):
    return {t["id"] for t in e["tags"]}

def xy(p):
    return p["x"] * L / 100, p["y"] * W / 100

def minute(e):
    m = e["eventSec"] / 60
    return m + 45 if e["matchPeriod"] == "2H" else m

def zone(x, y):
    t = "def" if x < L / 3 else ("mid" if x < 2 * L / 3 else "att")
    l = "L" if y < W / 3 else ("C" if y < 2 * W / 3 else "R")
    return f"{t}-{l}"

def goal_angle(x, y):
    dx = L - x
    a = math.atan2(2 * HALF_GOAL * dx, dx * dx + (y - GOAL_Y) ** 2 - HALF_GOAL ** 2)
    return a + math.pi if a < 0 else a

def is_shot(e):
    return e["eventId"] == 10 or e["subEventId"] in (33, 35)

def is_goal_for(e):  # returns team credited, or None
    tg = tags(e)
    if 102 in tg:  # own goal: credit the opponent
        return "own"
    if 101 in tg and (is_shot(e)):
        return "shot"
    return None

POSS_EVENTS = {8, 10, 3, 7}  # pass, shot, free kick (restarts), others on the ball

# ---------------------------------------------------------------- per-match volumes
sub_keys = {e["subEventName"] or e["eventName"] for e in events}
type_keys = {e["eventName"] for e in events}
sub_counts, type_counts = defaultdict(list), defaultdict(list)
for mid, es in bym.items():
    c = Counter(e["subEventName"] or e["eventName"] for e in es)
    ct = Counter(e["eventName"] for e in es)
    for k in sub_keys:
        sub_counts[k].append(c.get(k, 0))
    for k in type_keys:
        type_counts[k].append(ct.get(k, 0))
P["per_match"] = {k: {"mean": round(st.mean(v), 2), "sd": round(st.pstdev(v), 2)}
                  for k, v in sorted(type_counts.items(), key=lambda kv: -st.mean(kv[1]))}
P["per_match_subevent"] = {k: {"mean": round(st.mean(v), 2), "sd": round(st.pstdev(v), 2)}
                           for k, v in sorted(sub_counts.items(), key=lambda kv: -st.mean(kv[1])) if st.mean(v) >= 0.5}

# ---------------------------------------------------------------- results, scorelines, home advantage
hg = [minfo[m]["teamsData"][str(home_of[m])]["score"] for m in bym]
ag = [minfo[m]["teamsData"][str(away_of[m])]["score"] for m in bym]
res = Counter("H" if h > a else ("A" if a > h else "D") for h, a in zip(hg, ag))
P["results"] = {
    "home_goals_mean": round(st.mean(hg), 3), "away_goals_mean": round(st.mean(ag), 3),
    "home_win": round(res["H"] / N, 3), "draw": round(res["D"] / N, 3), "away_win": round(res["A"] / N, 3),
    "top_scorelines": {f"{h}-{a}": round(c / N, 3) for (h, a), c in Counter(zip(hg, ag)).most_common(12)},
    "total_goals_dist": {str(k): round(v / N, 3) for k, v in sorted(Counter(h + a for h, a in zip(hg, ag)).items())},
}

# ---------------------------------------------------------------- timing
gaps, half_len = [], {"1H": [], "2H": []}
goal_min, shot_min = Counter(), Counter()
for mid, es in bym.items():
    for per in ("1H", "2H"):
        pe = [e for e in es if e["matchPeriod"] == per]
        if pe:
            half_len[per].append(pe[-1]["eventSec"] / 60)
        for a, b in zip(pe, pe[1:]):
            gaps.append(b["eventSec"] - a["eventSec"])
    for e in es:
        mn = minute(e)
        if e["matchPeriod"] == "1H" and mn >= 45:
            bucket = "45+"
        elif mn >= 90:
            bucket = "90+"
        else:
            bucket = f"{int(mn // 15) * 15}-{int(mn // 15) * 15 + 15}"
        if is_shot(e):
            shot_min[bucket] += 1
        if is_goal_for(e):
            goal_min[bucket] += 1
order = ["0-15", "15-30", "30-45", "45+", "45-60", "60-75", "75-90", "90+"]
qg = st.quantiles(gaps, n=20)
P["timing"] = {
    "event_gap_s": {"median": round(st.median(gaps), 2), "p05": round(qg[0], 2), "p95": round(qg[-1], 2), "mean": round(st.mean(gaps), 2)},
    "half_length_min": {k: {"median": round(st.median(v), 1), "p90": round(st.quantiles(v, n=10)[-1], 1)} for k, v in half_len.items()},
    "shots_by_window": {k: round(shot_min[k] / sum(shot_min.values()), 3) for k in order},
    "goals_by_window": {k: round(goal_min[k] / sum(goal_min.values()), 3) for k in order},
}

# ---------------------------------------------------------------- possessions
def takes_control(e):  # contested touches, clearances and failed passes don't hand the ball over on their own
    return e["eventId"] in (10, 3) or e["subEventId"] == 70 or (e["eventId"] == 8 and 1801 in tags(e))

poss = []  # dicts
for mid, es in bym.items():
    cur = None
    for e in es:
        if e["eventId"] in POSS_EVENTS:
            if cur is not None and e["teamId"] != cur["team"] and e["matchPeriod"] == cur["period"] and not takes_control(e):
                continue
            if cur is None or e["teamId"] != cur["team"] or e["matchPeriod"] != cur["period"]:
                if cur:
                    poss.append(cur)
                start = e["subEventName"] if e["eventId"] == 3 else "Open play"
                if 1401 in tags(e):
                    start = "Interception"
                cur = {"team": e["teamId"], "period": e["matchPeriod"], "t0": e["eventSec"], "t1": e["eventSec"],
                       "n": 0, "start": start, "shot": False, "goal": False, "x0": xy(e["positions"][0])[0],
                       "counter": False, "passes": 0}
            cur["n"] += 1
            cur["t1"] = e["eventSec"]
            cur["passes"] += e["eventId"] == 8
            if is_shot(e):
                cur["shot"] = True
                cur["goal"] |= 101 in tags(e)
            cur["counter"] |= 1901 in tags(e)
    if cur:
        poss.append(cur)
dur = [p["t1"] - p["t0"] for p in poss]
lens = [p["n"] for p in poss]
by_start = defaultdict(list)
for p in poss:
    by_start[p["start"]].append(p)
P["possessions"] = {
    "definition": "run of on-ball events by one team; ends when the opponent takes control (accurate pass, shot, restart, carry) - duels, fouls, clearances and failed passes alone don't end it",
    "per_match": round(len(poss) / N, 1),
    "on_ball_events": {"median": st.median(lens), "p90": st.quantiles(lens, n=10)[-1]},
    "duration_s": {"median": round(st.median(dur), 1), "p10": round(st.quantiles(dur, n=10)[0], 1), "p90": round(st.quantiles(dur, n=10)[-1], 1)},
    "ends_in_shot": round(sum(p["shot"] for p in poss) / len(poss), 4),
    "by_start": {k: {"share": round(len(v) / len(poss), 3), "shot_rate": round(sum(p["shot"] for p in v) / len(v), 4),
                     "goal_rate": round(sum(p["goal"] for p in v) / len(v), 4)}
                 for k, v in sorted(by_start.items(), key=lambda kv: -len(kv[1]))},
    "shot_rate_by_start_third": {},
}
for name, lo, hi in [("def", 0, L / 3), ("mid", L / 3, 2 * L / 3), ("att", 2 * L / 3, L + 1)]:
    v = [p for p in poss if lo <= p["x0"] < hi and p["start"] in ("Open play", "Interception")]
    P["possessions"]["shot_rate_by_start_third"][name] = {"share": round(len(v) / len(poss), 3), "shot_rate": round(sum(p["shot"] for p in v) / len(v), 4)}
cp = [p for p in poss if p["counter"]]
P["possessions"]["counter_attacks"] = {"per_match": round(len(cp) / N, 2), "shot_rate": round(sum(p["shot"] for p in cp) / max(len(cp), 1), 3)}

# set pieces: shot / goal by the taking team within 15 s, before a change of possession under the rule above
sp = defaultdict(lambda: [0, 0, 0])
for es in bym.values():
    for i, e in enumerate(es):
        if e["eventId"] != 3 or e["subEventId"] in (33, 35):
            continue
        k = e["subEventName"]
        if k == "Throw in" and xy(e["positions"][0])[0] >= 2 * L / 3:
            k = "Throw in (final third)"
        sp[k][0] += 1
        for f in es[i + 1:]:
            if f["matchPeriod"] != e["matchPeriod"] or f["eventSec"] - e["eventSec"] > 15:
                break
            if f["teamId"] != e["teamId"] and f["eventId"] in POSS_EVENTS and takes_control(f):
                break
            if f["teamId"] == e["teamId"] and is_shot(f):
                sp[k][1] += 1; sp[k][2] += 101 in tags(f)
                break
P["set_pieces"] = {k: {"per_match": round(n / N, 2), "shot_within_15s": round(s_ / n, 3), "goal_within_15s": round(g_ / n, 4)}
                   for k, (n, s_, g_) in sorted(sp.items(), key=lambda kv: -kv[1][0])}

# ---------------------------------------------------------------- transitions (subevent level, same-team continuation vs turnover)
trans = defaultdict(Counter)
turnover = Counter(); seen = Counter()
for es in bym.values():
    on = [e for e in es if e["eventId"] in POSS_EVENTS or e["eventId"] == 1]
    for a, b in zip(on, on[1:]):
        ka = a["subEventName"] or a["eventName"]
        kb = (b["subEventName"] or b["eventName"]) + ("" if b["teamId"] == a["teamId"] else " (opp)")
        trans[ka][kb] += 1
        if a["eventId"] in POSS_EVENTS and b["eventId"] in POSS_EVENTS:
            seen[ka] += 1
            turnover[ka] += b["teamId"] != a["teamId"]
P["transitions_top"] = {k: {b: round(c / sum(v.values()), 3) for b, c in v.most_common(6)}
                        for k, v in trans.items() if sum(v.values()) > 2000}
P["turnover_after"] = {k: round(turnover[k] / seen[k], 3) for k in seen if seen[k] > 2000}

# ---------------------------------------------------------------- passes
pz = defaultdict(lambda: [0, 0, []])
psub = defaultdict(lambda: [0, 0, []])
for e in events:
    if e["eventId"] != 8 or len(e["positions"]) < 2:
        continue
    (x0, y0), (x1, y1) = xy(e["positions"][0]), xy(e["positions"][1])
    ok = 1801 in tags(e)
    ln = math.hypot(x1 - x0, y1 - y0)
    for d, k in ((pz, zone(x0, y0)), (psub, e["subEventName"])):
        d[k][0] += 1; d[k][1] += ok; d[k][2].append(ln)
P["passes"] = {
    "by_zone": {z: {"per_match": round(a / N, 1), "completion": round(c / a, 3), "len_m_median": round(st.median(Ls), 1)}
                for z, (a, c, Ls) in sorted(pz.items())},
    "by_type": {k: {"per_match": round(a / N, 1), "completion": round(c / a, 3), "len_m_median": round(st.median(Ls), 1)}
                for k, (a, c, Ls) in sorted(psub.items(), key=lambda kv: -kv[1][0])},
}

# ---------------------------------------------------------------- duels & set pieces
duel = defaultdict(Counter)
for e in events:
    if e["eventId"] == 1:
        tg = tags(e)
        duel[e["subEventName"]]["won" if 703 in tg else ("lost" if 701 in tg else "neutral")] += 1
P["duels"] = {k: {o: round(c / sum(v.values()), 3) for o, c in v.items()} for k, v in duel.items()}
cards = Counter(); card_min = []
for e in events:
    tg = tags(e)
    for t, name in ((1702, "yellow"), (1703, "second_yellow"), (1701, "red")):
        if t in tg:
            cards[name] += 1; card_min.append(minute(e))
def subs_of(d):
    s = d["formation"].get("substitutions")
    return s if isinstance(s, list) else []
subs = [s["minute"] for m in minfo.values() for d in m["teamsData"].values() for s in subs_of(d)]
P["discipline_subs"] = {
    "cards_per_match": {k: round(v / N, 3) for k, v in cards.items()},
    "card_minute_median": round(st.median(card_min), 1),
    "subs_per_team_match": round(len(subs) / (2 * N), 2),
    "sub_minute": {"p10": st.quantiles(subs, n=10)[0], "median": st.median(subs), "p90": st.quantiles(subs, n=10)[-1]},
    "first_sub_minute_median": st.median(min(s["minute"] for s in subs_of(d))
                                         for m in minfo.values() for d in m["teamsData"].values() if subs_of(d)),
}

# ---------------------------------------------------------------- shots & xG (fitted to real goals)
rows = []
for e in events:
    if not is_shot(e):
        continue
    x, y = xy(e["positions"][0])
    tg = tags(e)
    rows.append({"dist": math.hypot(L - x, y - GOAL_Y), "ang": goal_angle(x, y), "head": 403 in tg,
                 "goal": 101 in tg, "on_target": 1801 in tg, "blocked": 2101 in tg,
                 "pen": e["subEventId"] == 35, "fk": e["subEventId"] == 33, "counter": 1901 in tg,
                 "foot": "head" if 403 in tg else ("left" if 401 in tg else ("right" if 402 in tg else "other"))})
op = [r for r in rows if not r["pen"] and not r["fk"]]

def logit_fit(X, y, iters=25):
    k = len(X[0]); b = [0.0] * k
    for _ in range(iters):
        g = [0.0] * k; H = [[0.0] * k for _ in range(k)]
        for xi, yi in zip(X, y):
            z = sum(bj * xj for bj, xj in zip(b, xi)); p = 1 / (1 + math.exp(-z)); w = p * (1 - p)
            for a in range(k):
                g[a] += (yi - p) * xi[a]
                for c in range(k):
                    H[a][c] += w * xi[a] * xi[c]
        # solve H d = g (Gaussian elimination)
        M = [H[i][:] + [g[i]] for i in range(k)]
        for i in range(k):
            piv = max(range(i, k), key=lambda r: abs(M[r][i])); M[i], M[piv] = M[piv], M[i]
            for r in range(k):
                if r != i:
                    f = M[r][i] / M[i][i]
                    M[r] = [mr - f * mi for mr, mi in zip(M[r], M[i])]
        b = [bj + M[i][k] / M[i][i] for i, bj in enumerate(b)]
    return b

X = [[1, r["dist"], r["ang"], float(r["head"])] for r in op]
Y = [float(r["goal"]) for r in op]
beta = logit_fit(X, Y)
xg = lambda r: 1 / (1 + math.exp(-(beta[0] + beta[1] * r["dist"] + beta[2] * r["ang"] + beta[3] * r["head"])))
bands = [(0, 6), (6, 11), (11, 16.5), (16.5, 22), (22, 30), (30, 99)]
P["shots"] = {
    "per_match": round(len(rows) / N, 2),
    "xg_model": {"form": "sigmoid(b0 + b1*dist_m + b2*goal_angle_rad + b3*is_header)", "b0": round(beta[0], 4), "b1": round(beta[1], 4),
                 "b2": round(beta[2], 4), "b3": round(beta[3], 4), "fit_on": f"{len(op)} open-play shots, real goal outcomes",
                 "xg_per_match_check": round(sum(xg(r) for r in op) / N, 3), "goals_per_match_open_play": round(sum(Y) / N, 3)},
    "by_distance_m": {f"{lo}-{hi}": {"share": round(len(v) / len(op), 3), "goal_rate": round(sum(r["goal"] for r in v) / len(v), 3),
                                     "model_xg": round(st.mean(xg(r) for r in v), 3), "on_target": round(sum(r["on_target"] for r in v) / len(v), 3)}
                      for lo, hi in bands for v in [[r for r in op if lo <= r["dist"] < hi]] if v},
    "outcome": {"on_target": round(sum(r["on_target"] for r in op) / len(op), 3), "blocked": round(sum(r["blocked"] for r in op) / len(op), 3),
                "goal": round(sum(r["goal"] for r in op) / len(op), 3)},
    "body_part": {k: round(v / len(op), 3) for k, v in Counter(r["foot"] for r in op).most_common()},
    "header_goal_rate": round(sum(r["goal"] for r in op if r["head"]) / max(1, sum(r["head"] for r in op)), 3),
    "penalty": {"per_match": round(sum(r["pen"] for r in rows) / N, 3), "conversion": round(sum(r["goal"] for r in rows if r["pen"]) / max(1, sum(r["pen"] for r in rows)), 3)},
    "direct_free_kick": {"per_match": round(sum(r["fk"] for r in rows) / N, 3), "conversion": round(sum(r["goal"] for r in rows if r["fk"]) / max(1, sum(r["fk"] for r in rows)), 3)},
    "counter_attack_shot_goal_rate": round(sum(r["goal"] for r in op if r["counter"]) / max(1, sum(r["counter"] for r in op)), 3),
}

# ---------------------------------------------------------------- game state: shots & on-ball share when leading / level / trailing
state_time = Counter(); state_shots = Counter(); state_onball = Counter(); state_onball_tot = Counter()
tt, ts, tob, tall = Counter(), Counter(), Counter(), Counter()  # keyed (team, state): time, shots, own on-ball, all on-ball
for mid, es in bym.items():
    h, a = home_of[mid], away_of[mid]
    score = {h: 0, a: 0}
    prev_t = 0.0
    for e in es:
        t = minute(e)
        st_h = "level" if score[h] == score[a] else ("leading" if score[h] > score[a] else "trailing")
        st_a = {"level": "level", "leading": "trailing", "trailing": "leading"}[st_h]
        dt = max(0.0, t - prev_t) if t >= prev_t else 0.0
        state_time[st_h] += dt; state_time[st_a] += dt
        tt[(h, st_h)] += dt; tt[(a, st_a)] += dt
        prev_t = t
        stt = st_h if e["teamId"] == h else st_a
        if is_shot(e):
            state_shots[stt] += 1
            ts[(e["teamId"], stt)] += 1
        if e["eventId"] in POSS_EVENTS:
            state_onball[stt] += 1
            state_onball_tot[st_h] += 1; state_onball_tot[st_a] += 1
            tob[(e["teamId"], stt)] += 1
            tall[(h, st_h)] += 1; tall[(a, st_a)] += 1
        g = is_goal_for(e)
        if g == "shot":
            score[e["teamId"]] += 1
        elif g == "own":
            score[a if e["teamId"] == h else h] += 1
STATES = ("leading", "level", "trailing")
team_ids = {t for t, _ in tt}
rate = {t: sum(ts[(t, s)] for s in STATES) / sum(tt[(t, s)] for s in STATES) for t in team_ids}
share = {t: sum(tob[(t, s)] for s in STATES) / sum(tall[(t, s)] for s in STATES) for t in team_ids}
P["game_state"] = {s: {"team_shots_per90_raw": round(state_shots[s] / (state_time[s] / 90), 2),
                       "on_ball_share_raw": round(state_onball[s] / state_onball_tot[s], 3),
                       "time_share": round(state_time[s] / sum(state_time.values()), 3),
                       # strength-adjusted: observed vs what the same teams do on average over the same minutes
                       "shot_rate_multiplier": round(sum(ts[(t, s)] for t in team_ids) / sum(rate[t] * tt[(t, s)] for t in team_ids), 3),
                       "on_ball_share_shift_pp": round(100 * (sum(tob[(t, s)] for t in team_ids) - sum(share[t] * tall[(t, s)] for t in team_ids)) / sum(tall[(t, s)] for t in team_ids), 2)}
                   for s in STATES}
P["game_state"]["note"] = "multiplier/shift are within-team (controls for strong teams leading more often); raw values are confounded"

# ---------------------------------------------------------------- team strength (multiplicative Poisson, home advantage)
def fit_rates(val):  # val[(mid, team)] = count
    T = sorted({t for m in bym for t in (home_of[m], away_of[m])})
    att = {t: 1.0 for t in T}; dfn = {t: 1.0 for t in T}; hadv = 1.0
    for _ in range(200):
        for t in T:
            num = sum(val[(m, t)] for m in bym if t in (home_of[m], away_of[m]))
            den = sum((hadv if home_of[m] == t else 1) * dfn[away_of[m] if home_of[m] == t else home_of[m]] for m in bym if t in (home_of[m], away_of[m]))
            att[t] = num / den
        for t in T:
            num = sum(val[(m, o)] for m in bym for o in (home_of[m], away_of[m]) if t in (home_of[m], away_of[m]) and o != t)
            den = sum((hadv if home_of[m] != t else 1) * att[away_of[m] if home_of[m] == t else home_of[m]] for m in bym if t in (home_of[m], away_of[m]))
            dfn[t] = num / den
        hadv = sum(val[(m, home_of[m])] for m in bym) / sum(att[home_of[m]] * dfn[away_of[m]] for m in bym)
        s = st.mean(att.values()); att = {t: v / s for t, v in att.items()}; dfn = {t: v * s for t, v in dfn.items()}
    base = st.mean(dfn.values())
    return {"home_multiplier": round(hadv, 3), "base_rate_away": round(base, 3),
            "attack": {"min": round(min(att.values()), 2), "max": round(max(att.values()), 2), "sd": round(st.pstdev(att.values()), 3)},
            "defence_conceded_mult": {"min": round(min(dfn.values()) / base, 2), "max": round(max(dfn.values()) / base, 2), "sd": round(st.pstdev(dfn.values()) / base, 3)},
            "corr_attack_defence": round(st.correlation([att[t] for t in T], [dfn[t] for t in T]), 3)}

goals_v = Counter(); shots_v = Counter()
for mid, es in bym.items():
    for t in (home_of[mid], away_of[mid]):
        goals_v[(mid, t)] = minfo[mid]["teamsData"][str(t)]["score"]
    for e in es:
        if is_shot(e):
            shots_v[(mid, e["teamId"])] += 1
P["team_strength"] = {"goals": fit_rates(goals_v), "shots": fit_rates(shots_v),
                      "note": "expected count = base * home_mult^is_home * attack[team] * defence_conceded_mult[opp]"}

# ---------------------------------------------------------------- players: physical attributes & role shares
used = {e["playerId"] for e in events if e["playerId"]}
role = lambda pid: players.get(pid, {}).get("role", {}).get("code2", "?")
P["players"] = {}
for r in ("GK", "DF", "MD", "FW"):
    ps = [players[p] for p in used if p in players and role(p) == r]
    hts = [p["height"] for p in ps if p["height"] and p["height"] > 150]
    wts = [p["weight"] for p in ps if p["weight"] and p["weight"] > 50]
    ages = [2017.6 - int(p["birthDate"][:4]) - int(p["birthDate"][5:7]) / 12 for p in ps if p.get("birthDate")]
    P["players"][r] = {"n": len(ps), "height_cm": {"mean": round(st.mean(hts), 1), "sd": round(st.pstdev(hts), 1)},
                       "weight_kg": {"mean": round(st.mean(wts), 1), "sd": round(st.pstdev(wts), 1)},
                       "age": {"mean": round(st.mean(ages), 1), "sd": round(st.pstdev(ages), 1)},
                       "foot": {k: round(v / len(ps), 3) for k, v in Counter(p["foot"] or "unknown" for p in ps).most_common()}}
share = defaultdict(Counter)
for e in events:
    r = role(e["playerId"])
    if e["eventId"] == 8: share["passes"][r] += 1
    if is_shot(e): share["shots"][r] += 1
    if is_shot(e) and 101 in tags(e): share["goals"][r] += 1
    if e["eventId"] == 1: share["duels"][r] += 1
    if 1401 in tags(e): share["interceptions"][r] += 1
P["role_share"] = {k: {r: round(c / sum(v.values()), 3) for r, c in v.most_common() if r != "?"} for k, v in share.items()}
# finishing skill spread: player goals vs model xG (players with >= 30 open-play shots)
pl_rows = defaultdict(lambda: [0, 0.0, 0])
for e in events:
    if is_shot(e) and e["subEventId"] not in (33, 35):
        x, y = xy(e["positions"][0]); tg = tags(e)
        r = {"dist": math.hypot(L - x, y - GOAL_Y), "ang": goal_angle(x, y), "head": 403 in tg}
        pl_rows[e["playerId"]][0] += 101 in tg; pl_rows[e["playerId"]][1] += xg(r); pl_rows[e["playerId"]][2] += 1
ratios = [g / x for g, x, n in pl_rows.values() if n >= 30 and x > 0]
P["finishing_skill"] = {"players": len(ratios), "goals_over_xg": {"p10": round(st.quantiles(ratios, n=10)[0], 2), "median": round(st.median(ratios), 2), "p90": round(st.quantiles(ratios, n=10)[-1], 2)}}

json.dump(P, open(out_path, "w", encoding="utf-8"), indent=1)

# ---------------------------------------------------------------- console summary
def show(title, d, depth=0):
    print("  " * depth + f"{title}:" if title else "", end="" if not title else "\n")
    for k, v in d.items():
        if isinstance(v, dict):
            show(k, v, depth + 1)
        else:
            print("  " * (depth + 1) + f"{k}: {v}")
for k in ["results", "timing", "possessions", "set_pieces", "passes", "duels", "discipline_subs", "shots", "game_state", "team_strength", "players", "role_share", "finishing_skill"]:
    show(k, P[k])
print("\nper-match (top 20 subevents):")
for k, v in list(P["per_match_subevent"].items())[:20]:
    print(f"  {k:28s} {v['mean']:7.1f} ± {v['sd']:.1f}")
print("\ntransitions:")
for k in ["Simple pass", "High pass", "Cross", "Ground attacking duel", "Ground defending duel", "Air duel", "Throw in", "Goal kick", "Corner", "Shot", "Clearance", "Touch", "Acceleration"]:
    if k in P["transitions_top"]:
        print(f"  {k:22s} -> " + ", ".join(f"{b} {c:.0%}" for b, c in P["transitions_top"][k].items()))
print("turnover after:", {k: v for k, v in sorted(P["turnover_after"].items(), key=lambda kv: -kv[1])})
