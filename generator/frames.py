"""Position frames (2 Hz) for all players and the ball, built from a simulated match's events.

Each player's path has four layers:
  1. team shape   - formation spots that slide with the ball, push up in possession and squeeze out of it
  2. involvement  - pulled to the exact spot of every event he takes part in (passer, receiver, tackler...)
  3. off-ball     - smooth wandering whose size is scaled so each player covers his physical profile's distance
  4. sprints      - short bursts at sprint speed (attacking runs in possession, recovery runs out of it)
then speeds are capped at the player's (fatigue-adjusted) top speed. Ball paths interpolate event locations, with
height for lofted passes. Output is in the absolute frame (the home team's first-half attacking frame).
"""
from __future__ import annotations

import math
import random

import numpy as np

from contracts.models import MatchMeta, Team
from generator import params as P

L, W = 105.0, 68.0
HZ = 2.0
DT = 1.0 / HZ
LOFT_M = {"high": 8.0, "launch": 12.0, "cross": 4.5, "corner": 5.0, "goal_kick": 15.0, "free_kick": 3.0}
SPRINT_KMH = 25.2
CRUISE_KMH = 22.0       # speed cap outside sprint bursts, so sprints come only from the burst layer
DEPTH_SCALE = 0.55      # compresses formation spots towards the team's centre (outfield block ~31 m deep)


def to_abs(is_home: bool, period: int, x: float, y: float) -> tuple[float, float]:
    """Team-frame point -> absolute. The transform is its own inverse."""
    return (x, y) if is_home == (period == 1) else (L - x, W - y)


def _smooth(a: np.ndarray, tau_s: float) -> np.ndarray:
    """Causal exponential smoothing along axis 0 (frames)."""
    k = 1 - math.exp(-DT / tau_s)
    out = np.empty_like(a)
    out[0] = a[0]
    for i in range(1, len(a)):
        out[i] = out[i - 1] + k * (a[i] - out[i - 1])
    return out


def _cap_speed(pos: np.ndarray, vmax: np.ndarray, alive: np.ndarray) -> np.ndarray:
    """pos (F, N, 2); limit each frame-to-frame step to vmax (F, N) m/s. Dead slots (off the pitch) jump freely."""
    out = pos.copy()
    lim = vmax * DT
    for i in range(1, len(out)):
        step = out[i] - out[i - 1]
        d = np.hypot(step[:, 0], step[:, 1])
        scale = np.where((d > lim[i]) & alive[i] & alive[i - 1], lim[i] / np.maximum(d, 1e-9), 1.0)
        out[i] = out[i - 1] + step * scale[:, None]
    return out


