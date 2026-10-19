import { useEffect, useRef, useState } from "react";
import type { AskResult, Dashboard, Fixture, Frame, MatchMeta, MatchState, Overlay, Persona, PlayerView } from "./types";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

export const api = {
  config: () => fetch("/api/config").then(json<{ agents: boolean; models: { provider: string; models: Record<string, string> };
                                                 languages: Record<string, string> }>),
  fixtures: (round: number) => fetch(`/api/fixtures?round=${round}`).then(json<{ fixtures: Fixture[] }>),
  start: (match_id: string, speed: number, languages: string[]) =>
    fetch("/api/matches/start", { method: "POST", headers: { "Content-Type": "application/json" },
                                  body: JSON.stringify({ match_id, speed, languages }) })
      .then(json<{ match_id: string; meta: MatchMeta; state: MatchState }>),
  dashboard: (id: string) => fetch(`/api/matches/${id}/dashboard`).then(json<Dashboard>),
  player: (id: string, pid: string) => fetch(`/api/matches/${id}/players/${pid}`).then(json<PlayerView>),
  agents: (id: string) => fetch(`/api/matches/${id}/agents`).then(json<{ enabled: boolean; notes: AgentNote[] }>),
  ask: (id: string, body: { question: string; tab: string; team_id?: string | null; player_id?: string | null;
                            persona: string; lang: string }) =>
    fetch(`/api/matches/${id}/ask`, { method: "POST", headers: { "Content-Type": "application/json" },
                                      body: JSON.stringify(body) }).then(json<AskResult>),
};

export type AgentNote = { clock?: string; kind: string; reason?: string; skipped?: boolean; seconds?: number;
                          note_source?: string; trace?: { step: string; ms: number; outcome: string; problems?: string[] }[];
                          error?: string };

export type Live = {
  meta: MatchMeta | null; state: MatchState | null; frame: Frame | null; personas: Persona[];
  cards: Overlay[]; notes: Overlay[]; tags: Overlay[]; connected: boolean; finished: boolean;
};

/** The live feed for one match; persona / language / focus changes are sent on the open socket. */
export function useLive(matchId: string | null, persona: string, lang: string, focusPlayer: string | null): Live {
  const [live, setLive] = useState<Live>({ meta: null, state: null, frame: null, personas: [], cards: [], notes: [],
                                           tags: [], connected: false, finished: false });
  const ws = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!matchId) return;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const sock = new WebSocket(`${proto}://${location.host}/ws/matches/${matchId}?persona=${persona}&lang=${lang}`);
    ws.current = sock;
    setLive(l => ({ ...l, cards: [], notes: [], tags: [] }));
    sock.onopen = () => setLive(l => ({ ...l, connected: true }));
    sock.onclose = () => setLive(l => ({ ...l, connected: false }));
    sock.onmessage = ev => {
      const msg = JSON.parse(ev.data);
      setLive(l => {
        switch (msg.type) {
          case "hello": return { ...l, meta: msg.data.meta, state: msg.data.state, personas: msg.data.personas };
          case "frame": return { ...l, frame: msg.data };
          case "state": return { ...l, state: msg.data };
          case "finished": return { ...l, finished: true };
          case "overlay": {
            const o: Overlay = { ...msg.data, data: { ...msg.data.data, received: msg.replay ? 0 : Date.now() } };
            if (o.kind === "narrative" || o.kind === "recap") {
              const notes = msg.replay ? l.notes.filter(n => n.at.clock !== o.at.clock || n.kind !== o.kind) : l.notes;
              return { ...l, notes: [o, ...notes].slice(0, 30) };
            }
            if (o.kind === "player_tag") return { ...l, tags: [o, ...l.tags].slice(0, 6) };
            return { ...l, cards: [o, ...l.cards].slice(0, 40) };
          }
          default: return l;
        }
      });
    };
    return () => sock.close();
    // reconnect only when the match changes; preferences travel on the open socket
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [matchId]);

  useEffect(() => {
    const sock = ws.current;
    if (sock && sock.readyState === WebSocket.OPEN) {
      sock.send(JSON.stringify({ type: "prefs", persona, lang, focus_player: focusPlayer }));
    }
  }, [persona, lang, focusPlayer, live.connected]);

  return live;
}

/** Poll a view every `ms` while it is mounted. */
export function usePoll<T>(fn: (() => Promise<T>) | null, ms: number, deps: unknown[]): T | null {
  const [data, setData] = useState<T | null>(null);
  useEffect(() => {
    if (!fn) return;
    let alive = true;
    const tick = () => fn().then(d => alive && setData(d)).catch(() => undefined);
    tick();
    const id = setInterval(tick, ms);
    return () => { alive = false; clearInterval(id); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return data;
}
