// Turn raw peak/line matches into a reviewable element list.
//
// `/eds/auto-assign` answers "which lines could this peak be" — a list of
// candidate matches per detected peak, with no notion of how much signal is
// actually there. That is not enough to hand a user: it says nothing about
// which matches are real, and the same element appears once per peak it
// explains.
//
// This collapses those matches to one row per element and measures each one
// against the sum spectrum, so every row carries net counts and a confidence
// grounded in counting statistics rather than in whether a line happened to
// fall within the matching tolerance.

import type { EdsAutoAssignResult, Spectrum } from "../api";
import type { EdsBackground } from "../eds/integrate";
import { integrateWindow } from "../eds/integrate";

export type Confidence = "strong" | "clear" | "weak" | "trace";

export interface IdentifiedElement {
  symbol: string;
  /** "K" | "L" | "M" — the shell whose line explained the peak. */
  line: string;
  energyKev: number;
  eLo: number;
  eHi: number;
  net: number;
  sigma: number;
  /** net / σ — how many standard deviations the peak stands above noise. */
  significance: number;
  confidence: Confidence;
  /** Distance from the detected peak to the tabulated line (keV). */
  deltaKev: number;
  /** net relative to the strongest element, for the strength bar. */
  relative: number;
  /** Pre-ticked for everything but `trace`. */
  selected: boolean;
}

/** Counting-statistics bands. A peak at 100σ in a whole-cube sum spectrum is
 *  unambiguous; below ~10σ it is as likely to be a background fluctuation as
 *  an element, which is why trace rows arrive unticked rather than hidden —
 *  a real trace element the user is looking for must still be reachable. */
const BANDS: [number, Confidence][] = [
  [100, "strong"],
  [30, "clear"],
  [10, "weak"],
];

export function confidenceOf(significance: number): Confidence {
  for (const [threshold, label] of BANDS) {
    if (significance >= threshold) return label;
  }
  return "trace";
}

export interface IdentifyOptions {
  /** Half-width of the integration window (keV). */
  halfWindowKev?: number;
  background?: EdsBackground;
  e0Kev?: number;
}

/**
 * One row per element, strongest first. Elements matched by more than one
 * peak keep their best match — the one closest to the tabulated line.
 */
export function identifyElements(
  auto: EdsAutoAssignResult | null,
  spectrum: Spectrum | null,
  opts: IdentifyOptions = {},
): IdentifiedElement[] {
  if (!auto || !spectrum) return [];
  const half = opts.halfWindowKev ?? 0.085;
  const background = opts.background ?? "linear";

  // best candidate per element: nearest line wins
  const best = new Map<string, { line: string; energy: number; delta: number }>();
  for (const assignment of auto.assignments) {
    const top = assignment.candidates[0];
    if (!top) continue;
    const delta = Math.abs(top.delta_kev);
    const held = best.get(top.symbol);
    if (!held || delta < held.delta) {
      best.set(top.symbol, {
        line: top.line,
        energy: top.energy_kev,
        delta,
      });
    }
  }

  const rows: IdentifiedElement[] = [];
  for (const [symbol, match] of best) {
    const eLo = match.energy - half;
    const eHi = match.energy + half;
    const integration = integrateWindow(spectrum, eLo, eHi, background, {
      e0Kev: opts.e0Kev,
    });
    if (!integration) continue;
    const significance =
      integration.sigma > 0 ? integration.net / integration.sigma : 0;
    const confidence = confidenceOf(significance);
    rows.push({
      symbol,
      line: match.line,
      energyKev: match.energy,
      eLo,
      eHi,
      net: integration.net,
      sigma: integration.sigma,
      significance,
      confidence,
      deltaKev: match.delta,
      relative: 0,
      selected: confidence !== "trace",
    });
  }

  rows.sort((a, b) => b.net - a.net);
  const strongest = rows.length > 0 ? Math.max(rows[0].net, 1e-9) : 1;
  for (const row of rows) {
    row.relative = Math.max(0, Math.min(1, row.net / strongest));
  }
  return rows;
}

/** Add an element the identifier missed, measured the same way so its row is
 *  comparable with the auto-detected ones. */
export function measureElement(
  symbol: string,
  line: string,
  energyKev: number,
  spectrum: Spectrum,
  reference: IdentifiedElement[],
  opts: IdentifyOptions = {},
): IdentifiedElement | null {
  const half = opts.halfWindowKev ?? 0.085;
  const integration = integrateWindow(
    spectrum,
    energyKev - half,
    energyKev + half,
    opts.background ?? "linear",
    { e0Kev: opts.e0Kev },
  );
  if (!integration) return null;
  const significance =
    integration.sigma > 0 ? integration.net / integration.sigma : 0;
  const strongest = Math.max(...reference.map((r) => r.net), integration.net, 1e-9);
  return {
    symbol,
    line,
    energyKev,
    eLo: energyKev - half,
    eHi: energyKev + half,
    net: integration.net,
    sigma: integration.sigma,
    significance,
    confidence: confidenceOf(significance),
    deltaKev: 0,
    relative: Math.max(0, Math.min(1, integration.net / strongest)),
    selected: true, // an element the user asked for is on by definition
  };
}
