import { useEffect, useState } from "react";
import { kits } from "../kit";
import type { MatchMeta, MatchState, Overlay } from "../types";

const pct = (x: number) => `${Math.round(100 * x)}%`;

export function ScoreBug({ meta, state }: { meta: MatchMeta; state: MatchState }) {
  const side = (s: "home" | "away") => {
    const t = meta[s];
    return (
      <div className="bug-team">
        <span className="bug-swatch" style={{ background: t.colors.primary, borderColor: t.colors.secondary }} />
        <span className="bug-code">{t.short_name}</span>
        <span className="bug-goals">{state[s].goals}</span>
        {state[s].red_cards > 0 && <span className="bug-red" title="red card">{"▮".repeat(state[s].red_cards)}</span>}
      </div>
    );
  };
  return (
    <div className="scorebug" aria-label="Score">
      {side("home")}
      <div className="bug-clock">{state.finished ? "FT" : state.clock}</div>
      {side("away")}
    </div>
  );
}

export function WinProbBar({ meta, state }: { meta: MatchMeta; state: MatchState }) {
  const wp = state.win_probability;
  const kit = kits(meta);
  return (
    <div className="winprob" aria-label="Win probability">
      <div className="wp-label">Win probability</div>
      <div className="wp-bar">
        <div style={{ width: pct(wp.home), background: kit[meta.home.team_id].fill, color: kit[meta.home.team_id].trim }} title={`${meta.home.name} ${pct(wp.home)}`}>
          {wp.home > 0.12 && pct(wp.home)}
        </div>
        <div className="wp-draw" style={{ width: pct(wp.draw) }} title={`Draw ${pct(wp.draw)}`}>{wp.draw > 0.12 && pct(wp.draw)}</div>
        <div style={{ width: pct(wp.away), background: kit[meta.away.team_id].fill, color: kit[meta.away.team_id].trim }} title={`${meta.away.name} ${pct(wp.away)}`}>
          {wp.away > 0.12 && pct(wp.away)}
        </div>
      </div>
      <div className="wp-teams"><span>{meta.home.short_name}</span><span>draw</span><span>{meta.away.short_name}</span></div>
    </div>
  );
}

/** Moment cards stay up for their ttl (real seconds), highest priority on top. */
export function MomentCards({ cards }: { cards: Overlay[] }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(id);
  }, []);
  const visible = cards
    .filter(c => now - (c.data.received as number) < c.ttl_s * 1000)
    .sort((a, b) => b.priority - a.priority)
    .slice(0, 3);
  return (
    <div className="cards" aria-live="polite">
      {visible.map(c => (
        <div key={c.msg_id} className={`card card-${c.kind} prio-${c.priority >= 8 ? "high" : "normal"}`}>
          <div className="card-head"><span>{c.title}</span><span>{c.at.clock}</span></div>
          <div className="card-body">{c.body}</div>
        </div>
      ))}
    </div>
  );
}

export function PlayerTags({ tags }: { tags: Overlay[] }) {
  const recent = tags.filter(t => Date.now() - (t.data.received as number) < t.ttl_s * 1000).slice(0, 2);
  return (
    <div className="tags">
      {recent.map(t => <div key={t.msg_id} className="tag">⚡ {t.body}</div>)}
    </div>
  );
}

export function NoteFeed({ notes, lang }: { notes: Overlay[]; lang: string }) {
  if (!notes.length) return <div className="notes empty">Live notes appear here as the match unfolds.</div>;
  return (
    <div className="notes">
      {notes.map(n => (
        <article key={n.msg_id} className={`note ${n.kind}`}>
          <header>
            <span className="note-clock">{n.at.clock}</span>
            <span className="note-kind">{n.kind === "recap" ? "Recap" : "Live note"}</span>
            {n.verified && <span className="badge ok" title="Passed the Verifier's checks">verified</span>}
            {String(n.data.text_source ?? "").startsWith("fallback") && (
              <span className="badge" title="Built from the fact lines after the model's draft failed a check">from facts</span>
            )}
            {n.lang !== lang && lang !== "en" && <span className="badge">English</span>}
          </header>
          <p>{n.body}</p>
        </article>
      ))}
    </div>
  );
}
