// What a map tile reports next to its colour — one rule, so the on-screen
// legend and the exported figure cannot disagree.
//
// This lived inside MapOverlay while the overlay was the only surface that
// showed it. The figure export then grew its own version, which is how EDS
// figures ended up captioning at% only and EELS figures captioning nothing at
// all, while both overlays showed net counts on screen. Same class of defect
// as the holed-region label that read gross while its CSV read net: a second
// copy of a display rule drifts from the first.

import { formatCountTick } from "../edsSpectrumDisplay";
import type { MapTile } from "./mapTile";

/** Which number the legend carries: none, integrated net counts, or the
 *  atomic percent a Quantify run produced for that element. */
export type LegendValue = "none" | "net" | "atomic";

/** The legend/caption detail for `tile`, or "" when there is nothing to say.
 *  `quantBySymbol` is keyed by element symbol because quantification is
 *  per-element — an element carrying two EELS edges shares one at%. */
export function legendDetail(
  tile: MapTile,
  legendValue: LegendValue,
  quantBySymbol?: Record<string, number>,
): string {
  if (legendValue === "atomic") {
    const pct = quantBySymbol?.[tile.symbol];
    return pct == null ? "" : `${pct.toFixed(1)} at%`;
  }
  if (legendValue === "net") return formatCountTick(tile.totalCounts);
  return "";
}
