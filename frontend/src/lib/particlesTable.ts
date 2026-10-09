// The Particles results table (ResultsWindow) built from an /analyze/particles
// response. It used to be titled "— nm" while every value in it was in
// pixels: the calibrated fields the server returns went unused. Sizes are
// now shown calibrated, with their unit in the column header, whenever every
// particle carries a calibrated value, and in px otherwise. Centroids stay in
// px (image coordinates, 1-based) and are reported as x = column, y = row.

import type { ParticleRow } from "./api";

export interface ParticlesTableData {
  title: string;
  columns: string[];
  rows: (string | number | null)[][];
}

const sig4 = (v: number) => Number(v.toPrecision(4));

export function particlesTable(
  particles: ParticleRow[],
  unit: string,
  heights?: { height_unit?: string; volume_unit?: string },
): ParticlesTableData {
  // AFM height maps add each particle's height above its substrate and volume
  const hu = heights?.height_unit;
  const vu = heights?.volume_unit;
  const withHeights = !!hu && !!vu;
  const num = (v: number | null | undefined) => (v == null ? null : sig4(v));
  const calibrated =
    particles.length > 0 &&
    unit !== "px" &&
    particles.every(
      (p) => p.area_calibrated != null && p.diameter_calibrated != null,
    );
  const lenUnit = calibrated ? unit : "px";
  return {
    title: `Particles (${particles.length})`,
    columns: [
      "id",
      `area (${lenUnit}²)`,
      `equiv ⌀ (${lenUnit})`,
      "mean I",
      "x (px)",
      "y (px)",
      "circ.",
      "AR",
      "class",
      ...(withHeights ? [`height (${hu})`, `volume (${vu})`] : []),
    ],
    rows: particles.map((p) => [
      p.id,
      calibrated ? sig4(p.area_calibrated!) : p.area,
      sig4(calibrated ? p.diameter_calibrated! : p.equiv_diameter),
      sig4(p.mean_intensity),
      Number(p.centroid[1].toFixed(1)),
      Number(p.centroid[0].toFixed(1)),
      Number(p.circularity.toFixed(2)),
      p.aspect_ratio == null ? null : Number(p.aspect_ratio.toFixed(2)),
      p.shape_class,
      ...(withHeights ? [num(p.height_above_base), num(p.volume)] : []),
    ]),
  };
}
