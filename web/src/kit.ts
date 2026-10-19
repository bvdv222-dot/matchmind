import type { Colors, MatchMeta } from "./types";

const PITCH = "#1f5f35";

function rgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function distance(a: string, b: string): number {
  const [r1, g1, b1] = rgb(a), [r2, g2, b2] = rgb(b);
  // weighted RGB distance: close enough to perceived difference for picking a readable kit
  return Math.sqrt(2 * (r1 - r2) ** 2 + 4 * (g1 - g2) ** 2 + 3 * (b1 - b2) ** 2);
}

/** Shirt fill and trim that stay readable on the grass and distinct from the opponent. */
export function kits(meta: MatchMeta): Record<string, { fill: string; trim: string }> {
  const pick = (c: Colors, avoid?: string) => {
    const primaryOk = distance(c.primary, PITCH) > 160 && (!avoid || distance(c.primary, avoid) > 160);
    return primaryOk ? { fill: c.primary, trim: c.secondary } : { fill: c.secondary, trim: c.primary };
  };
  const home = pick(meta.home.colors);
  const away = pick(meta.away.colors, home.fill);
  return { [meta.home.team_id]: home, [meta.away.team_id]: away };
}
