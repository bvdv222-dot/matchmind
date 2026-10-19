"""Profile SkillCorner physical aggregates + one match of 10fps tracking for generator movement parameters."""
import csv, json, sys, os, math, statistics as st
from collections import defaultdict, Counter

root = sys.argv[1]

# ---- season physical aggregates (per-90 normalised by position group)
rows = list(csv.DictReader(open(os.path.join(root, "physical.csv"), encoding="utf-8")))
print(f"== SkillCorner physical aggregates: {len(rows)} player-seasons (A-League 24/25, >60 min performances)")
byg = defaultdict(list)
for r in rows:
    byg[r["position_group"]].append(r)
cols = [("total_metersperminute_full_all", "m/min", 1), ("hsr_distance_full_all", "HSR m/90", None),
        ("sprint_distance_full_all", "sprint m/90", None), ("sprint_count_full_all", "sprints/90", None),
        ("highaccel_count_full_all", "hi-accel/90", None), ("psv99", "PSV99 km/h", 1)]
print(f"  {'group':22s} n   " + "  ".join(f"{c[1]:>12s}" for c in cols))
for g, rs in sorted(byg.items()):
    out = []
    for col, lab, raw in cols:
        vals = []
        for r in rs:
            try:
                v = float(r[col])
            except ValueError:
                continue
            # per-match totals in these aggregates are averages per match already when count_match>0
            vals.append(v)
        out.append(f"{st.mean(vals):12.1f}" if vals else f"{'-':>12s}")
    print(f"  {g:22s} {len(rs):3d} " + "  ".join(out))

# ---- tracking: speeds, team shape, ball speed
meta = json.load(open(os.path.join(root, "match.json"), encoding="utf-8"))
team_of = {p["id"]: p["team_id"] for p in meta["players"]}
role_of = {p["id"]: p["player_role"]["acronym"] for p in meta["players"]}
home = meta["home_team"]["id"]
print(f"\n== tracking match {meta['id']}: {meta['home_team']['short_name']} v {meta['away_team']['short_name']}, pitch {meta['pitch_length']}x{meta['pitch_width']}")

prev = {}
speeds = defaultdict(list)
dist = defaultdict(float)
ball_speed = []
width, depth, centroid_gap = [], [], []
pprev_ball = None
frames = 0
step = 1
with open(os.path.join(root, "tracking.jsonl"), encoding="utf-8") as fh:
    for line in fh:
        f = json.loads(line)
        if f["period"] is None or not f["player_data"]:
            continue
        frames += 1
        t = f["timestamp"]
        cur = {}
        for p in f["player_data"]:
            cur[p["player_id"]] = (p["x"], p["y"])
            if p["player_id"] in prev:
                (x0, y0), fr0 = prev[p["player_id"]]
                if f["frame"] - fr0 == 1:
                    d = math.hypot(p["x"] - x0, p["y"] - y0)
                    v = d * 10 * 3.6  # 10 fps -> km/h
                    if v < 40:
                        speeds[p["player_id"]].append(v)
                        dist[p["player_id"]] += d
        for pid, xy in cur.items():
            prev[pid] = (xy, f["frame"])
        b = f["ball_data"]
        if b["x"] is not None:
            if pprev_ball and f["frame"] - pprev_ball[2] == 1:
                bv = math.hypot(b["x"] - pprev_ball[0], b["y"] - pprev_ball[1]) * 36
                if bv < 150:
                    ball_speed.append(bv)
            pprev_ball = (b["x"], b["y"], f["frame"])
        if frames % 25 == 0:  # team shape sampled every 2.5 s
            for tid in {team_of.get(pid) for pid in cur}:
                pts = [xy for pid, xy in cur.items() if team_of.get(pid) == tid and role_of.get(pid) != "GK"]
                if len(pts) >= 9:
                    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                    width.append(max(ys) - min(ys)); depth.append(max(xs) - min(xs))

print(f"  frames used {frames} ({frames/600:.0f} min at 10fps)")
allv = [v for vs in speeds.values() for v in vs]
bands = [(0, 7, "walk"), (7, 14.4, "jog"), (14.4, 19.8, "run"), (19.8, 25.2, "HSR"), (25.2, 99, "sprint")]
print("  time share by speed band: " + ", ".join(f"{n} {sum(lo <= v < hi for v in allv)/len(allv):.0%}" for lo, hi, n in bands))
outfield = [pid for pid in speeds if role_of.get(pid) != "GK" and len(speeds[pid]) > 0.8 * frames]
tops = sorted(st.quantiles(speeds[p], n=1000)[-1] for p in outfield)
print(f"  outfield full-match players: {len(outfield)}  m/min median {st.median(dist[p] / (len(speeds[p]) / 600) for p in outfield):.0f}  p99.9 speed km/h median {st.median(tops):.1f} (range {tops[0]:.1f}-{tops[-1]:.1f})")
bym = defaultdict(list)
for p in outfield:
    bym[role_of[p]].append(dist[p] / (len(speeds[p]) / 600))
print("  m/min by role: " + ", ".join(f"{r} {st.mean(v):.0f}" for r, v in sorted(bym.items())))
print(f"  ball speed km/h (moving >5): median {st.median([b for b in ball_speed if b > 5]):.0f}  p95 {st.quantiles([b for b in ball_speed if b > 5], n=20)[-1]:.0f}")
print(f"  team shape (outfield 10): width median {st.median(width):.0f} m, depth median {st.median(depth):.0f} m")

# ---- dynamic events: what extra 'physical-context' events look like
dyn = list(csv.DictReader(open(os.path.join(root, "dyn.csv"), encoding="utf-8")))
print(f"\n== dynamic events: {len(dyn)} rows")
print("  types: " + ", ".join(f"{k} {v}" for k, v in Counter(r["event_type"] for r in dyn).most_common()))
print("  off-ball run subtypes: " + ", ".join(f"{k} {v}" for k, v in Counter(r["event_subtype"] for r in dyn if r["event_type"] == "off_ball_run").most_common(10)))
print("  on-ball engagement subtypes: " + ", ".join(f"{k} {v}" for k, v in Counter(r["event_subtype"] for r in dyn if r["event_type"] == "on_ball_engagement").most_common(8)))
