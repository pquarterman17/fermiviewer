// Turn the /eels/auto-assign response into a reviewable edge list — the
// EELS analogue of identify.ts, but far thinner.
//
// EDS's identifyElements() has to measure net/sigma/significance/confidence
// client-side, against a displayed spectrum, because /eds/auto-assign only
// returns candidate line matches. EELS has no such gap: /eels/auto-assign
// scores every tabulated edge server-side and already returns the full
// Evidence vocabulary (see calc/eels_identify.py). This module's only job is
// reshaping that response into the shared shape buildRows/
// seedEelsSpeciesFrom (speciesRows.ts) and ElementList.tsx already consume.

import type { EelsAutoAssignResult } from "../api";
import type { Evidence } from "./identify";

export interface EelsEdgeEvidence extends Evidence {
  /** The pre-edge background-fit window auto-assign measured against —
   *  carried through so a seeded species' background window is the exact
   *  one the displayed net counts were computed from, not a recomputed
   *  default that could disagree with it. */
  fitWindow: [number, number];
}

/**
 * One row per scored edge, already sorted strongest-first by the backend.
 * `relative` is computed here (against the strongest edge in this pass) the
 * same way identifyElements() does for EDS — the response doesn't carry it,
 * since "relative to what" is a display concern, not a measurement.
 */
export function eelsEvidenceFrom(
  result: EelsAutoAssignResult | null,
): EelsEdgeEvidence[] {
  if (!result) return [];
  const strongest = result.edges.reduce((m, e) => Math.max(m, e.net), 1e-9);
  return result.edges.map((e) => ({
    symbol: e.element,
    transition: e.edge,
    energy: e.onset_ev,
    windowLo: e.signal_window[0],
    windowHi: e.signal_window[1],
    fitWindow: e.fit_window,
    net: e.net,
    sigma: e.sigma,
    significance: e.significance,
    confidence: e.confidence,
    relative: Math.max(0, Math.min(1, e.net / strongest)),
    recommended: e.confidence !== "trace",
  }));
}
