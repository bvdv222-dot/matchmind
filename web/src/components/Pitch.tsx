import type { ReactNode } from "react";
import { kits } from "../kit";
import type { Frame, MatchMeta } from "../types";

const L = 105, W = 68;

/** Pitch markings in metres (viewBox 105 x 68, absolute frame: home attacks right in the first half). */
export function PitchLines() {
  const s = { fill: "none", stroke: "var(--pitch-line)", strokeWidth: 0.35 };
  return (
    <g>
      <rect x={0} y={0} width={L} height={W} {...s} />
      <line x1={L / 2} y1={0} x2={L / 2} y2={W} {...s} />
      <circle cx={L / 2} cy={W / 2} r={9.15} {...s} />
      <circle cx={L / 2} cy={W / 2} r={0.4} fill="var(--pitch-line)" />
      {[0, 1].map(side => {
        const x0 = side ? L - 16.5 : 0, x6 = side ? L - 5.5 : 0, spot = side ? L - 11 : 11;
        return (
          <g key={side}>
            <rect x={x0} y={W / 2 - 20.16} width={16.5} height={40.32} {...s} />
            <rect x={x6} y={W / 2 - 9.16} width={5.5} height={18.32} {...s} />
            <circle cx={spot} cy={W / 2} r={0.4} fill="var(--pitch-line)" />
            <rect x={side ? L : -1.6} y={W / 2 - 3.66} width={1.6} height={7.32} {...s} />
          </g>
        );
      })}
    </g>
  );
}

export function PitchSvg({ children, className }: { children?: ReactNode; className?: string }) {
  return (
    <svg className={className} viewBox={`-3 -3 ${L + 6} ${W + 6}`} role="img" aria-label="Pitch">
      <rect x={-3} y={-3} width={L + 6} height={W + 6} fill="var(--pitch)" rx={1.5} />
      {[...Array(10)].map((_, i) => (
        <rect key={i} x={(i * L) / 10} y={0} width={L / 10} height={W} fill={i % 2 ? "var(--pitch-stripe)" : "transparent"} />
      ))}
      <PitchLines />
      {children}
    </svg>
  );
}

type Props = { frame: Frame | null; meta: MatchMeta | null; focus: string | null; onPick: (pid: string) => void };

/** Live positions from the 2 Hz frames; click a player to follow them. */
export function LivePitch({ frame, meta, focus, onPick }: Props) {
  if (!meta) return <PitchSvg className="pitch" />;
  const kit = kits(meta);
  const shirt: Record<string, number> = {};
  for (const s of [meta.home, meta.away]) for (const p of [...s.starting, ...s.bench]) shirt[p.player_id] = p.shirt;
  return (
    <PitchSvg className="pitch">
      {frame?.players.map(p => {
        const c = kit[p.team_id];
        const isFocus = p.player_id === focus;
        return (
          <g key={p.player_id} className="player" transform={`translate(${p.x},${p.y})`} onClick={() => onPick(p.player_id)}>
            {isFocus && <circle r={3.2} fill="none" stroke="var(--accent)" strokeWidth={0.5} className="pulse" />}
            <circle r={1.6} fill={c.fill} stroke={c.trim} strokeWidth={0.45} />
            <text y={0.6} textAnchor="middle" fontSize={1.6} fill={c.trim} fontWeight={700}>{shirt[p.player_id]}</text>
          </g>
        );
      })}
      {frame && (
        <g transform={`translate(${frame.ball.x},${frame.ball.y})`}>
          <ellipse cx={0.4} cy={0.5 + frame.ball.z * 0.15} rx={0.9} ry={0.5} fill="rgba(0,0,0,.35)" />
          <circle r={0.75 + frame.ball.z * 0.04} cy={-frame.ball.z * 0.25} fill="#fff" stroke="#111" strokeWidth={0.15} />
        </g>
      )}
    </PitchSvg>
  );
}
