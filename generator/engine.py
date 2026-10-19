"""Possession-level match engine.

The ball holder takes one action per step (shot, pass, carry, take-on), possibly under pressure; each action's
outcome decides who holds the ball next and where. Restarts (throw-ins, goal kicks, corners, free kicks, penalties,
kick-offs) take dead-ball time and run their own short scripts. Every probability comes from generator/params.py.

Coordinates are in the possessing team's attacking frame (x -> 105); a change of possession flips them.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from contracts.models import MatchMeta, SheetPlayer, Team, TeamSheet, Venue
from generator import names
from generator import params as P

L, W = 105.0, 68.0
BOX_X, BOX_Y0, BOX_Y1 = 88.5, 13.84, 54.16
GOAL = (L, W / 2)
B0, B1, B2, B3 = P.xg_coefficients()
_MEAN_PRESS = sum(P.PRESSURE_RATE.values()) / len(P.PRESSURE_RATE)
UNPRESSED_ODDS = (1 - _MEAN_PRESS * P.PRESSURE_ODDS) / (1 - _MEAN_PRESS)


def clamp_pt(x: float, y: float) -> tuple[float, float]:
    return min(L, max(0.0, x)), min(W, max(0.0, y))


def flip(p: tuple[float, float]) -> tuple[float, float]:
    return L - p[0], W - p[1]


def third(x: float) -> str:
    return "def" if x < L / 3 else ("mid" if x < 2 * L / 3 else "att")


def in_box(p: tuple[float, float]) -> bool:
    return p[0] >= BOX_X and BOX_Y0 <= p[1] <= BOX_Y1


def goal_angle(x: float, y: float) -> float:
    dx = L - x
    a = math.atan2(7.32 * dx, dx * dx + (y - W / 2) ** 2 - 3.66 ** 2)
    return a + math.pi if a < 0 else a


def xg(x: float, y: float, header: bool) -> float:
    d = math.hypot(L - x, y - W / 2)
    return 1 / (1 + math.exp(-(B0 + B1 * d + B2 * goal_angle(x, y) + B3 * header)))


@dataclass
class OnPitch:
    player: object          # contracts.models.Player
    slot: int               # index into the formation's spots
    yellow: bool = False
    on_minute: int = 0      # match minute the player came on


@dataclass
class Side:
    team: Team
    is_home: bool
    on: list[OnPitch]
    bench: list
    sub_minutes: list[int]
    attack: float
    defence: float
    quality: float
    home: float = 1.0             # shot-volume home factor (sqrt of the calibrated home/away ratio, or its inverse)
    spots: list[tuple[float, float]] = field(default_factory=list)

    @property
    def id(self) -> str:
        return self.team.team_id

    def positions(self, ball_x: float) -> list[tuple[OnPitch, tuple[float, float]]]:
        """Slot spots shifted with the ball: the block moves up and down the pitch as a unit."""
        shift = 0.45 * (ball_x - L / 2)
        out = []
        for op in self.on:
            sx, sy = self.spots[op.slot]
            x = min(20.0, max(2.0, sx + 0.15 * shift)) if op.player.position == "GK" else sx + shift
            out.append((op, (min(103.0, max(3.0, x)), sy)))
        return out

    def find(self, positions: tuple[str, ...]) -> OnPitch | None:
        for op in self.on:
            if op.player.position in positions:
                return op
        return None

    def keeper(self) -> OnPitch:
        return self.find(("GK",)) or self.on[0]


class MatchSim:
    def __init__(self, home: Team, away: Team, seed: int, match_id: str | None = None, round_no: int = 1,
                 kickoff_utc: str | None = None):
        self.rng = random.Random(seed)
        self.seed = seed
        self.match_id = match_id or f"M{seed}"
        self.round_no = round_no
        self.kickoff_utc = kickoff_utc or (datetime(2026, 8, 15, 14, tzinfo=UTC)
                                           + timedelta(days=7 * (round_no - 1))).isoformat()
        h = math.sqrt(P.HOME_SHOT_MULT) * P.HOME_VOLUME_EXTRA
        self.sides = [self._side(home, True, h), self._side(away, False, 1 / h)]
        self.events: list[dict] = []
        self.score = [0, 0]
        self.period = 1
        self.t = 0.0
        self.possession = 0
        self.poss_side = 0
        self.poss_start_t = 0.0
        self.poss_origin = "kick_off"
        self.holder: OnPitch | None = None
        self.ball = (L / 2, W / 2)
        self.arrived = "ground"       # how the holder received it: ground / air / cross
        self.last_pass_idx: int | None = None
        self.half_end = 0.0

    # ------------------------------------------------------------------ setup
    def _side(self, team: Team, is_home: bool, home_mult: float) -> Side:
        slots = P.FORMATIONS[team.formation]
        pool = list(team.players)
        on = []
        for i, pos in enumerate(slots):
            cands = [p for p in pool if p.position == pos] or [p for p in pool if p.role == P.ROLE_OF[pos]]
            # the first-listed player at a position is the usual starter; occasional rotation
            pick = cands[0] if self.rng.random() < 0.8 or len(cands) == 1 else self.rng.choice(cands[1:])
            pool.remove(pick)
            on.append(OnPitch(pick, i))
        gk_bench = [p for p in pool if p.position == "GK"][:1]
        others = [p for p in pool if p.position != "GK"]
        self.rng.shuffle(others)
        bench = gk_bench + others[:8]
        n = 3 if self.rng.random() < P.SUBS["three"] else 2
        mins = sorted(int(min(P.SUBS["latest"], max(P.SUBS["earliest"],
                                                     self.rng.gauss(P.SUBS["minute_mean"], P.SUBS["minute_sd"]))))
                      for _ in range(n))
        r = team.ratings
        # home advantage: volume via `home` (home x sqrt(m), away / sqrt(m) gives the calibrated shots ratio m) and
        # the rest of the goals ratio via finishing quality
        q_home = math.sqrt(P.HOME_GOAL_MULT / P.HOME_SHOT_MULT)
        return Side(team, is_home, on, bench, mins, r.attack, r.defence,
                    r.quality * (q_home if is_home else 1 / q_home), home=home_mult,
                    spots=list(P.SPOTS[team.formation]))

    def meta(self) -> MatchMeta:
        def sheet(s: Side) -> TeamSheet:
            def sp(p) -> SheetPlayer:
                return SheetPlayer(player_id=p.player_id, name=p.name, short_name=p.short_name, shirt=p.shirt,
                                   position=p.position)
            return TeamSheet(team_id=s.id, name=s.team.name, short_name=s.team.short_name, colors=s.team.colors,
                             formation=s.team.formation, starting=[sp(p) for p in self.starting[s.id]],
                             bench=[sp(p) for p in self.bench_at_start[s.id]])
        home = self.sides[0].team
        return MatchMeta(match_id=self.match_id, competition="Premier Synthetic League", season="2026/27",
                         round=self.round_no, kickoff_utc=self.kickoff_utc,
                         venue=Venue(name=home.stadium, city=home.city),
                         referee=names.person(random.Random(self.seed))[0],
                         home=sheet(self.sides[0]), away=sheet(self.sides[1]), seed=self.seed,
                         generator_version=P.GENERATOR_VERSION)

    # ------------------------------------------------------------------ helpers
    @property
    def att(self) -> Side:
        return self.sides[self.poss_side]

    @property
    def dfn(self) -> Side:
        return self.sides[1 - self.poss_side]

    def minute(self) -> int:
        return int(self.t // 60) + (45 if self.period == 2 else 0)

    def clock(self) -> str:
        base = 45 if self.period == 1 else 90
        m = int(self.t // 60) + 1 + (0 if self.period == 1 else 45)
        return f"{base}+{m - base}'" if m > base else f"{m}'"

    def lognorm(self, median: float, sigma: float) -> float:
        return median * math.exp(self.rng.gauss(0, sigma))

    def advance(self, seconds: float) -> None:
        self.t += max(0.0, seconds)

    def emit(self, type_: str, side: Side | None, player=None, start=None, end=None, **kw) -> int:
        e = {"event_id": f"{self.match_id}-{len(self.events):05d}", "match_id": self.match_id,
             "seq": len(self.events), "period": self.period, "t": round(self.t, 2), "minute": self.minute(),
             "clock": self.clock(), "type": type_, "possession": self.possession,
             "possession_team_id": self.att.id}
        if side is not None:
            e["team_id"] = side.id
        if player is not None:
            e["player_id"] = player.player_id
        if start is not None:
            x, y = clamp_pt(*start)
            e["start"] = {"x": round(x, 1), "y": round(y, 1)}
        if end is not None:
            x, y = clamp_pt(*end)
            e["end"] = {"x": round(x, 1), "y": round(y, 1)}
        for k, v in kw.items():
            if v is not None and v != []:
                e[k] = v
        self.events.append(e)
        return len(self.events) - 1

    def strength(self) -> float:
        """Chance-volume multiplier for the side in possession (attack x opponent's conceding x home)."""
        a, d = self.att, self.dfn
        return a.attack * d.defence

    def fatigue(self, op: OnPitch) -> float:
        on = max(0, self.minute() - op.on_minute)
        f = P.FATIGUE_AT_90 * (on / 90) ** 1.6 / op.player.attributes.stamina
        return min(P.FATIGUE_CAP, f)

    def game_state(self) -> str:
        me, opp = self.score[self.poss_side], self.score[1 - self.poss_side]
        return "level" if me == opp else ("leading" if me > opp else "trailing")

    def pick_near(self, side: Side, target: tuple[float, float], frame_ball_x: float, exclude=None,
                  sigma: float = 11.0, no_gk: bool = True) -> OnPitch:
        best, weights = [], []
        for op, (x, y) in side.positions(frame_ball_x):
            if op is exclude or (no_gk and op.player.position == "GK"):
                continue
            d2 = (x - target[0]) ** 2 + (y - target[1]) ** 2
            best.append(op)
            weights.append(math.exp(-d2 / (2 * sigma * sigma)) + 1e-9)
        return self.rng.choices(best, weights)[0]

    def defender_near(self, p: tuple[float, float]) -> tuple[OnPitch, tuple[float, float]]:
        """An opponent close to point p (given in the attacking frame); returns him and p in his frame."""
        fp = flip(p)
        return self.pick_near(self.dfn, fp, fp[0], sigma=8.0, no_gk=False), fp

    def change_possession(self, new_side: int, holder: OnPitch, ball: tuple[float, float], origin: str) -> None:
        """ball is given in the NEW possessor's frame."""
        if new_side != self.poss_side:
            self.possession += 1
            self.poss_side = new_side
            self.poss_start_t = self.t
            self.poss_origin = origin
            self.last_pass_idx = None
        self.holder, self.ball, self.arrived = holder, clamp_pt(*ball), "ground"

    def turnover(self, holder: OnPitch, ball_new_frame: tuple[float, float], origin: str) -> None:
        self.change_possession(1 - self.poss_side, holder, ball_new_frame, origin)

    # ------------------------------------------------------------------ main loop
    def run(self) -> tuple[MatchMeta, list[dict]]:
        self.starting = {s.id: [o.player for o in s.on] for s in self.sides}
        self.bench_at_start = {s.id: list(s.bench) for s in self.sides}
        for period in (1, 2):
            self.period, self.t = period, 0.0
            mu, sd = P.HALF_STOPPAGE_MIN[period]
            self.half_end = (45 + max(0.5, self.rng.gauss(mu, sd))) * 60
            self.emit("period_start", None)
            kick_side = 0 if period == 1 else 1
            self.restart("kick_off", kick_side, (L / 2, W / 2), dead_time=0.0)
            while self.t < self.half_end:
                self.step()
            self.emit("period_end", None)
        return self.meta(), self.events

    def step(self) -> None:
        holder, ball = self.holder, self.ball
        zone = third(ball[0])
        pressed = False
        if self.rng.random() < P.PRESSURE_RATE[zone]:
            d, dp = self.defender_near(ball)
            self.emit("pressure", self.dfn, d.player, start=dp)
            pressed = True
        self.advance(self.lognorm(*P.DECISION_TIME) * (0.8 if pressed else 1.0))

        if holder.player.position != "GK" and self.try_shot(pressed):
            return
        r = self.rng.random()
        # fouls in the box are rare (they cost a penalty), so defenders hold back there
        fouled = P.FOUL_PER_TOUCH * (0.05 if in_box(ball) else (1.3 if zone != "def" else 0.6))
        if r < fouled:
            self.foul(fouled_side=self.poss_side, at=ball, victim=holder)
            return
        if r < fouled + P.ATTACKING_FOUL_PER_TOUCH:
            self.foul(fouled_side=1 - self.poss_side, at=ball, victim=None)
            return
        mix = P.ACTION_MIX[zone]
        if holder.player.position == "GK":
            action = "pass"
        else:
            action = self.rng.choices(list(mix), list(mix.values()))[0]
        if action == "pass":
            self.open_pass(pressed)
        elif action == "carry":
            self.carry(pressed)
        else:
            self.take_on()

    # ------------------------------------------------------------------ actions
    def try_shot(self, pressed: bool) -> bool:
        x, y = self.ball
        d = math.hypot(L - x, y - W / 2)
        base = 0.0
        for limit, p in P.SHOT_PROPENSITY:
            if d < limit:
                base = p
                break
        if base == 0.0:
            return False
        ang = goal_angle(x, y)
        base *= min(1.0, ang / 0.35)
        if self.arrived in ("cross", "air") and in_box(self.ball):
            base *= 1.25
        state = self.game_state()
        mult = self.strength() ** 1.15 * self.att.home * P.GAME_STATE_SHOTS[state]
        if self.minute() >= P.LATE_GAME_STATE["from_minute"] and state != "level":
            mult *= P.LATE_GAME_STATE[state]
        mult *= 0.85 if pressed else 1.0
        if self.rng.random() < min(0.9, base * mult):
            header = self.arrived in ("cross", "air") and in_box(self.ball) and self.rng.random() < 0.55
            self.shot("open_play", header=header)
            return True
        return False

    def open_pass(self, pressed: bool) -> None:
        zone = third(self.ball[0])
        if self.holder.player.position == "GK":
            subtype = "launch" if self.rng.random() < 0.4 else "ground"
        elif self.arrived == "air" and self.rng.random() < 0.45:
            subtype = "head"
        else:
            mix = dict(P.PASS_MIX[zone])
            if zone == "att" and not (W / 3 < self.ball[1] < 2 * W / 3):
                mix["cross"] = mix.get("cross", 0) + P.CROSS_WIDE_BONUS
            subtype = self.rng.choices(list(mix), list(mix.values()))[0]
        self.pass_(subtype, pressed=pressed)

    def pass_target(self, subtype: str) -> tuple[float, float]:
        x, y = self.ball
        if subtype in ("cross", "corner"):
            return self.rng.uniform(91, 103), self.rng.uniform(22, 46)
        length = self.lognorm(P.PASS_MEDIAN_LENGTH.get(subtype, 15.0), 0.45)
        zone = third(x)
        if subtype in ("through", "launch", "goal_kick"):
            ang = self.rng.gauss(0, 0.35)
        elif subtype == "kick_off":
            ang = math.pi + self.rng.gauss(0, 0.6)
        elif subtype == "throw_in":
            ang = self.rng.gauss(0, 0.9)
        else:
            spread = {"def": 0.9, "mid": 1.1, "att": 1.35}[zone]
            ang = self.rng.gauss(0.0, spread)
            if zone == "att" and self.rng.random() < 0.25:
                ang = math.pi + self.rng.gauss(0, 0.6)   # recycle backwards
        tx, ty = x + length * math.cos(ang), y + length * math.sin(ang)
        if subtype not in ("through",):
            tx = min(tx, 103.0)
        return min(104.0, max(1.0, tx)), min(67.0, max(1.0, ty))

    def completion(self, subtype: str, pressed: bool, length: float, passer_op: OnPitch) -> float:
        passer = passer_op.player
        p = P.PASS_COMPLETION.get(subtype, 0.85)
        odds = p / (1 - p)
        # pressed passes lose odds; unpressed ones gain just enough that the mix keeps the calibrated average
        odds *= P.PRESSURE_ODDS if pressed else UNPRESSED_ODDS
        med = P.PASS_MEDIAN_LENGTH.get(subtype, 15.0)
        odds *= (med / max(length, 1.0)) ** 0.5
        odds *= passer.attributes.passing * self.strength() ** 0.08
        odds *= 1 - P.FATIGUE_PASS * self.fatigue(passer_op)
        return odds / (1 + odds)

    def pass_(self, subtype: str, pressed: bool = False, tags: list[str] | None = None) -> None:
        start = self.ball
        target = self.pass_target(subtype)
        length = math.dist(start, target)
        passer = self.holder
        receiver = self.pick_near(self.att, target, start[0], exclude=passer)
        sp = P.BALL_SPEED_KMH.get(subtype, (45, 9))
        speed = max(15.0, self.rng.gauss(*sp))
        travel = round(length / (speed / 3.6), 2)
        tags = list(tags or [])
        if pressed:
            tags.append("under_pressure")
        # offside on balls in behind
        off_p = P.OFFSIDE_THROUGH if subtype == "through" else (P.OFFSIDE_HIGH if subtype == "high" else 0.0)
        if off_p and target[0] > 60 and self.rng.random() < off_p:
            self.emit("pass", self.att, passer.player, start, target, subtype=subtype, outcome="offside",
                      related_player_id=receiver.player.player_id, speed_kmh=round(speed, 1), duration_s=travel,
                      tags=tags)
            self.advance(travel)
            self.emit("offside", self.att, receiver.player, start=target)
            self.restart("free_kick", 1 - self.poss_side, flip(target), dead_time=self.dead("offside"))
            return
        p = self.completion(subtype, pressed, length, passer)
        if self.rng.random() < p:
            idx = self.emit("pass", self.att, passer.player, start, target, subtype=subtype, outcome="complete",
                            related_player_id=receiver.player.player_id, speed_kmh=round(speed, 1),
                            duration_s=travel, tags=tags)
            self.advance(travel)
            self.last_pass_idx = idx
            arrived = "cross" if subtype in ("cross", "corner") else (
                "air" if subtype in ("high", "launch", "goal_kick") else "ground")
            if arrived == "air" and self.rng.random() < 0.55:
                d, dp = self.defender_near(target)
                self.emit("aerial_duel", self.att, receiver.player, start=target, outcome="won",
                          related_player_id=d.player.player_id)
            self.holder, self.ball, self.arrived = receiver, target, arrived
            return
        self.emit("pass", self.att, passer.player, start, target, subtype=subtype, outcome="incomplete",
                  related_player_id=receiver.player.player_id, speed_kmh=round(speed, 1), duration_s=travel,
                  tags=tags)
        self.advance(travel)
        self.failed_pass(subtype, start, target)

    def failed_pass(self, subtype: str, start, target) -> None:
        rng = self.rng
        if subtype in ("cross", "corner"):
            d, dp = self.defender_near(target)
            r = rng.random()
            if r < 0.14:
                self.emit("clearance", self.dfn, d.player, start=dp, outcome="out")
                self.restart("corner", self.poss_side, None)
            elif r < 0.30:
                self.emit("clearance", self.dfn, d.player, start=dp, outcome="out")
                self.restart("throw_in", self.poss_side, (rng.uniform(70, 95), rng.choice((0.0, W))))
            elif r < 0.42:
                self.emit("ball_out", self.att, self.holder.player, start=(L, target[1]))
                self.restart("goal_kick", 1 - self.poss_side, None)
            elif r < 0.42 + 0.58 * P.CORNER_SECOND_BALL:
                self.emit("clearance", self.dfn, d.player, start=dp)
                loc = (rng.uniform(76, 90), rng.uniform(14, 54))
                rec = self.pick_near(self.att, loc, loc[0])
                self.emit("ball_recovery", self.att, rec.player, start=loc)
                self.holder, self.ball, self.arrived = rec, loc, "ground"
            else:
                self.emit("clearance", self.dfn, d.player, start=dp)
                loc = (rng.uniform(20, 45), rng.uniform(8, 60))     # defender's frame
                rec = self.pick_near(self.dfn, loc, loc[0])
                self.emit("ball_recovery", self.dfn, rec.player, start=loc)
                self.turnover(rec, loc, "recovery")
            return
        near_line = target[1] < 4 or target[1] > W - 4
        p_out = 0.17 + (0.45 if near_line else 0.0) + (0.30 if subtype in ("high", "launch", "goal_kick") else 0.0)
        if target[0] > 100:
            p_out += 0.3
        r = rng.random()
        if r < p_out:
            self.emit("ball_out", self.att, self.holder.player, start=target)
            if target[0] > 100 and self.rng.random() < 0.85:
                self.restart("goal_kick", 1 - self.poss_side, None)
            else:
                tx = min(100.0, target[0])
                self.restart("throw_in", 1 - self.poss_side, flip((tx, 0.0 if target[1] < W / 2 else W)))
            return
        u = rng.uniform(0.45, 1.0)
        pt = (start[0] + u * (target[0] - start[0]), start[1] + u * (target[1] - start[1]))
        d, dp = self.defender_near(pt)
        if rng.random() < 0.72:
            self.emit("interception", self.dfn, d.player, start=dp)
            self.turnover(d, dp, "interception")
        else:   # loose ball after a contest
            if subtype in ("high", "launch", "goal_kick", "head"):
                self.emit("aerial_duel", self.dfn, d.player, start=dp, outcome="won",
                          related_player_id=self.holder.player.player_id)
            if rng.random() < 0.6:
                self.emit("ball_recovery", self.dfn, d.player, start=dp)
                self.turnover(d, dp, "recovery")
            else:
                rec = self.pick_near(self.att, pt, pt[0])
                self.emit("ball_recovery", self.att, rec.player, start=pt)
                self.holder, self.ball, self.arrived = rec, pt, "ground"

    def carry(self, pressed: bool) -> None:
        x, y = self.ball
        dist = self.lognorm(7.0, 0.5)
        ang = self.rng.gauss(0, 0.7)
        end = clamp_pt(min(103.0, x + dist * math.cos(ang)), min(66.0, max(2.0, y + dist * math.sin(ang))))
        dur = round(math.dist((x, y), end) / self.rng.uniform(4.5, 7.0), 2)
        tags = ["under_pressure"] if pressed else []
        if self.rng.random() < P.CARRY_LOSS * (1.5 if pressed else 1.0):
            d, dp = self.defender_near(end)
            self.emit("carry", self.att, self.holder.player, (x, y), end, duration_s=dur, tags=tags)
            self.advance(dur)
            self.emit("tackle", self.dfn, d.player, start=dp, outcome="won",
                      related_player_id=self.holder.player.player_id)
            self.turnover(d, dp, "tackle")
            return
        self.emit("carry", self.att, self.holder.player, (x, y), end, duration_s=dur, tags=tags)
        self.advance(dur)
        self.ball, self.arrived = end, "ground"

    def take_on(self) -> None:
        x, y = self.ball
        d, dp = self.defender_near(self.ball)
        if self.rng.random() < P.FOUL_ON_TAKE_ON * (0.10 if in_box(self.ball) else 1.0):
            self.foul(fouled_side=self.poss_side, at=self.ball, victim=self.holder, by=d)
            return
        odds_won = P.TAKE_ON["won"] / P.TAKE_ON["lost"] * self.strength() ** 0.15 \
            * self.holder.player.attributes.dribbling * (1 - P.FATIGUE_DUEL * self.fatigue(self.holder)) \
            / (d.player.attributes.defending * (1 - P.FATIGUE_DUEL * self.fatigue(d)))
        r = self.rng.random()
        self.advance(self.rng.uniform(0.8, 2.0))
        if r < P.TAKE_ON["neutral"]:
            self.emit("take_on", self.att, self.holder.player, start=self.ball, outcome="neutral",
                      related_player_id=d.player.player_id)
            if self.rng.random() < 0.5:
                self.emit("ball_recovery", self.dfn, d.player, start=dp)
                self.turnover(d, dp, "recovery")
            return
        p_won = odds_won / (1 + odds_won)
        if self.rng.random() < p_won:
            end = clamp_pt(min(103.0, x + self.rng.uniform(3, 8)), y + self.rng.gauss(0, 3))
            self.emit("take_on", self.att, self.holder.player, start=(x, y), end=end, outcome="won",
                      related_player_id=d.player.player_id)
            self.emit("tackle", self.dfn, d.player, start=dp, outcome="lost",
                      related_player_id=self.holder.player.player_id)
            self.ball = end
        else:
            self.emit("take_on", self.att, self.holder.player, start=(x, y), outcome="lost",
                      related_player_id=d.player.player_id)
            self.emit("tackle", self.dfn, d.player, start=dp, outcome="won",
                      related_player_id=self.holder.player.player_id)
            self.turnover(d, dp, "tackle")

    # ------------------------------------------------------------------ shots
    def shot(self, kind: str, header: bool = False, tags: list[str] | None = None) -> None:
        side, shooter = self.att, self.holder
        x, y = self.ball
        tags = list(tags or [])
        if kind == "penalty":
            p_goal = P.PENALTY_CONVERSION * shooter.player.attributes.finishing ** 0.1
        elif kind == "free_kick":
            p_goal = P.DIRECT_FK_CONVERSION * shooter.player.attributes.finishing
        else:
            p_goal = xg(x, y, header) * P.XG_SCALE * shooter.player.attributes.finishing * side.quality
        if kind == "open_play":
            tired = sum(self.fatigue(o) for o in self.dfn.on) / max(1, len(self.dfn.on))
            p_goal *= P.HALF_CONVERSION[self.period] * (1 + P.FATIGUE_DEFENCE_XG * tired)
        p_goal = min(0.95, p_goal)
        if kind == "open_play" and self.poss_origin in ("interception", "tackle", "recovery") \
                and self.t - self.poss_start_t < 15:
            tags.append("counter_attack")
        pf = shooter.player.foot
        body = "head" if header else (("left_foot" if pf == "left" else "right_foot") if self.rng.random() < 0.8
                                      else ("right_foot" if pf == "left" else "left_foot"))
        speed = max(20.0, self.rng.gauss(*P.BALL_SPEED_KMH["header_shot" if header else "shot"]))
        key = self.last_pass_idx
        if key is not None and self.events[key]["team_id"] == side.id and len(self.events) - key <= 3:
            self.events[key].setdefault("tags", []).append("key_pass")
        self.advance(0.6)
        gk = self.dfn.keeper()
        goal_pt = (L, W / 2 + self.rng.uniform(-3.4, 3.4))
        if self.rng.random() < p_goal:
            self.emit("shot", side, shooter.player, (x, y), goal_pt, subtype=kind, outcome="goal", body_part=body,
                      speed_kmh=round(speed, 1), tags=tags)
            if key is not None and "key_pass" in self.events[key].get("tags", []):
                self.events[key]["tags"].append("assist")
            self.score[self.poss_side] += 1
            self.restart("kick_off", 1 - self.poss_side, (L / 2, W / 2), dead_time=self.dead("kick_off_goal"))
            return
        miss = P.SHOT_OUTCOME_GIVEN_MISS
        outcome = self.rng.choices(list(miss), list(miss.values()))[0]
        if kind == "penalty":
            outcome = "saved" if self.rng.random() < 0.7 else "off_target"
        if outcome == "off_target" and self.rng.random() < P.OFF_TARGET_POST:
            outcome = "post"
        wide = (L, W / 2 + self.rng.choice((-1, 1)) * self.rng.uniform(4, 12))
        end = goal_pt if outcome in ("saved", "post") else ((x + 3, y) if outcome == "blocked" else wide)
        self.emit("shot", side, shooter.player, (x, y), end, subtype=kind, outcome=outcome, body_part=body,
                  speed_kmh=round(speed, 1), tags=tags)
        rng = self.rng
        if outcome == "saved":
            res = rng.choices(list(P.SAVE_RESULT), list(P.SAVE_RESULT.values()))[0]
            self.emit("save", self.dfn, gk.player, start=(1.0, W / 2), outcome="held" if res == "held" else "parried",
                      related_player_id=shooter.player.player_id)
            if res == "held":
                self.advance(rng.uniform(4, 9))
                self.turnover(gk, (6.0, W / 2), "keeper")
            elif res == "corner":
                self.restart("corner", self.poss_side, None)
            else:
                self.loose_in_box()
        elif outcome == "blocked":
            if rng.random() < P.BLOCK_RESULT["corner"]:
                self.restart("corner", self.poss_side, None)
            else:
                self.loose_in_box(edge=True)
        elif outcome == "post":
            self.loose_in_box()
        else:
            self.restart("goal_kick", 1 - self.poss_side, None)

    def loose_in_box(self, edge: bool = False) -> None:
        loc = (self.rng.uniform(84, 96) if edge else self.rng.uniform(92, 100), self.rng.uniform(18, 50))
        if self.rng.random() < 0.38:
            rec = self.pick_near(self.att, loc, loc[0])
            self.emit("ball_recovery", self.att, rec.player, start=loc)
            self.holder, self.ball, self.arrived = rec, loc, "ground"
        else:
            fl = flip(loc)
            rec = self.pick_near(self.dfn, fl, fl[0], no_gk=False)
            self.emit("clearance", self.dfn, rec.player, start=fl)
            far = (self.rng.uniform(25, 50), self.rng.uniform(5, 63))
            nxt = self.pick_near(self.dfn, far, far[0])
            self.emit("ball_recovery", self.dfn, nxt.player, start=far)
            self.turnover(nxt, far, "recovery")

    # ------------------------------------------------------------------ fouls, cards, restarts
    def foul(self, fouled_side: int, at, victim: OnPitch | None, by: OnPitch | None = None) -> None:
        """at is in the current possessor's frame."""
        offender_side = self.sides[1 - fouled_side]
        if fouled_side == self.poss_side:
            spot = at
            offender = by or self.defender_near(at)[0]
            off_pt = flip(at)
        else:
            spot = flip(at)
            offender = self.holder
            off_pt = at
        self.emit("foul", offender_side, offender.player, start=off_pt,
                  related_player_id=victim.player.player_id if victim else None)
        self.card_check(offender_side, offender)
        if fouled_side == self.poss_side and in_box(spot):
            self.restart("penalty", fouled_side, (L - 11.0, W / 2))
        else:
            self.restart("free_kick", fouled_side, spot)

    def card_check(self, side: Side, op: OnPitch) -> None:
        if op not in side.on:
            return
        r = self.rng.random()
        late = 0.55 + 0.9 * min(self.minute(), 95) / 95
        if r < P.RED_PER_FOUL:
            self.emit("card", side, op.player, subtype="red")
            self.send_off(side, op)
        elif r < P.RED_PER_FOUL + P.YELLOW_PER_FOUL * late * (P.BOOKED_CAUTION if op.yellow else 1.0):
            if op.yellow:
                self.emit("card", side, op.player, subtype="second_yellow")
                self.send_off(side, op)
            else:
                op.yellow = True
                self.emit("card", side, op.player, subtype="yellow")
        else:
            return
        self.advance(self.dead("card") / 4)

    def send_off(self, side: Side, op: OnPitch) -> None:
        if op.player.position == "GK":    # an outfield player makes way for the reserve keeper if one is left
            return self._keeper_sent_off(side, op)
        side.on.remove(op)
        side.attack *= 0.85
        side.defence *= 1.18

    def _keeper_sent_off(self, side: Side, op: OnPitch) -> None:
        spare = next((p for p in side.bench if p.position == "GK"), None)
        out = next((o for o in side.on if o.player.position in ("ST", "AM", "LW", "RW", "CM")), None)
        side.on.remove(op)
        if spare and out and side.sub_minutes:
            side.on.remove(out)
            side.bench.remove(spare)
            side.on.append(OnPitch(spare, op.slot, on_minute=self.minute()))
            side.sub_minutes.pop()
            self.emit("substitution", side, out.player, related_player_id=spare.player_id)
        side.attack *= 0.85
        side.defence *= 1.18

    def dead(self, kind: str) -> float:
        med, sd = P.RESTART_TIME[kind]
        return max(3.0, self.rng.gauss(med, sd))

    def subs_due(self) -> None:
        for side in self.sides:
            while self.period == 2 and side.sub_minutes and self.minute() >= side.sub_minutes[0]:
                side.sub_minutes.pop(0)
                outs = [o for o in side.on if o.player.position != "GK"]
                if not outs:
                    break
                # tired legs come off first; attackers and midfielders more than defenders
                w = [(3 if o.player.role == "FW" else (2 if o.player.role == "MD" else 1)) * (0.02 + self.fatigue(o))
                     for o in outs]
                out = self.rng.choices(outs, w)[0]
                cands = [p for p in side.bench if p.position == out.player.position] or \
                        [p for p in side.bench if p.role == out.player.role and p.position != "GK"] or \
                        [p for p in side.bench if p.position != "GK"]
                if not cands:
                    break
                inn = cands[0]
                side.bench.remove(inn)
                new = OnPitch(inn, out.slot, on_minute=self.minute())
                side.on[side.on.index(out)] = new
                if self.holder is out:
                    self.holder = new
                self.emit("substitution", side, out.player, related_player_id=inn.player_id)
                self.advance(self.dead("substitution") / 3)

    def restart(self, kind: str, side_idx: int, spot, dead_time: float | None = None) -> None:
        if self.t >= self.half_end and kind != "penalty":
            return
        self.advance(self.dead(kind if kind != "kick_off" else "throw_in") if dead_time is None else dead_time)
        self.subs_due()
        side = self.sides[side_idx]
        origin = kind
        rng = self.rng
        if kind == "kick_off":
            taker = side.find(("ST", "AM", "CM")) or side.on[-1]
            self.change_possession(side_idx, taker, spot, origin)
            self.pass_("kick_off")
        elif kind == "throw_in":
            x, y = spot
            spot = (min(100.0, max(2.0, x)), 0.5 if y < W / 2 else W - 0.5)
            taker = self.pick_near(side, spot, spot[0])
            self.change_possession(side_idx, taker, spot, origin)
            self.pass_("throw_in", tags=["set_piece"])
        elif kind == "goal_kick":
            gk = side.keeper()
            self.change_possession(side_idx, gk, (5.5, W / 2), origin)
            if rng.random() < 0.5:
                self.pass_("ground", tags=["set_piece", "goal_kick"])
            else:
                self.pass_("goal_kick", tags=["set_piece"])
        elif kind == "corner":
            top = rng.random() < 0.5
            loc = (L - 0.5, 0.5 if top else W - 0.5)
            taker = side.find(("LW", "RW", "AM", "CM")) or side.on[-1]
            self.change_possession(side_idx, taker, loc, origin)
            self.set_piece_cross("corner", P.CORNER_DIRECT_SHOT)
        elif kind == "penalty":
            taker = max((o for o in side.on if o.player.position != "GK"),
                        key=lambda o: o.player.attributes.finishing)
            self.change_possession(side_idx, taker, (L - 11.0, W / 2), origin)
            self.shot("penalty", tags=["set_piece"])
        else:   # free kick
            x, y = clamp_pt(*spot)
            d = math.hypot(L - x, y - W / 2)
            taker = self.pick_near(side, (x, y), x)
            self.change_possession(side_idx, taker, (x, y), origin)
            if x > 2 * L / 3 and d < 32 and abs(y - W / 2) < 18 and rng.random() < 0.38:
                self.advance(self.dead("direct_free_kick") - self.dead("free_kick"))
                self.shot("free_kick", tags=["set_piece"])
            elif x > 2 * L / 3 and rng.random() < 0.62:
                self.set_piece_cross("free_kick", P.FK_CROSS_DIRECT_SHOT, sub="free_kick_cross")
            else:
                self.pass_("free_kick", tags=["set_piece"])

    def set_piece_cross(self, kind: str, direct_shot: float, sub: str | None = None) -> None:
        start = self.ball
        target = self.pass_target("corner")
        sp = max(20.0, self.rng.gauss(*P.BALL_SPEED_KMH["corner"]))
        travel = round(math.dist(start, target) / (sp / 3.6), 2)
        taker = self.holder
        aerial = sorted((o for o in self.att.on if o is not taker and o.player.position != "GK"),
                        key=lambda o: -o.player.attributes.aerial * o.player.height_cm)[:5]
        if self.rng.random() < direct_shot * self.strength() ** 0.5 * self.att.home:
            header = self.rng.choice(aerial)
            delivery = kind if kind == "corner" else "cross"
            idx = self.emit("pass", self.att, taker.player, start, target, subtype=delivery,
                            outcome="complete", related_player_id=header.player.player_id, speed_kmh=round(sp, 1),
                            duration_s=travel, tags=["set_piece"] + ([sub] if sub else []))
            self.advance(travel)
            self.last_pass_idx = idx
            self.holder, self.ball, self.arrived = header, target, "cross"
            self.shot("open_play", header=self.rng.random() < 0.8, tags=["set_piece"])
            return
        recv = self.rng.choice(aerial)
        self.emit("pass", self.att, taker.player, start, target, subtype=kind if kind == "corner" else "cross",
                  outcome="incomplete", related_player_id=recv.player.player_id, speed_kmh=round(sp, 1),
                  duration_s=travel, tags=["set_piece"] + ([sub] if sub else []))
        self.advance(travel)
        self.failed_pass("corner", start, target)


def simulate(home: Team, away: Team, seed: int, match_id: str | None = None, round_no: int = 1,
             kickoff_utc: str | None = None):
    return MatchSim(home, away, seed, match_id, round_no, kickoff_utc).run()
