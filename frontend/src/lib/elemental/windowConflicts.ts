// Window overlap detection — an ADVISORY only (SPECTRAL_WORKSPACE_PLAN #20).
//
// Three rules, all non-blocking: nothing here ever narrows, refuses, or
// filters a window, a map, or a quantification. The gate this item reopened
// under ("Ta M / Si K in real work produces a wrong answer silently") is a
// SILENT failure — `/eds/quantify` on the eds-overlap cube returns Ta at
// 0.00 at% against a truth of 6.67, sigma 0.000, no warning anywhere in the
// response (tests/test_quant_golden.py pins this measured failure). The fix
// here is visibility, not correction: a badge the user can act on (narrow
// the windows, change beam kV, switch to Model fit), never an automatic one.
//
// R1 (signal window overlap, both modalities) and R2 (unresolvable lines,
// EDS only) are DIFFERENT failure modes and both fire independently. R1 is
// something the user did (drew overlapping windows) and can undo by
// narrowing them; R2 is the detector's own resolution and does not care
// where the windows sit — narrowing them until they stop touching does
// nothing for R2's case. Conflating the two into one rule would hide that a
// narrowed window can still be broken.
//
// A `lib/` module must not import from `components/` (the rule that forced
// the `mapTile.ts` extraction — see SPECTRAL_WORKSPACE_PLAN's #7 entry), so
// R2 formats its own eV numbers here rather than importing
// `WindowPresetBar.tsx`'s `formatWindowWidth`.

import { fanoFwhmKev } from "../eds/resolution";
import type { EnergyWindow, Species } from "../spectrum/species";
import { orderWindow, speciesUnit } from "../spectrum/species";

export type ConflictKind = "overlap" | "unresolved" | "background";

export interface WindowConflict {
  /** Species ids of the conflicting pair, ordered aId < bId so a pair is
   *  never reported twice under swapped keys. */
  aId: string;
  bId: string;
  kind: ConflictKind;
  /** Human sentence for the tooltip — self-contained, names both species. */
  detail: string;
}

function windowsOverlap(a: EnergyWindow, b: EnergyWindow): boolean {
  return a.lo < b.hi && b.lo < a.hi;
}

function label(s: Species): string {
  const energy = s.modality === "eels" ? `${Math.round(s.energy)} eV` : s.energy.toFixed(3);
  return `${s.symbol} ${s.transition} (${energy})`;
}

function fmt(value: number, unit: "keV" | "eV"): string {
  return unit === "eV" ? `${Math.round(value)}` : value.toFixed(3);
}

/** Stable pair ordering by species id, so a conflict is reported once. */
function byId(a: Species, b: Species): [Species, Species] {
  return a.id < b.id ? [a, b] : [b, a];
}

// Every rule below sorts its pair FIRST and builds `detail` from the sorted
// (first, second), never from the raw (a, b) call-order parameters — so a
// conflict's aId/bId AND its tooltip wording are both independent of which
// species the outer loop in `detectWindowConflicts` happened to visit
// first. Building `detail` from (a, b) instead would still pass every
// "aId < bId" assertion while wording the SAME conflict two different ways
// depending on incidental input-array order — a real defect this module
// found in itself while writing its own order-independence test.

function signalOverlap(a: Species, b: Species): WindowConflict | null {
  if (!windowsOverlap(orderWindow(a.windows.signal), orderWindow(b.windows.signal))) {
    return null;
  }
  const [first, second] = byId(a, b);
  const unit = speciesUnit(first.modality);
  const fw = orderWindow(first.windows.signal);
  const sw = orderWindow(second.windows.signal);
  const lo = Math.max(fw.lo, sw.lo);
  const hi = Math.min(fw.hi, sw.hi);
  return {
    aId: first.id,
    bId: second.id,
    kind: "overlap",
    detail: `${label(first)} and ${label(second)}: integration windows share `
      + `[${fmt(lo, unit)}, ${fmt(hi, unit)}] ${unit}.`,
  };
}

/** The detector convolves two EDS lines regardless of how the windows are
 *  drawn — this fires even after R1 has been narrowed away. */
function unresolvedLines(a: Species, b: Species): WindowConflict | null {
  if (a.modality !== "eds" || b.modality !== "eds") return null;
  const separationKev = Math.abs(a.energy - b.energy);
  const fwhmKev = fanoFwhmKev((a.energy + b.energy) / 2);
  if (separationKev >= fwhmKev) return null;
  const [first, second] = byId(a, b);
  const sepEv = Math.round(separationKev * 1000);
  const fwhmEv = Math.round(fwhmKev * 1000);
  return {
    aId: first.id,
    bId: second.id,
    kind: "unresolved",
    detail: `${label(first)} and ${label(second)} are ${sepEv} eV apart — closer `
      + `than the detector resolution (${fwhmEv} eV); integration cannot `
      + `separate them. Consider Model fit.`,
  };
}

/** A power-law fitted through another element's edge is the EELS way to be
 *  silently wrong — checked in both directions, since either species could
 *  be the one whose background window runs through the other's edge. */
function backgroundThroughEdge(a: Species, b: Species): WindowConflict | null {
  if (a.modality !== "eels" || b.modality !== "eels") return null;
  const [first, second] = byId(a, b);
  const hits: string[] = [];
  const check = (bg: Species, edge: Species) => {
    if (!bg.windows.background) return;
    const bgWindow = orderWindow(bg.windows.background);
    const edgeSignal = orderWindow(edge.windows.signal);
    const onsetInside = edge.energy >= bgWindow.lo && edge.energy <= bgWindow.hi;
    if (windowsOverlap(bgWindow, edgeSignal) || onsetInside) {
      hits.push(
        `${label(bg)}'s background window [${fmt(bgWindow.lo, "eV")}, `
        + `${fmt(bgWindow.hi, "eV")}] eV runs through ${label(edge)}'s edge.`,
      );
    }
  };
  check(first, second);
  check(second, first);
  if (hits.length === 0) return null;
  return { aId: first.id, bId: second.id, kind: "background", detail: hits.join(" ") };
}

/**
 * All window conflicts among the VISIBLE species — a hidden species maps
 * nothing, so flagging it would train users to ignore the badge. Each
 * unordered pair is reported at most once PER RULE (a pair can appear
 * twice, once as "overlap" and once as "unresolved" — see the module
 * header for why that is not redundant).
 */
export function detectWindowConflicts(
  species: readonly Species[],
): WindowConflict[] {
  const visible = species.filter((s) => s.visible);
  const conflicts: WindowConflict[] = [];
  for (let i = 0; i < visible.length; i++) {
    for (let j = i + 1; j < visible.length; j++) {
      const a = visible[i];
      const b = visible[j];
      if (a.modality !== b.modality) continue; // cannot happen per image; guard anyway
      for (const rule of [signalOverlap, unresolvedLines, backgroundThroughEdge]) {
        const conflict = rule(a, b);
        if (conflict) conflicts.push(conflict);
      }
    }
  }
  return conflicts;
}

/** The conflicts touching one species, found from either end of the pair. */
export function conflictsFor(
  conflicts: readonly WindowConflict[], speciesId: string,
): WindowConflict[] {
  return conflicts.filter((c) => c.aId === speciesId || c.bId === speciesId);
}
