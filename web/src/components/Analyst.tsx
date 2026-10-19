import { useState } from "react";
import { kits } from "../kit";
import type { Dashboard, MatchMeta } from "../types";
import { PassNetwork, Rhythm, WinProbChart, XgFlow } from "./Charts";

const ROWS: [string, string, (v: number) => string][] = [
  ["xg", "xG", v => v.toFixed(2)],
  ["shots", "Shots", v => `${v}`],
  ["shots_on_target", "On target", v => `${v}`],
  ["big_chances", "Big chances", v => `${v}`],
  ["possession_share", "Possession", v => `${Math.round(100 * v)}%`],
  ["field_tilt", "Field tilt", v => `${Math.round(100 * v)}%`],
  ["pass_completion", "Pass completion", v => `${Math.round(100 * v)}%`],
  ["progressive_passes", "Progressive passes", v => `${v}`],
  ["ppda", "PPDA (lower = more pressing)", v => v.toFixed(1)],
  ["pressures", "Pressures", v => `${v}`],
  ["crosses", "Crosses", v => `${v}`],
  ["corners", "Corners", v => `${v}`],
];

function Chip({ words, good, concern }: { words?: string; good?: boolean; concern?: boolean }) {
  if (!words) return null;
  const cls = good ? "good" : concern ? "concern" : "neutral";
  return <span className={`chip ${cls}`} title="Compared with what this team usually does against this kind of opponent, at this stage">{words.replace(" their usual", "")}</span>;
}

export function AnalystView({ d, meta, onTeam, onPlayer }: {
  d: Dashboard; meta: MatchMeta; onTeam: (tid: string) => void; onPlayer: (pid: string) => void;
}) {
  const [netTeam, setNetTeam] = useState(d.home);
  const home = d.teams[d.home], away = d.teams[d.away];
  const kit = kits(meta);
  const color = (tid: string) => ({ primary: kit[tid].fill, secondary: kit[tid].trim });
  return (
    <div className="analyst">
      <section className="panel stats">
        <h3>Team comparison <small>vs their usual</small></h3>
        <table>
          <thead><tr><th>{meta.home.short_name}</th><th></th><th></th><th>{meta.away.short_name}</th></tr></thead>
          <tbody>
            {ROWS.map(([k, label, fmt]) => (
              <tr key={k}>
                <td className="num">{fmt(home.stats[k] ?? 0)} <Chip words={home.vs_expected[k]?.words} good={home.vs_expected[k]?.good_for_team} concern={home.vs_expected[k]?.concern} /></td>
                <td className="label" colSpan={2}>{label}</td>
                <td className="num">{fmt(away.stats[k] ?? 0)} <Chip words={away.vs_expected[k]?.words} good={away.vs_expected[k]?.good_for_team} concern={away.vs_expected[k]?.concern} /></td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="standing">{home.name}: {home.attack_standing.words} attack, {home.defence_standing.words} defence last season ·
          {" "}{away.name}: {away.attack_standing.words} attack, {away.defence_standing.words} defence.</p>
        <div className="team-links">
          <button onClick={() => onTeam(d.home)}>Ask about {meta.home.short_name}</button>
          <button onClick={() => onTeam(d.away)}>Ask about {meta.away.short_name}</button>
        </div>
      </section>

      <section className="panel"><h3>xG flow</h3><XgFlow windows={d.windows} meta={meta} /></section>
      <section className="panel"><h3>Win probability</h3><WinProbChart history={[...d.win_probability_history, { ...d.state.win_probability, minute: d.state.minute, clock: d.state.clock }]} meta={meta} /></section>
      <section className="panel"><h3>Rhythm <small>field tilt and chaos, 5-minute windows</small></h3><Rhythm windows={d.windows} meta={meta} /></section>

      <section className="panel network-panel">
        <h3>Pass network
          <span className="seg">
            {[d.home, d.away].map(tid => (
              <button key={tid} className={netTeam === tid ? "on" : ""} onClick={() => setNetTeam(tid)}>
                {tid === d.home ? meta.home.short_name : meta.away.short_name}
              </button>
            ))}
          </span>
        </h3>
        <PassNetwork team={d.teams[netTeam]} color={color(netTeam)} />
        <p className="small">Hub: {d.teams[netTeam].network.hub.player_id ? d.teams[netTeam].network.nodes[d.teams[netTeam].network.hub.player_id]?.name : "-"} ·
          attacking left to right · line width = passes</p>
      </section>

      <section className="panel">
        <h3>Phases <small>possessions and xG by how they were played</small></h3>
        <table className="phases">
          <thead><tr><th>Phase</th><th>{meta.home.short_name}</th><th>{meta.away.short_name}</th></tr></thead>
          <tbody>
            {Object.keys(home.phases).map(ph => (
              <tr key={ph}><td>{ph}</td>
                <td>{home.phases[ph].count} · {home.phases[ph].xg.toFixed(2)} xG</td>
                <td>{away.phases[ph].count} · {away.phases[ph].xg.toFixed(2)} xG</td></tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="panel">
        <h3>Possession value leaders <small>goals added</small></h3>
        <ol className="leaders">
          {d.top_players.map(p => (
            <li key={p.player_id}><button className="link" onClick={() => onPlayer(p.player_id)}>{p.name}</button>
              <span className="muted"> {p.team}</span><span className="num">{p.value_added >= 0 ? "+" : ""}{p.value_added.toFixed(2)}</span></li>
          ))}
        </ol>
      </section>

      <section className="panel moments">
        <h3>Moments</h3>
        <ul>
          {[...d.moments].reverse().filter(m => m.priority >= 4).slice(0, 14).map(m => (
            <li key={m.moment_id}><span className="note-clock">{m.clock}</span> {m.headline}</li>
          ))}
        </ul>
      </section>
    </div>
  );
}
