// atomsExportCsv: header layout, NaN-to-blank for missing strain,
// strain fields included when present.

import { describe, expect, it } from "vitest";

import { atomsExportCsv } from "./api";

const positions: [number, number][] = [
  [10.1234, 20.5678],
  [19.5, 10.2],
];
const amplitude = [1.5, 0.8];

describe("atomsExportCsv", () => {
  it("emits header + one row per column, no strain", () => {
    const csv = atomsExportCsv(positions, amplitude, undefined, undefined);
    const lines = csv.split("\n");
    expect(lines[0]).toBe(
      "x_px,y_px,amplitude,sublattice,exx,eyy,exy,rotation_rad",
    );
    expect(lines).toHaveLength(3); // header + 2 data rows
    // first row: x, y, amplitude, empty sublattice, empty strain cols
    expect(lines[1]).toMatch(/^10\.1234,20\.5678,1\.5,,,,,$/ );
  });

  it("includes sublattice labels when provided", () => {
    const csv = atomsExportCsv(positions, amplitude, [1, 2], undefined);
    const lines = csv.split("\n");
    expect(lines[1]).toMatch(/^10\.1234,20\.5678,1\.5,1,,,,$/ );
    expect(lines[2]).toMatch(/^19\.5000,10\.2000,0\.8,2,,,,$/ );
  });

  it("includes strain fields when valid strain is provided", () => {
    const strain = {
      valid: true,
      exx_mean: 0.001, eyy_mean: -0.002, exy_mean: 0.0,
      exx: [0.001, 0.002],
      eyy: [-0.002, -0.001],
      exy: [0.0, null],
      rotation: [0.0005, null],
      displacement: [[0.1, -0.1], [0.2, 0.0]] as [number, number][],
    };
    const csv = atomsExportCsv(positions, amplitude, [1, 2], strain);
    const lines = csv.split("\n");
    expect(lines[1]).toMatch(/^10\.1234,20\.5678,1\.5,1,0\.001,-0\.002,0,0\.0005$/);
    // null strain (exy, rotation) → blank columns at the end
    expect(lines[2]).toMatch(/,2,0\.002,-0\.001,,$/);
  });
});
