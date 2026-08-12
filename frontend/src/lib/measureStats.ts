// Aggregate statistics across all measurements on a single image.
// Mirrors fermi-viewer/+fermiViewer/+analysis/displayMeasurementStats.m
// which reports: N, mean ± std, min, max over distance-like measures.
// Extended here to angle and ROI groups, matching the MATLAB groupings
// used in the status-bar message and the Stats results window.
//
// Pure module — no React, no Zustand.  All inputs are plain values.

import {
  areaPxToPhysical,
  physAngle,
  polygonStats,
  tiltDist,
  type TiltSettings,
} from "./geometry";
import type { RoiStats } from "./api";
import type { Measure } from "../store/viewer";

// ---------------------------------------------------------------------------
// Input shape
// ---------------------------------------------------------------------------

export interface MeasureStatsInput {
  measures: Measure[];
  /** Image dimensions in pixels (for de-normalising pts). */
  img: { w: number; h: number };
  /** Calibrated pixel size (null → pixel units). */
  pixelSize: number | null;
  /** Pixel unit label, e.g. "nm". */
  pixelUnit: string;
  /** Per-image tilt settings (#34).  null or angle===0 → no correction. */
  tilt: TiltSettings | null;
  /** ROI intensity stats keyed by measure id (may be empty). */
  roiStats: Record<string, RoiStats>;
}

// ---------------------------------------------------------------------------
// Output shape
// ---------------------------------------------------------------------------

/** Stats for a group of same-kind numeric scalar measures. */
export interface GroupStats {
  /** Human label matching the MATLAB title: "Distance", "Angle", "ROI" */
  label: string;
  /** Unit string appended to values, e.g. "nm", "px", "°" */
  unit: string;
  count: number;
  mean: number;
  std: number;
  min: number;
  max: number;
  /** Linear-interpolation median/quartiles (#6/audit R6) — same method as
   *  calc/distributions.py's PopulationSummary (numpy's default percentile
   *  method), so a group's spread reads consistently whether it came from
   *  a handful of manual measurements here or a particle/grain population
   *  from PopulationHistogram. NaN for an empty group (never reached: the
   *  caller only pushes a group when count >= 1). */
  median: number;
  q1: number;
  q3: number;
  /** Individual values (sorted ascending) — used for the MATLAB rank plot. */
  values: number[];
}

