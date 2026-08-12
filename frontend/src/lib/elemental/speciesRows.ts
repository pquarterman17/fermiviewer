// Where auto-ID's evidence meets the user's decisions (SPECTRAL_WORKSPACE_PLAN
// #9, generalised to EELS by #12/#16).
//
// Two different things describe a species in this workspace and they must not
// be merged into one object:
//
//   Evidence   what auto-ID MEASURED — net, sigma, significance, confidence.
//              Recomputed every identify; changes when the background model
//              changes. EDS's IdentifiedElement and EELS's EelsEdgeEvidence
//              both extend it with their own modality-specific extra (see
//              identify.ts / eelsIdentify.ts).
//   Species    what the USER DECIDED — which things to map, over what
//              windows, which are showing. Must survive a re-identification
//              that changes every measured number.
//
// Rows are built from SPECIES, not from evidence: a species the user removed
// stays gone even though auto-ID still finds it, and one added by hand still
// shows even though nothing detected a peak/edge for it. Evidence is looked
// up per row and is allowed to be missing.
//
// This is pure so the merge rules can be tested without rendering anything.

import type { Species } from "../spectrum/species";
import { edsSpecies, eelsSpecies } from "../spectrum/species";
import type { EelsEdgeEvidence } from "./eelsIdentify";
import type { Evidence } from "./identify";

export interface SpeciesRow {
  species: Species;
  /** The measurement backing this row, when there is one. Null for a species
   *  the current identify pass did not find — a hand-added trace species, or
   *  one whose signal vanished when the background model changed. */
  evidence: Evidence | null;
}

/** Evidence indexed by symbol+transition, NOT symbol alone: EDS's
 *  identifyElements collapses to one row per element, so symbol used to be
 *  unique, but EELS's /eels/auto-assign scores every tabulated edge — Si-K
 *  and Si-L23 can both be evidence at once, and keying on symbol alone would
 *  silently drop one of them. */
function rowKey(symbol: string, transition: string): string {
  return `${symbol}|${transition}`;
}

export function evidenceByKey(
  evidence: readonly Evidence[],
): Map<string, Evidence> {
  return new Map(evidence.map((e) => [rowKey(e.symbol, e.transition), e]));
}

export function buildRows(
  species: readonly Species[],
  evidence: readonly Evidence[],
): SpeciesRow[] {
  const byKey = evidenceByKey(evidence);
  return species.map((s) => ({
    species: s,
    evidence: byKey.get(rowKey(s.symbol, s.transition)) ?? null,
  }));
}

/**
 * The EDS species list for an image that has none yet, seeded from auto-ID.
 *
 * Returns null when `existing` is non-empty — the user's decisions win, and a
 * re-identification must never overwrite them. That is the whole reason
 * evidence and species are separate types: re-running identify refreshes
 * every measured number on screen while leaving unticked rows untucked and
 * tuned windows tuned.
 *
 * Auto-ID's `recommended` flag (everything above trace) seeds `visible`, so a
 * freshly opened cube arrives with its real elements already showing and its
 * trace candidates present but off.
 */
export function seedEdsSpeciesFrom(
  evidence: readonly Evidence[],
  existing: readonly Species[],
): Species[] | null {
  if (existing.length > 0) return null;
  return evidence.map((e) =>
    edsSpecies(e.symbol, e.transition, e.energy, {
      visible: e.recommended,
      // Auto-ID measured over a window it chose; keep that exact window rather
      // than recomputing a default one, so the net counts shown in the row are
      // the net counts of the window the map will actually be cut on.
      halfWindowKev: (e.windowHi - e.windowLo) / 2,
    }),
  );
}

/**
 * The EELS species list for an image that has none yet, seeded from
 * /eels/auto-assign. Same seed-or-restore contract as `seedEdsSpeciesFrom`
 * (null when the user already has a list), but the window comes straight
 * from the evidence — including the pre-edge fit window auto-assign
 * actually measured against — rather than through `eelsDefaultWindows`,
 * so a seeded species' background window can never disagree with the net
 * counts the row displays.
 */
export function seedEelsSpeciesFrom(
  evidence: readonly EelsEdgeEvidence[],
  existing: readonly Species[],
): Species[] | null {
  if (existing.length > 0) return null;
  return evidence.map((e) =>
    eelsSpecies(e.symbol, e.transition, e.energy, {
      visible: e.recommended,
      windows: {
        signal: { lo: e.windowLo, hi: e.windowHi },
        background: { lo: e.fitWindow[0], hi: e.fitWindow[1] },
      },
    }),
  );
}

/** The species whose maps should be extracted and composited. */
export function visibleSpecies(rows: readonly SpeciesRow[]): Species[] {
  return rows.filter((r) => r.species.visible).map((r) => r.species);
}
