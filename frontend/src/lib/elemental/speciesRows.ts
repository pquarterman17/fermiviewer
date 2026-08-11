// Where auto-ID's evidence meets the user's decisions (SPECTRAL_WORKSPACE_PLAN
// #9).
//
// Two different things describe an element in this workspace and they must not
// be merged into one object:
//
//   IdentifiedElement  what auto-ID MEASURED — net, sigma, significance,
//                      confidence, delta-from-tabulated. Recomputed from the
//                      spectrum every identify; changes when the background
//                      model changes; has no EELS analogue.
//   Species            what the USER DECIDED — which things to map, over what
//                      windows, which are showing. Must survive a
//                      re-identification that changes every measured number.
//
// Rows are built from SPECIES, not from evidence: an element the user removed
// stays gone even though auto-ID still finds it, and an element the user added
// by hand still shows even though nothing detected a peak for it. Evidence is
// looked up per row and is allowed to be missing.
//
// This is pure so the merge rules can be tested without rendering anything.

import type { Species } from "../spectrum/species";
import { edsSpecies } from "../spectrum/species";
import type { IdentifiedElement } from "./identify";

export interface SpeciesRow {
  species: Species;
  /** The measurement backing this row, when there is one. Null for a species
   *  the current identify pass did not find — a hand-added trace element, or
   *  one whose peak vanished when the background model changed. */
  evidence: IdentifiedElement | null;
}

/** Evidence indexed by symbol. `identifyElements` already collapses to one row
 *  per element, so the symbol is unique. */
export function evidenceBySymbol(
  evidence: readonly IdentifiedElement[],
): Map<string, IdentifiedElement> {
  return new Map(evidence.map((e) => [e.symbol, e]));
}

export function buildRows(
  species: readonly Species[],
  evidence: readonly IdentifiedElement[],
): SpeciesRow[] {
  const bySymbol = evidenceBySymbol(evidence);
  return species.map((s) => ({
    species: s,
    evidence: bySymbol.get(s.symbol) ?? null,
  }));
}

/**
 * The species list for an image that has none yet, seeded from auto-ID.
 *
 * Returns null when `existing` is non-empty — the user's decisions win, and a
 * re-identification must never overwrite them. That is the whole reason the
 * two types are separate: re-running identify refreshes every measured number
 * on screen while leaving unticked rows untucked and tuned windows tuned.
 *
 * Auto-ID's `recommended` flag (everything above trace) seeds `visible`, so a
 * freshly opened cube arrives with its real elements already showing and its
 * trace candidates present but off.
 */
export function seedSpeciesFrom(
  evidence: readonly IdentifiedElement[],
  existing: readonly Species[],
): Species[] | null {
  if (existing.length > 0) return null;
  return evidence.map((e) =>
    edsSpecies(e.symbol, e.line, e.energyKev, {
      visible: e.recommended,
      // Auto-ID measured over a window it chose; keep that exact window rather
      // than recomputing a default one, so the net counts shown in the row are
      // the net counts of the window the map will actually be cut on.
      halfWindowKev: (e.eHi - e.eLo) / 2,
    }),
  );
}

/** The species whose maps should be extracted and composited. */
export function visibleSpecies(rows: readonly SpeciesRow[]): Species[] {
  return rows.filter((r) => r.species.visible).map((r) => r.species);
}
