// Aggregate statistics across all measurements on a single image.
// Mirrors fermi-viewer/+fermiViewer/+analysis/displayMeasurementStats.m
// which reports: N, mean ± std, min, max over distance-like measures.
// Extended here to angle and ROI groups, matching the MATLAB groupings
// used in the status-bar message and the Stats results window.
//
// Pure module — no React, no Zustand.  All inputs are plain values.

import {
  physAngle,
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

function sampleStd(values: number[], mean: number): number {
  // MATLAB displayMeasurementStats uses population std (numel denominator),
  // consistent with the showStats() function in MeasurePanel which also
  // divides by vals.length (not vals.length-1).
  if (values.length === 0) return 0;
  return Math.sqrt(
    values.reduce((s, v) => s + (v - mean) ** 2, 0) / values.length,
  );
}

function groupOf(values: number[], label: string, unit: string): GroupStats {
  const sorted = [...values].sort((a, b) => a - b);
  const mean = sorted.reduce((s, v) => s + v, 0) / sorted.length;
  return {
    label,
    unit,
    count: sorted.length,
    mean,
    std: sampleStd(sorted, mean),
    min: sorted[0],
    max: sorted[sorted.length - 1],
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