export interface MeasureStats {
  /** Total across ALL measure kinds (all groups combined). */
  total: number;
  /** Per-kind group entries, only populated when count ≥ 1. */
  groups: GroupStats[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Mean, population standard deviation (n divisor — MATLAB
 * displayMeasurementStats uses the same numel denominator, as does
 * MeasurePanel's showStats(), not the n-1 sample-std convention) and count
 * of a plain numeric array. Exported so other pure modules — notably
 * lib/projectCompare.ts's per-sample result-vs-parameter roll-up (W4 item
 * 24) — share this exact arithmetic rather than a second hand-rolled copy
 * that could drift from it. `{ mean: NaN, std: NaN, n: 0 }` for an empty
 * array; never divides by zero.
 */
export function meanSd(values: number[]): { mean: number; std: number; n: number } {
  const n = values.length;
  if (n === 0) return { mean: NaN, std: NaN, n: 0 };
  const mean = values.reduce((s, v) => s + v, 0) / n;
  const std = Math.sqrt(values.reduce((s, v) => s + (v - mean) ** 2, 0) / n);
  return { mean, std, n };
}

/** Linear-interpolation percentile over an ALREADY-SORTED ascending array
 *  (numpy's default `np.percentile` method — "Type 7" in Hyndman & Fan
 *  1996 — the same convention calc/distributions.py's summarize() uses). */
function percentile(sorted: number[], p: number): number {
  const n = sorted.length;
  if (n === 0) return NaN;
  const rank = (p / 100) * (n - 1);
  const lo = Math.floor(rank);
  const hi = Math.ceil(rank);
  if (lo === hi) return sorted[lo];
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (rank - lo);
}

function groupOf(values: number[], label: string, unit: string): GroupStats {
  const sorted = [...values].sort((a, b) => a - b);
  const { mean, std } = meanSd(sorted);
  return {
    label,
    unit,
    count: sorted.length,
    mean,
    std,
    min: sorted[0],
    max: sorted[sorted.length - 1],
    median: percentile(sorted, 50),
    q1: percentile(sorted, 25),
    q3: percentile(sorted, 75),
    values: sorted,
  };
}

// ---------------------------------------------------------------------------
// Main computation
// ---------------------------------------------------------------------------

/**
 * Compute aggregate statistics across all measurements on an image.
 *
 * Groupings (matching displayMeasurementStats.m):
 *   "Distance" — distance / profile / polyline lengths (tilt-corrected #34)
 *   "Angle"    — angle measurements (degrees)
 *   "ROI"      — roi / ellipse mean intensities (from roiStats)
 *   "Area"     — polygon / lasso areas (item 14; physical when calibrated)
 *
 * @returns MeasureStats with .total and .groups (empty groups omitted).
 *
 * Reference:
 *   fermi-viewer/+fermiViewer/+analysis/displayMeasurementStats.m
 *   title: "N=%d, Mean=%.2f, Std=%.2f, Min=%.2f, Max=%.2f"
 *   statusMsg: "Stats: N=%d, mean=%.2f ± %.2f"
 */
export function computeMeasureStats(input: MeasureStatsInput): MeasureStats {
  const { measures, img, pixelSize, pixelUnit, tilt, roiStats } = input;

  const distVals: number[] = [];
  const angleVals: number[] = [];
  const roiVals: number[] = [];
  const areaVals: number[] = [];

  const unit = pixelSize != null ? pixelUnit : "px";

  for (const m of measures) {
    const px = m.pts.map((p) => ({ x: p.x * img.w, y: p.y * img.h }));

    if (
      m.kind === "distance" ||
      m.kind === "profile" ||
      m.kind === "polyline"
    ) {
      let total = 0;
      for (let i = 1; i < px.length; i++) {
        total += tiltDist(px[i - 1], px[i], pixelSize, tilt).value;
      }
      // only push if there are at least 2 points (segment exists)
      if (px.length >= 2) distVals.push(total);
    } else if (m.kind === "angle" && px.length === 3) {
      angleVals.push(physAngle(px[1], px[0], px[2]));
    } else if (m.kind === "roi" || m.kind === "ellipse") {
      const s = roiStats[m.id];
      if (s !== undefined) roiVals.push(s.mean);
    } else if (m.kind === "polygon" || m.kind === "lasso") {
      const areaPx2 = polygonStats(px).areaPx2;
      areaVals.push(areaPxToPhysical(areaPx2, pixelSize) ?? areaPx2);
    }
    // annotations (text/arrow/box/circle) carry no numeric value → skipped
  }

  const groups: GroupStats[] = [];
  if (distVals.length > 0)
    groups.push(groupOf(distVals, "Distance", unit));
  if (angleVals.length > 0)
    groups.push(groupOf(angleVals, "Angle", "°"));
  if (roiVals.length > 0)
    groups.push(groupOf(roiVals, "ROI mean", "counts"));
  if (areaVals.length > 0)
    groups.push(groupOf(areaVals, "Area", `${unit}²`));

  return { total: measures.length, groups };
}

// ---------------------------------------------------------------------------
// Format helpers used by the UI
// ---------------------------------------------------------------------------

/** One-liner status-bar string matching the MATLAB statusMsg format:
 *  "Stats: N=3, mean=2.45 ± 0.12 nm" — uses the Distance group when
 *  present, otherwise the first available group. */
export function statsStatusLine(stats: MeasureStats): string {
  const g = stats.groups[0];
  if (!g) return `Stats: N=${stats.total} (no numeric measures)`;
  return (
    `Stats: N=${g.count}, mean=${g.mean.toFixed(2)} ` +
    `± ${g.std.toFixed(2)} ${g.unit}`
  );
}
