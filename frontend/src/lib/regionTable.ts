// Per-image region (polygon/lasso) table — the deliverable of the W3
// area-measurement workstream (plan item 15): a row per drawn region with
// its area in physical units, feeding both the Regions inspector card and
// its CSV export. Also exports the pure per-image areas selector that W4
// item 24's result-vs-parameter roll-up consumes directly.
//
// Pure module — no React, no zustand. Areas/perimeter/centroid are
// DERIVED from `pts` + calibration on every call, never read from a
// stored field (ADR 0002): recalibrating pixel_size changes every row
// with no migration step.
//
// This module deliberately does NOT import `Measure`/`MeasureKind` from the
// store. `RegionCandidate.kind` is plain `string` and `REGION_KINDS` is
// tested with `.has()`, which keeps a pure lib module free of store types —
// the same separation `lib/geometry.ts` keeps. The store's real `Measure[]`
// is structurally assignable to `RegionCandidate[]` (every field this needs
// already exists on `Measure`), so callers pass it straight through with no
// cast; a test pins that by feeding a real `Measure[]` in.
//
// It was originally written this way because item 14 had not yet added
// "polygon" | "lasso" to the union. That has since landed, but the
// decoupling is worth keeping on its own merits.

import {
  areaPxToPhysical,
  polygonStatsNormalized,
  polygonStatsNormalizedWithHoles,
  type Size,
} from "./geometry";

/** Structural shape this module needs from a measure. Deliberately not
 *  the store's `Measure` type — see file header. */
export interface RegionCandidate {
  id: string;
  kind: string;
  pts: { x: number; y: number }[];
  /** Enclosed holes (plan item 19) — see Measure.holes (viewerTypes.ts)
   *  for the field's full contract. Absent/empty is the pre-#19 shape. */
  holes?: { x: number; y: number }[][];
  text?: string;
}

/** Measure kinds treated as closed, area-bearing regions. */
export const REGION_KINDS: ReadonlySet<string> = new Set(["polygon", "lasso"]);

/** The subset of ImageMeta a region row needs. */
export interface RegionTableImage {
  /** [h, w, ...] — same convention as ImageMeta.shape. */
  shape: number[];
  pixel_size: number | null;
  pixel_unit: string;
}

export interface RegionRow {
  measureId: string;
  /** Measure.text if set (trimmed, non-empty), else a stable generated
   *  "Region N" — N is the 1-based position among region-kind measures,
   *  in the order they appear in `measures`. */
  label: string;
  kind: string;
  /** px² — always populated, never null. NETS OUT any `holes` (item 19);
   *  identical to the pre-#19 value when there are none. */
  areaPx2: number;
  /** pixel_unit² — null when the image is uncalibrated. Never 0 or NaN
   *  as a stand-in for "unknown"; a null here means "no physical number
   *  exists", not "the area is zero". */
  areaPhysical: number | null;
  perimeterPx: number;
  /** image-pixel coordinates (not normalized). */
  centroid: { x: number; y: number };
  /** number of enclosed holes subtracted from areaPx2 (plan item 19); 0
   *  for every pre-#19 region. */
  holeCount: number;
}

function imgSize(image: RegionTableImage): Size {
  return { w: image.shape[1] ?? 1, h: image.shape[0] ?? 1 };
}

/** ASCII-safe token for a calibration unit, for CSV column headers that
 *  must not depend on the reader's encoding (e.g. "µm" → "um", "Å" →
 *  "A"). Never empty — falls back to "unit". */
export function unitToken(unit: string): string {
  const ascii = unit
    .replace(/[µμ]/g, "u")
    .replace(/Å/g, "A")
    .replace(/[^a-zA-Z0-9]/g, "");
  return ascii || "unit";
}

/** One row per region (polygon/lasso) measure on an image. */
export function regionRows(
  measures: RegionCandidate[],
  image: RegionTableImage,
): RegionRow[] {
  const img = imgSize(image);
  const rows: RegionRow[] = [];
  let n = 0;
  for (const m of measures) {
    if (!REGION_KINDS.has(m.kind)) continue;
    n++;
    // Holes-free path is the exact pre-#19 call — single-ring regions get
    // byte-identical numbers, not just equivalent ones.
    const stats =
      m.holes && m.holes.length > 0
        ? polygonStatsNormalizedWithHoles(m.pts, m.holes, img)
        : polygonStatsNormalized(m.pts, img);
    rows.push({
      measureId: m.id,
      label: m.text?.trim() || `Region ${n}`,
      kind: m.kind,
      areaPx2: stats.areaPx2,
      areaPhysical: areaPxToPhysical(stats.areaPx2, image.pixel_size),
      perimeterPx: stats.perimeterPx,
      centroid: stats.centroid,
      holeCount: m.holes?.length ?? 0,
    });
  }
  return rows;
}

/**
 * Per-image region areas in PHYSICAL units only (skips any region whose
 * image is uncalibrated — there is no physical number to report for it).
 *
 * This is the function W4 item 24's result-vs-parameter roll-up consumes
 * so it does not re-derive the area math: call once per image in a
 * sample group, concatenate, and feed the combined list into
 * lib/measureStats.ts-style mean/sd/n aggregation.
 */
export function regionPhysicalAreas(
  measures: RegionCandidate[],
  image: RegionTableImage,
): number[] {
  const out: number[] = [];
  for (const r of regionRows(measures, image)) {
    if (r.areaPhysical != null) out.push(r.areaPhysical);
  }
  return out;
}

/** CSV header for the physical-area column: states the real calibrated
 *  unit (e.g. "area_um2"), or "area_physical" with no unit when the
 *  image carries no calibration — never a hardcoded "area_um2". */
export function areaPhysicalColumn(image: RegionTableImage): string {
  return image.pixel_size != null
    ? `area_${unitToken(image.pixel_unit)}2`
    : "area_physical";
}

/** Column list for the Regions CSV export (one image per export). */
export function regionCsvColumns(image: RegionTableImage): string[] {
  return [
    "label",
    "kind",
    "area_px2",
    areaPhysicalColumn(image),
    "perimeter_px",
    "centroid_x_px",
    "centroid_y_px",
  ];
}

/** Row data matching regionCsvColumns, in the same order. */
export function regionCsvRows(
  rows: RegionRow[],
): (string | number | null)[][] {
  return rows.map((r) => [
    r.label,
    r.kind,
    r.areaPx2,
    r.areaPhysical,
    r.perimeterPx,
    r.centroid.x,
    r.centroid.y,
  ]);
}
