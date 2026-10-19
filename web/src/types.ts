// Mirrors contracts/models.py (OverlayMessage, PositionFrame, MatchMeta) and the API's view payloads.

export type Colors = { primary: string; secondary: string };
export type SheetPlayer = { player_id: string; name: string; short_name: string; shirt: number; position: string };
export type TeamSheet = {
  team_id: string; name: string; short_name: string; colors: Colors; formation: string;
  starting: SheetPlayer[]; bench: SheetPlayer[];
};
export type MatchMeta = {
  match_id: string; competition: string; season: string; round: number; kickoff_utc: string;
  venue: { name: string; city: string }; referee: string; home: TeamSheet; away: TeamSheet;
};

export type WinProb = { home: number; draw: number; away: number };
export type SideState = { team_id: string; name: string; goals: number; xg: number; red_cards: number };
export type MatchState = {
  match_id: string; clock: string; minute: number; period: number; home: SideState; away: SideState;
  in_possession: string | null; win_probability: WinProb; finished: boolean;
};

export type PlayerPos = { player_id: string; team_id: string; x: number; y: number; speed_kmh: number; distance_m: number };
export type Frame = { match_id: string; period: number; t: number; ball: { x: number; y: number; z: number }; players: PlayerPos[] };

export type Overlay = {
  msg_id: string; match_id: string;
  kind: "score_bug" | "stat_tile" | "moment_card" | "player_tag" | "win_prob" | "narrative" | "recap";
  at: { period: number; t: number; clock: string }; ttl_s: number; priority: number;
  audience: string[]; lang: string; title?: string | null; body?: string | null;
  data: Record<string, unknown>; verified: boolean;
};

export type Persona = { persona_id: string; label: string; club_id?: string | null; player_id?: string | null };

export type Fixture = {
  match_id: string; round: number; home: string; home_id: string; away: string; away_id: string;
  kickoff_utc: string; status: string; live: boolean;
};

export type Comparison = {
  metric: string; actual: number; expected: number; z: number; words: string; good_for_team: boolean; concern: boolean;
};
export type NetNode = { x: number; y: number; involvement: number; name: string };
export type TeamView = {
  name: string;
  stats: Record<string, number>;
  vs_expected: Record<string, Comparison>;
  phases: Record<string, { count: number; xg: number; shots: number; goals: number }>;
  network: { nodes: Record<string, NetNode>; edges: { from: string; to: string; passes: number }[];
             hub: { player_id: string | null; share: number }; top_pair: { players: (string | null)[]; passes: number } };
  attack_standing: { words: string; band: string };
  defence_standing: { words: string; band: string };
};
export type Window = {
  from_min: number; to_min: number; home_xg: number; away_xg: number; home_field_tilt: number;
  home_possession: number; passes_per_min: number; chaos_index: number;
};
export type Moment = { moment_id: string; kind: string; priority: number; clock: string; minute: number;
                       team_id?: string; headline: string };
export type Dashboard = {
  state: MatchState; teams: Record<string, TeamView>; windows: Window[];
  win_probability_history: (WinProb & { minute: number; clock: string })[];
  top_players: { player_id: string; name: string; team: string; value_added: number }[];
  moments: Moment[]; facts: { key: string; text: string }[]; home: string; away: string;
};

export type PlayerView = {
  player_id: string; name: string; short_name: string; team_id: string; team: string; position: string;
  shirt: number; age: number; height_cm: number; foot: string; on_pitch: boolean;
  match: Record<string, number>; physical: { top_speed_kmh?: number; distance_m?: number; sprints?: number };
};

export type AskResult = { answer: string; source: string; verified: boolean; answerable?: boolean;
                          context_sent: string[]; problems: string[]; lang: string };
