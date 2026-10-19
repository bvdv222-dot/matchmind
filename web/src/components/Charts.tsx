import type { MatchMeta, TeamView, Window, WinProb } from "../types";
import { PitchSvg } from "./Pitch";

const W = 320, H = 120, PAD = 22;

function axis(maxMin: number) {
  return [0, 15, 30, 45, 60, 75, 90].filter(m => m <= Math.max(maxMin, 45)).map(m => {
    const x = PAD + ((W - 2 * PAD) * m) / Math.max(maxMin, 45);
    return <g key={m}><line x1={x} y1={H - PAD} x2={x} y2={H - PAD + 3} stroke="var(--muted)" />
      <text x={x} y={H - 6} fontSize={9} textAnchor="middle" fill="var(--muted)">{m}'</text></g>;
  });
}

/** Cumulative xG by five-minute window for both teams. */
export function XgFlow({ windows, meta }: { windows: Window[]; meta: MatchMeta }) {
  if (!windows.length) return null;
  const end = windows[windows.length - 1].to_min;
  let h = 0, a = 0;
  const pts = windows.map(w => ({ m: w.to_min, h: (h += w.home_xg), a: (a += w.away_xg) }));
  const max = Math.max(0.5, h, a);
  const X = (m: number) => PAD + ((W - 2 * PAD) * m) / Math.max(end, 45);
  const Y = (v: number) => H - PAD - ((H - 2 * PAD) * v) / max;
  const line = (k: "h" | "a") => `M${X(0)},${Y(0)} ` + pts.map(p => `L${X(p.m)},${Y(p[k])}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label="xG flow">
      <path d={line("h")} fill="none" stroke={meta.home.colors.primary} strokeWidth={2.2} />
      <path d={line("a")} fill="none" stroke={meta.away.colors.primary} strokeWidth={2.2} strokeDasharray="5 3" />
      <text x={W - PAD} y={Y(h) - 4} fontSize={10} textAnchor="end" fill="var(--text)">{meta.home.short_name} {h.toFixed(2)}</text>
      <text x={W - PAD} y={Y(a) + 12} fontSize={10} textAnchor="end" fill="var(--text)">{meta.away.short_name} {a.toFixed(2)}</text>
      {axis(end)}
    </svg>
  );
}

/** Home win / draw / away probability through the match. */
export function WinProbChart({ history, meta }: { history: (WinProb & { minute: number })[]; meta: MatchMeta }) {
  if (history.length < 2) return null;
  const end = history[history.length - 1].minute;
  const X = (m: number) => PAD + ((W - 2 * PAD) * m) / Math.max(end, 45);
  const Y = (v: number) => H - PAD - (H - 2 * PAD) * v;
  const top = history.map(p => `${X(p.minute)},${Y(p.home)}`).join(" ");
  const mid = history.map(p => `${X(p.minute)},${Y(p.home + p.draw)}`).join(" ");
  const first = X(history[0].minute), last = X(end);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label="Win probability over time">
      <polygon points={`${first},${Y(0)} ${top} ${last},${Y(0)}`} fill={meta.home.colors.primary} opacity={0.85} />
      <polygon points={`${top} ${[...history].reverse().map(p => `${X(p.minute)},${Y(p.home + p.draw)}`).join(" ")}`}
               fill="var(--draw)" opacity={0.8} />
      <polygon points={`${mid} ${last},${Y(1)} ${first},${Y(1)}`} fill={meta.away.colors.primary} opacity={0.85} />
      {axis(end)}
    </svg>
  );
}

/** Field tilt (bars, home share of final-third passes) and the chaos index (dots, 1.0 = typical). */
export function Rhythm({ windows, meta }: { windows: Window[]; meta: MatchMeta }) {
  if (!windows.length) return null;
  const n = windows.length, bw = (W - 2 * PAD) / Math.max(n, 19);
  const mid = H / 2;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label="Field tilt and chaos index">
      <line x1={PAD} x2={W - PAD} y1={mid} y2={mid} stroke="var(--muted)" strokeDasharray="2 3" />
      {windows.map((w, i) => {
        const v = w.home_field_tilt - 0.5;
        const h = Math.abs(v) * (H - 2 * PAD);
        const x = PAD + i * bw;
        const chaosY = mid - (Math.min(w.chaos_index, 2) - 1) * 40;
        return (
          <g key={i}>
            <rect x={x + 1} width={bw - 2} y={v > 0 ? mid - h : mid} height={h}
                  fill={v > 0 ? meta.home.colors.primary : meta.away.colors.primary} opacity={0.85}>
              <title>{`${w.from_min}-${w.to_min}': ${meta.home.short_name} ${Math.round(100 * w.home_field_tilt)}% of final-third passes, chaos ${w.chaos_index}`}</title>
            </rect>
            <circle cx={x + bw / 2} cy={chaosY} r={2.2} fill={w.chaos_index >= 1.3 ? "var(--warn)" : "var(--text)"} />
          </g>
        );
      })}
      <text x={PAD} y={12} fontSize={9} fill="var(--muted)">▲ {meta.home.short_name} on top</text>
      <text x={PAD} y={H - 4} fontSize={9} fill="var(--muted)">▼ {meta.away.short_name} on top · dots: chaos index</text>
    </svg>
  );
}

/** Average positions and passing links, team attacking left to right. */
export function PassNetwork({ team, color }: { team: TeamView; color: { primary: string; secondary: string } }) {
  const { nodes, edges } = team.network;
  const maxInv = Math.max(1, ...Object.values(nodes).map(n => n.involvement));
  const maxP = Math.max(1, ...edges.map(e => e.passes));
  return (
    <PitchSvg className="network">
      {edges.map((e, i) => {
        const a = nodes[e.from], b = nodes[e.to];
        if (!a || !b) return null;
        return <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="#fff" strokeOpacity={0.15 + 0.6 * (e.passes / maxP)}
                     strokeWidth={0.2 + 1.4 * (e.passes / maxP)} />;
      })}
      {Object.entries(nodes).map(([pid, n]) => (
        <g key={pid} transform={`translate(${n.x},${n.y})`}>
          <circle r={1 + 2.2 * (n.involvement / maxInv)} fill={color.primary} stroke={color.secondary} strokeWidth={0.4} />
          <text y={-3.4} fontSize={2.1} textAnchor="middle" fill="#fff">{n.name}</text>
        </g>
      ))}
    </PitchSvg>
  );
}
