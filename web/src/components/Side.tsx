import { useState } from "react";
import { api, type AgentNote } from "../api";
import type { AskResult, MatchMeta, PlayerView } from "../types";

export function PlayerCard({ p, meta }: { p: PlayerView; meta: MatchMeta }) {
  const c = p.team_id === meta.home.team_id ? meta.home.colors : meta.away.colors;
  const m = p.match, ph = p.physical;
  const row = (label: string, v: string | number | undefined) => v !== undefined && <div className="kv"><span>{label}</span><b>{v}</b></div>;
  return (
    <div className="player-card" style={{ borderColor: c.primary }}>
      <div className="pc-head" style={{ background: c.primary, color: c.secondary }}>
        <span className="pc-shirt">{p.shirt}</span>
        <div><div className="pc-name">{p.name}</div><div className="pc-sub">{p.team} · {p.position} · {p.age} · {p.foot}-footed · {p.height_cm} cm</div></div>
      </div>
      <div className="pc-body">
        {row("Possession value", m.value_added !== undefined ? `${m.value_added >= 0 ? "+" : ""}${m.value_added.toFixed(2)} goals` : undefined)}
        {row("Passes", m.passes !== undefined ? `${m.passes_complete ?? 0}/${m.passes} (${Math.round(100 * (m.pass_completion ?? 0))}%)` : undefined)}
        {row("Progressive passes", m.progressive_passes)}
        {row("Key passes", m.key_passes)}
        {row("Shots / xG", m.shots !== undefined ? `${m.shots} / ${(m.xg ?? 0).toFixed(2)}` : undefined)}
        {row("Goals", m.goals)}
        {row("Take-ons won", m.take_ons !== undefined ? `${m.take_ons_won ?? 0}/${m.take_ons}` : undefined)}
        {row("Tackles won / interceptions", m.tackles_won !== undefined || m.interceptions !== undefined ? `${m.tackles_won ?? 0} / ${m.interceptions ?? 0}` : undefined)}
        {row("Distance", ph.distance_m !== undefined ? `${(ph.distance_m / 1000).toFixed(1)} km` : undefined)}
        {row("Top speed", ph.top_speed_kmh !== undefined ? `${ph.top_speed_kmh.toFixed(1)} km/h` : undefined)}
        {row("Sprints", ph.sprints)}
        {!p.on_pitch && <div className="muted">Not on the pitch</div>}
      </div>
    </div>
  );
}

export function AskPanel({ matchId, tab, teamId, playerId, persona, lang }: {
  matchId: string; tab: string; teamId: string | null; playerId: string | null; persona: string; lang: string;
}) {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<AskResult | null>(null);
  const [showCtx, setShowCtx] = useState(false);
  const submit = async () => {
    if (q.trim().length < 2) return;
    setBusy(true);
    try { setRes(await api.ask(matchId, { question: q, tab, team_id: teamId, player_id: playerId, persona, lang })); }
    catch (e) { setRes({ answer: `Sorry, that failed: ${e}`, source: "error", verified: false, context_sent: [], problems: [], lang: "en" }); }
    finally { setBusy(false); }
  };
  return (
    <section className="panel ask">
      <h3>Ask about this view <small>{playerId ? "player" : teamId ? "team" : "match"} context</small></h3>
      <form onSubmit={e => { e.preventDefault(); submit(); }}>
        <input value={q} onChange={e => setQ(e.target.value)} placeholder="e.g. Why are they on top? Who is pressing hardest?" aria-label="Question" />
        <button disabled={busy}>{busy ? "…" : "Ask"}</button>
      </form>
      {res && (
        <div className="answer">
          <p>{res.answer}</p>
          <div className="answer-meta">
            {res.verified && <span className="badge ok">verified</span>}
            <span className="badge">{res.source === "assistant" ? "assistant" : "from the facts"}</span>
            <button className="link" onClick={() => setShowCtx(s => !s)}>{showCtx ? "hide" : "show"} what was sent to the model ({res.context_sent.length} lines)</button>
          </div>
          {showCtx && <ul className="ctx">{res.context_sent.map((l, i) => <li key={i}>{l}</li>)}</ul>}
        </div>
      )}
    </section>
  );
}

export function AgentTrace({ notes }: { notes: AgentNote[] }) {
  return (
    <section className="panel trace">
      <h3>Agent trace <small>every note: who did what, how long, what the Verifier said</small></h3>
      {!notes.length && <p className="muted">No notes yet.</p>}
      {[...notes].reverse().slice(0, 8).map((n, i) => (
        <div key={i} className="trace-row">
          <div><span className="note-clock">{n.clock ?? "-"}</span> {n.kind}/{n.reason} {n.skipped ? "(skipped)" : ""} · {n.seconds ?? "?"} s · {n.note_source}</div>
          <div className="steps">
            {(n.trace ?? []).map((t, j) => (
              <span key={j} className={`step ${t.outcome}`} title={(t.problems ?? []).join("; ")}>{t.step}:{t.outcome}</span>
            ))}
          </div>
          {(n.trace ?? []).filter(t => t.outcome === "reject").map((t, j) => (
            <div key={j} className="problems">Verifier: {(t.problems ?? []).join("; ")}</div>
          ))}
        </div>
      ))}
    </section>
  );
}
