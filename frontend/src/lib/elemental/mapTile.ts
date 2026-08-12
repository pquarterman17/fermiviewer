// The unit every elemental surface draws: one species' window map.
//
// The type and its key rule live in lib/ rather than beside the montage that
// first defined them, because the montage is no longer the only consumer —
// the overlay, the map hooks, the legend rule and the figure export all key
// off the same tile, and lib/ modules must not reach up into components/.

export interface MapTile {
  symbol: string;
  line: string;
  /** Full caption override. When absent, the montage/overlay/legend fall
   *  back to "{symbol} {line}α" — the EDS X-ray-line convention. EELS tiles
   *  (edges, not lines) set this explicitly so the caption never grows a
   *  meaningless "α" suffix. */
  caption?: string;
  /** H×W background-subtracted counts. */
  map: number[][];
  shape: [number, number];
  totalCounts: number;
}

/** Stable per-tile identity for React keys and the overlay's per-tile gain
 *  map. `symbol` alone collides when one element carries two species — EELS'
 *  Si-K and Si-L23 (see useEelsMaps.ts) — so every keyed usage goes through
 *  this instead. Safe for EDS too: its species list never repeats a symbol,
 *  so the key is unchanged in effect, just spelled "Fe-K" instead of "Fe". */
export function tileKey(tile: MapTile): string {
  return `${tile.symbol}-${tile.line}`;
}

/** Caption shown on the tile, in the legend, and on the exported figure. */
export function tileLabel(tile: MapTile): string {
  return tile.caption ?? `${tile.symbol} ${tile.line}α`;
}
