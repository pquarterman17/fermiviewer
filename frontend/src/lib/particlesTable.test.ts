// Particle results table: AFM height maps add height and volume columns.
import { describe, expect, it } from "vitest";

import type { ParticleRow } from "./api";
import { particlesTable } from "./particlesTable";

const row = (extra: Partial<ParticleRow> = {}): ParticleRow => ({
  id: 1, area: 100, centroid: [10, 20], equiv_diameter: 11.28, mean_intensity: 4,
  area_calibrated: 400, diameter_calibrated: 22.6, circularity: 0.9, aspect_ratio: 1,
  eccentricity: 0, orientation_rad: 0, solidity: 1, feret_max: 14, feret_max_calibrated: 28,
  shape_class: "sphere-like", ...extra,
});

describe("particlesTable", () => {
  it("adds height and volume for a height map", () => {
    const t = particlesTable([row({ height_above_base: 4, volume: 1600 })], "nm",
      { height_unit: "nm", volume_unit: "nm³" });
    expect(t.columns.slice(-2)).toEqual(["height (nm)", "volume (nm³)"]);
    expect(t.rows[0].slice(-2)).toEqual([4, 1600]);
  });

  it("is unchanged without height units", () => {
    const t = particlesTable([row()], "nm");
    expect(t.columns.at(-1)).toBe("class");
    expect(t.rows[0]).toHaveLength(t.columns.length);
  });
});
