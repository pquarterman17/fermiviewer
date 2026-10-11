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

/**
 * What auto-ID measured for one candidate species — the vocabulary shared by
 * EDS (computed client-side here, against a displayed spectrum, because
 * `/eds/auto-assign` only returns candidate matches) and EELS (computed
 * server-side by `/eels/auto-assign`, which scores every tabulated edge
 * directly — see `lib/elemental/eelsIdentify.ts`). Field names mirror
 * `Species` (`symbol`/`transition`/`energy`) so a row's evidence and its
 * species describe the same species in the same vocabulary.
 *
 * This is the base shape `speciesRows.ts` and `ElementList.tsx` consume;
 * modality-specific extras (EDS's `deltaKev` below, EELS's `fitWindow` in
 * `EelsEdgeEvidence`) live on an extending interface rather than being
 * widened onto this one.
 */
export interface Evidence {
  symbol: string;
  /** EDS: the shell whose line explained the peak ("K"|"L"|"M"). EELS: the
   *  edge label ("L23"). Matches `Species.transition`. */
  transition: string;
  /** Reference/anchor energy, in the species' own unit. Matches
   *  `Species.energy`. */
  energy: number;
  /** The window this evidence was actually measured over. */
  windowLo: number;
  windowHi: number;
  net: number;
  sigma: number;
  /** net / σ — how many standard deviations the signal stands above noise. */
  significance: number;
  confidence: Confidence;
  /** net relative to the strongest species in this identify pass, for the
   *  strength bar. */
  relative: number;
  /**
   * Auto-ID's RECOMMENDATION that this species is worth mapping — true for
   * everything but `trace`. It is a seeding hint, not state: whether a
   * species is actually shown lives on the Species in `store/species.ts`, so
   * that a re-identification cannot silently retick what the user untucked.
   */
  recommended: boolean;
  /** Auto-ID evidence versus a measurement requested explicitly by the user. */
  source?: "auto" | "manual";
}

export interface IdentifiedElement extends Evidence {
  /** EDS only: distance from the detected peak to the tabulated line (keV).
   *  EELS has no analogue — auto-assign scores directly against the
   *  tabulated onset, there is no separate "detected peak" to compare
   *  against it. */
  deltaKev: number;
}

export type RejectionReason = "below_background" | "line_overlap" | "outside_range";

export interface RejectedElement {
  symbol: string;
  transition: string;
  energy: number;
  deltaKev: number;
  reason: RejectionReason;
  detail: string;
  net: number | null;
}

export interface IdentificationResult {
  elements: IdentifiedElement[];
  rejected: RejectedElement[];
}

/** Counting-statistics bands. A peak at 100σ in a whole-cube sum spectrum is
 *  unambiguous; below ~10σ it is as likely to be a background fluctuation as
 *  an element. Positive trace rows therefore arrive unticked rather than
 *  hidden — a real trace element the user is looking for must remain
 *  reachable. Non-positive integrations are not evidence for an automatic
 *  identification and are discarded by `identifyElements`. */
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
 * One row per element, strongest first. Every line matched to an element is
 * measured: the most significant positive line wins, with distance to the
 * detected peak as the tie-breaker. The element is omitted only when none of
 * its matched lines has positive background-subtracted signal.
 */