def build_frames(meta: MatchMeta, events: list[dict], teams: dict[str, Team], seed: int | None = None) -> list[dict]:
    rng = random.Random(meta.seed if seed is None else seed)
    nrng = np.random.default_rng(meta.seed if seed is None else seed)
    home_id = meta.home.team_id
    is_home = {meta.home.team_id: True, meta.away.team_id: False}
    players = {p.player_id: p for t in teams.values() for p in t.players}
    formation = {meta.home.team_id: meta.home.formation, meta.away.team_id: meta.away.formation}

    # ---------------------------------------------------------------- clock: one match timeline across both halves
    ends = {e["period"]: e["t"] for e in events if e["type"] == "period_end"}
    offset = {1: 0.0, 2: ends[1]}
    tau = np.concatenate([np.arange(0, ends[1], DT), ends[1] + np.arange(0, ends[2], DT)])
    period_of = np.where(tau < ends[1], 1, 2)
    nF = len(tau)

    def mt(e: dict, extra: float = 0.0) -> float:
        return offset[e["period"]] + e["t"] + extra

    # ---------------------------------------------------------------- slots: who is on the pitch, where, when
    # columns: home slots 0-10, away slots 11-21; a sub takes over his predecessor's column from the swap time
    cols: list[list[tuple[str, float, float]]] = [[] for _ in range(22)]     # (player_id, from, to)
    col_of: dict[str, int] = {}
    for base, sheet in ((0, meta.home), (11, meta.away)):
        for i, sp in enumerate(sheet.starting):
            cols[base + i].append((sp.player_id, 0.0, float("inf")))
            col_of[sp.player_id] = base + i
    for e in events:
        if e["type"] == "substitution":
            c = col_of.get(e["player_id"])
            if c is None:
                continue
            pid, start, _ = cols[c][-1]
            cols[c][-1] = (pid, start, mt(e))
            cols[c].append((e["related_player_id"], mt(e), float("inf")))
            col_of[e["related_player_id"]] = c
        elif e["type"] == "card" and e.get("subtype") in ("red", "second_yellow"):
            c = col_of.get(e["player_id"])
            if c is not None and players[e["player_id"]].position != "GK":
                pid, start, _ = cols[c][-1]
                cols[c][-1] = (pid, start, mt(e))
    alive = np.zeros((nF, 22), dtype=bool)
    occupant = np.full((nF, 22), -1, dtype=int)
    roster: list[str] = []
    for c, spans in enumerate(cols):
        for pid, a, b in spans:
            m = (tau >= a) & (tau < b)
            alive[m, c] = True
            occupant[m, c] = len(roster)
            roster.append(pid)
    team_of_col = np.array([home_id] * 11 + [meta.away.team_id] * 11)
    spots = np.array([P.SPOTS[formation[meta.home.team_id]][i] for i in range(11)]
                     + [P.SPOTS[formation[meta.away.team_id]][i] for i in range(11)], dtype=float)
    BLOCK_MID = 52.0
    gk_col = np.array([meta.home.starting[i].position == "GK" for i in range(11)]
                      + [meta.away.starting[i].position == "GK" for i in range(11)])

    # ---------------------------------------------------------------- ball path and possession
    bt, bx, by = [], [], []
    poss_t, poss_home = [], []
    loft = np.zeros(nF)
    for e in events:
        if e.get("possession_team_id"):
            poss_t.append(mt(e))
            poss_home.append(e["possession_team_id"] == home_id)
        if "start" not in e or "team_id" not in e:
            continue
        h, p = is_home[e["team_id"]], e["period"]
        sx, sy = to_abs(h, p, e["start"]["x"], e["start"]["y"])
        bt.append(mt(e))
        bx.append(sx)
        by.append(sy)
        if "end" in e:
            dur = e.get("duration_s") or (0.5 if e["type"] == "shot" else 0.0)
            ex, ey = to_abs(h, p, e["end"]["x"], e["end"]["y"])
            bt.append(mt(e, dur))
            bx.append(ex)
            by.append(ey)
            if e["type"] == "pass" and e.get("subtype") in LOFT_M and dur > 0:
                m = (tau >= mt(e)) & (tau <= mt(e, dur))
                u = (tau[m] - mt(e)) / dur
                loft[m] = np.maximum(loft[m], 4 * LOFT_M[e["subtype"]] * u * (1 - u))
    order = np.argsort(bt, kind="stable")
    bt, bx, by = np.array(bt)[order], np.array(bx)[order], np.array(by)[order]
    ball = np.stack([np.interp(tau, bt, bx), np.interp(tau, bt, by)], axis=1)
    pidx = np.searchsorted(np.array(poss_t), tau, side="right") - 1
    home_has = np.array(poss_home)[np.clip(pidx, 0, None)]

    # ---------------------------------------------------------------- layer 1: team shape
    shape = np.zeros((nF, 22, 2))
    for c in range(22):
        h = c < 11
        # ball in this team's own frame, per frame
        flip = (h != (period_of == 1))
        bxt = np.where(flip, L - ball[:, 0], ball[:, 0])
        byt = np.where(flip, W - ball[:, 1], ball[:, 1])
        in_poss = home_has if h else ~home_has
        sx, sy = spots[c]
        if not gk_col[c]:
            sx = BLOCK_MID + (sx - BLOCK_MID) * DEPTH_SCALE
        if gk_col[c]:
            x = np.clip(sx + 0.12 * (bxt - L / 2), 2, 20)
            y = W / 2 + 0.25 * (byt - W / 2)
        else:
            stretch = np.where(in_poss, 1.15, 0.85)      # longer in possession, compact out of it
            x = BLOCK_MID + (sx - BLOCK_MID) * stretch + 0.55 * (bxt - L / 2) + np.where(in_poss, 3.0, -5.0)
            width = np.where(in_poss, 1.0, 0.74)
            y = W / 2 + (sy - W / 2) * width + 0.22 * (byt - sy)
        x, y = np.clip(x, 1, L - 1), np.clip(y, 1, W - 1)
        ax = np.where(flip, L - x, x)
        ay = np.where(flip, W - y, y)
        shape[:, c, 0], shape[:, c, 1] = ax, ay
    shape = _smooth(shape, 2.5)

    # ---------------------------------------------------------------- layer 2: involvement in events
    wsum = np.zeros((nF, 22))
    wpos = np.zeros((nF, 22, 2))

    def pull(pid: str | None, when: float, pt: tuple[float, float], sigma: float = 2.2) -> None:
        c = col_of.get(pid) if pid else None
        if c is None:
            return
        i0, i1 = np.searchsorted(tau, [when - 3 * sigma, when + 3 * sigma])
        if i1 <= i0:
            return
        w = np.exp(-0.5 * ((tau[i0:i1] - when) / sigma) ** 2) * alive[i0:i1, c]
        wsum[i0:i1, c] += w
        wpos[i0:i1, c, 0] += w * pt[0]
        wpos[i0:i1, c, 1] += w * pt[1]

    for e in events:
        if "start" not in e or "team_id" not in e:
            continue
        h, p = is_home[e["team_id"]], e["period"]
        pull(e.get("player_id"), mt(e), to_abs(h, p, e["start"]["x"], e["start"]["y"]))
        if e["type"] == "pass" and e.get("outcome") == "complete" and "end" in e:
            pull(e.get("related_player_id"), mt(e, e.get("duration_s") or 0.0),
                 to_abs(h, p, e["end"]["x"], e["end"]["y"]))
        elif e["type"] == "carry" and "end" in e:
            pull(e.get("player_id"), mt(e, e.get("duration_s") or 0.0), to_abs(h, p, e["end"]["x"], e["end"]["y"]))
    wclip = np.minimum(wsum, 1.0)
    target = shape * (1 - wclip[..., None]) + np.where(wsum[..., None] > 0, wpos / np.maximum(wsum, 1e-9)[..., None],
                                                       0) * wclip[..., None]
    target = _smooth(target, 0.8)

    # ---------------------------------------------------------------- per-column player attributes over time
    def per_col(fn) -> np.ndarray:
        out = np.zeros((nF, 22))
        for c in range(22):
            occ = occupant[:, c]
            vals = np.array([fn(players[roster[k]]) for k in range(len(roster))])
            out[:, c] = np.where(occ >= 0, vals[np.clip(occ, 0, None)], 0.0)
        return out

    def fatigue_curve() -> np.ndarray:
        fat = np.zeros((nF, 22))
        for c, spans in enumerate(cols):
            for pid, a, b in spans:
                m = (tau >= a) & (tau < b)
                mins = (tau[m] - a) / 60
                fat[m, c] = np.minimum(P.FATIGUE_CAP, P.FATIGUE_AT_90 * (mins / 90) ** 1.6
                                       / players[pid].attributes.stamina)
        return fat

    fat = fatigue_curve()
    top = per_col(lambda pl: pl.attributes.top_speed_kmh) / 3.6 * (1 - 0.3 * fat)

    # ---------------------------------------------------------------- layer 4: sprint bursts
    sprint = np.zeros((nF, 22, 2))
    burst_on = np.zeros((nF, 22), dtype=bool)
    for c, spans in enumerate(cols):
        for pid, a, b in spans:
            pl = players[pid]
            if pl.position == "GK":
                continue
            b_ = min(b, tau[-1])
            minutes = (b_ - a) / 60
            # extra bursts make up for sprints the shape and involvement layers produce on their own
            n = nrng.poisson(pl.attributes.sprints_per90 * P.PHYSICAL_SCALE * minutes / 90 * 1.05)
            for _ in range(n):
                t0 = rng.uniform(a, b_ - 6)
                i0 = int(np.searchsorted(tau, t0))
                if i0 >= nF - 2:
                    continue
                own_poss = home_has[i0] if c < 11 else not home_has[i0]
                attacking_right = (c < 11) == (period_of[i0] == 1)
                fwd = 1.0 if attacking_right else -1.0
                direction = fwd if own_poss else -fwd
                ang = rng.gauss(0, 0.45)
                v = rng.uniform(SPRINT_KMH + 1.0, max(SPRINT_KMH + 1.5, pl.attributes.top_speed_kmh - 0.5)) / 3.6
                t_up = rng.uniform(2.5, 4.0)
                dist = v * t_up
                ux, uy = direction * math.cos(ang), math.sin(ang)
                k_up = int(t_up * HZ)
                k_back = int(14 * HZ)
                prof = np.concatenate([np.linspace(0, 1, k_up + 1)[1:], np.linspace(1, 0, k_back + 1)[1:]])
                seg = slice(i0, min(nF, i0 + len(prof)))
                prof = prof[: seg.stop - seg.start]
                sprint[seg, c, 0] += prof * dist * ux
                sprint[seg, c, 1] += prof * dist * uy
                burst_on[i0:min(nF, i0 + k_up + 1), c] = True

    # ---------------------------------------------------------------- layer 3: off-ball wandering, scaled to distance
    phase = nrng.uniform(0, 2 * math.pi, size=(3, 22, 2))
    period_s = nrng.uniform(9, 30, size=(3, 22, 2))
    wander_unit = np.zeros((nF, 22, 2))
    for k in range(3):
        wander_unit += np.sin(2 * math.pi * tau[:, None, None] / period_s[k] + phase[k]) / 3
    target_mpm = per_col(lambda pl: pl.attributes.distance_m_per_min) * (1 - 0.5 * fat)
    amp = np.full(22, 3.0)
    amp[gk_col] = 0.8

    def assemble(amp_: np.ndarray) -> np.ndarray:
        pos = target + sprint + wander_unit * amp_[None, :, None]
        pos[..., 0] = np.clip(pos[..., 0], 0.5, L - 0.5)
        pos[..., 1] = np.clip(pos[..., 1], 0.5, W - 0.5)
        return _cap_speed(pos, vmax, alive)

    vmax = np.where(burst_on, top, np.minimum(top, CRUISE_KMH / 3.6))
    want = (target_mpm * alive).sum(axis=0) * DT / 60     # metres each column should cover
    for _ in range(4):
        pos = assemble(amp)
        step = np.hypot(*np.moveaxis(np.diff(pos, axis=0), -1, 0)) * (alive[1:] & alive[:-1])
        got = step.sum(axis=0)
        amp = np.clip(amp * np.where(got > 0, want / np.maximum(got, 1e-6), 1.0) ** 2.2, 0.2, 30.0)
    pos = assemble(amp)

    # ---------------------------------------------------------------- speeds, distances, output
    step = np.zeros((nF, 22))
    step[1:] = np.hypot(*np.moveaxis(np.diff(pos, axis=0), -1, 0)) * (alive[1:] & alive[:-1])
    speed = step / DT * 3.6
    speed[1:] = 0.5 * (speed[1:] + speed[:-1])
    dist_by_player: dict[str, float] = {}
    frames = []
    for i in range(nF):
        per = int(period_of[i])
        out_players = []
        for c in range(22):
            if not alive[i, c]:
                continue
            pid = roster[occupant[i, c]]
            dist_by_player[pid] = dist_by_player.get(pid, 0.0) + step[i, c]
            out_players.append({"player_id": pid, "team_id": str(team_of_col[c]), "x": round(float(pos[i, c, 0]), 1),
                                "y": round(float(pos[i, c, 1]), 1), "speed_kmh": round(float(speed[i, c]), 1),
                                "distance_m": round(dist_by_player[pid], 1)})
        frames.append({"match_id": meta.match_id, "period": per, "t": round(float(tau[i] - offset[per]), 2),
                       "ball": {"x": round(float(ball[i, 0]), 1), "y": round(float(ball[i, 1]), 1),
                                "z": round(float(loft[i]), 1)},
                       "players": out_players})
    return frames
