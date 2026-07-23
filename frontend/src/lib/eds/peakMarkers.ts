import type { EdsAutoAssignResult, EdsLine } from "../api";

export interface PeakMarker {
  energyKev: number;
  label: string; // e.g. "Fe Kα"
  kind: "selected" | "auto";
}

/**
 * Merge user-selected element lines and auto-detected peak assignments into a
 * de-duplicated, energy-sorted set of spectrum markers. A selected line wins
 * over an auto detection at the same (element, shell), so an element the user
 * explicitly picked is never downgraded to a faint auto marker.
 */
export function buildPeakMarkers(
  selected: EdsLine[],
  auto: EdsAutoAssignResult | null,
): PeakMarker[] {
  const byKey = new Map<string, PeakMarker>();
  const put = (
    symbol: string,
    line: string,
    energyKev: number,
    kind: PeakMarker["kind"],
  ) => {
    const key = `${symbol}:${line}`;
    if (kind === "auto" && byKey.has(key)) return; // keep the selected marker
    byKey.set(key, { energyKev, label: `${symbol} ${line}α`, kind });
  };

  for (const ln of selected) put(ln.symbol, ln.line, ln.energy_kev, "selected");
  for (const a of auto?.assignments ?? []) {
    const top = a.candidates[0];
    if (top) put(top.symbol, top.line, top.energy_kev, "auto");
  }
  return [...byKey.values()].sort((a, b) => a.energyKev - b.energyKev);
}