export function identifyElementCandidates(
  auto: EdsAutoAssignResult | null,
  spectrum: Spectrum | null,
  opts: IdentifyOptions = {},
): IdentificationResult {
  if (!auto || !spectrum) return { elements: [], rejected: [] };
  const half = opts.halfWindowKev ?? 0.085;
  const background = opts.background ?? "linear";

  // Keep the leading candidate from every detected peak. Choosing a single
  // line by delta before measuring can hide (for example) a strong K line
  // when the same element's slightly closer low-energy L line is below its
  // local background.
  const matches = new Map<
    string,
    { line: string; energy: number; delta: number }[]
  >();
  const rejected: RejectedElement[] = [];
  for (const assignment of auto.assignments) {
    const top = assignment.candidates[0];
    if (!top) continue;
    const held = matches.get(top.symbol) ?? [];
    held.push({
      line: top.line,
      energy: top.energy_kev,
      delta: Math.abs(top.delta_kev),
    });
    matches.set(top.symbol, held);
    for (const alternative of assignment.candidates.slice(1)) {
      rejected.push({
        symbol: alternative.symbol,
        transition: alternative.line,
        energy: alternative.energy_kev,
        deltaKev: Math.abs(alternative.delta_kev),
        reason: "line_overlap",
        detail: `line overlap; peak better matches ${top.symbol} ${top.line}α`,
        net: null,
      });
    }
  }

  const rows: IdentifiedElement[] = [];
  for (const [symbol, elementMatches] of matches) {
    let chosen: IdentifiedElement | null = null;
    let failed: RejectedElement | null = null;
    for (const match of elementMatches) {
      const eLo = match.energy - half;
      const eHi = match.energy + half;
      const integration = integrateWindow(spectrum, eLo, eHi, background, {
        e0Kev: opts.e0Kev,
      });
      if (!integration) {
        failed ??= {
          symbol,
          transition: match.line,
          energy: match.energy,
          deltaKev: match.delta,
          reason: "outside_range",
          detail: "measurement window is outside the acquired spectrum",
          net: null,
        };
        continue;
      }
      if (integration.net <= 0) {
        failed ??= {
          symbol,
          transition: match.line,
          energy: match.energy,
          deltaKev: match.delta,
          reason: "below_background",
          detail: "signal is at or below the estimated background",
          net: integration.net,
        };
        continue;
      }
      const significance =
        integration.sigma > 0 ? integration.net / integration.sigma : 0;
      const confidence = confidenceOf(significance);
      const measured: IdentifiedElement = {
        symbol,
        transition: match.line,
        energy: match.energy,
        windowLo: eLo,
        windowHi: eHi,
        net: integration.net,
        sigma: integration.sigma,
        significance,
        confidence,
        deltaKev: match.delta,
        relative: 0,
        recommended: confidence !== "trace",
        source: "auto",
      };
      if (
        !chosen ||
        measured.significance > chosen.significance ||
        (measured.significance === chosen.significance &&
          measured.deltaKev < chosen.deltaKev)
      ) {
        chosen = measured;
      }
    }
    if (chosen) rows.push(chosen);
    else if (failed) rejected.push(failed);
  }

  rows.sort((a, b) => b.net - a.net);
  const strongest = rows.length > 0 ? Math.max(rows[0].net, 1e-9) : 1;
  for (const row of rows) {
    row.relative = Math.max(0, Math.min(1, row.net / strongest));
  }
  const acceptedKeys = new Set(rows.map((row) => `${row.symbol}|${row.transition}`));
  const uniqueRejected = new Map<string, RejectedElement>();
  for (const item of rejected) {
    if (acceptedKeys.has(`${item.symbol}|${item.transition}`)) continue;
    const key = `${item.symbol}|${item.transition}|${item.reason}`;
    if (!uniqueRejected.has(key)) uniqueRejected.set(key, item);
  }
  return { elements: rows, rejected: [...uniqueRejected.values()] };
}

export function identifyElements(
  auto: EdsAutoAssignResult | null,
  spectrum: Spectrum | null,
  opts: IdentifyOptions = {},
): IdentifiedElement[] {
  return identifyElementCandidates(auto, spectrum, opts).elements;
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
    transition: line,
    energy: energyKev,
    windowLo: energyKev - half,
    windowHi: energyKev + half,
    net: integration.net,
    sigma: integration.sigma,
    significance,
    confidence: confidenceOf(significance),
    deltaKev: 0,
    relative: Math.max(0, Math.min(1, integration.net / strongest)),
    recommended: true, // an element the user asked for is wanted by definition
    source: "manual",
  };
}
