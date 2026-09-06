import type { CalibrationEntry } from "../../lib/api";
import type { Measure } from "../../store/viewer";

export type SpatialAxis = "row" | "column";
export type CalibrationUnit = "nm" | "µm" | "Å" | "pm" | "mm";

const NM_PER_UNIT: Record<CalibrationUnit, number> = {
  pm: 1e-3,
  Å: 0.1,
  nm: 1,
  µm: 1e3,
  mm: 1e6,
};

export interface LineAxisMatch {
  axis: SpatialAxis;
  pixels: number;
}

/** Classify a normalized line within 15 degrees of a spatial axis. */
export function calibrationLineAxis(
  line: Measure | null,
  shape: number[],
): LineAxisMatch | null {
  if (!line || line.pts.length < 2 || shape.length < 2) return null;
  const [height, width] = shape;
  const dx = Math.abs((line.pts[1].x - line.pts[0].x) * width);
  const dy = Math.abs((line.pts[1].y - line.pts[0].y) * height);
  if (dx === 0 && dy === 0) return null;
  const angle = (Math.atan2(dy, dx) * 180) / Math.PI;
  if (angle <= 15) return { axis: "column", pixels: dx };
  if (angle >= 75) return { axis: "row", pixels: dy };
  return null;
}

export function positiveNumber(value: string): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

export function canonicalCalibrationUnit(unit: string): CalibrationUnit | null {
  const normalized = unit.trim().replace(/μ/g, "µ").toLowerCase();
  if (normalized === "um" || normalized === "µm") return "µm";
  if (["a", "å", "ang", "angstrom", "ångström"].includes(normalized)) return "Å";
  if (normalized === "nm" || normalized === "pm" || normalized === "mm") {
    return normalized;
  }
  return null;
}

export function convertCalibrationValue(
  value: number,
  from: CalibrationUnit,
  to: CalibrationUnit,
): number {
  return (value * NM_PER_UNIT[from]) / NM_PER_UNIT[to];
}

export function formatExtent(value: number): string {
  return Number(value.toPrecision(4)).toString();
}

export function calibrationEntryLabel(entry: CalibrationEntry): string {
  const pair = entry.pixel_spacing;
  if (!pair || pair[0] === pair[1]) {
    return `${formatExtent(entry.pixel_size)} ${entry.unit}/px`;
  }
  return (
    `rows ${formatExtent(pair[0])} · columns ${formatExtent(pair[1])} ` +
    `${entry.unit}/px`
  );
}
