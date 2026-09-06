// profileToCsv / boxProfileToCsv: header provenance + column layout for
// calibrated and uncalibrated profiles, including ragged box axes.

import { describe, expect, it } from "vitest";

import type { BoxProfileResult, ProfileResult } from "./api";
import { boxProfileToCsv, csvBaseName, profileToCsv } from "./profileCsv";

const profile: ProfileResult = {
  dist: [0, 0.5, 1],
  intensity: [10, null, 30],
  length: 1,
  unit: "nm",
  reduce: "sum",
};

describe("profileToCsv", () => {
  it("emits a header block + px and calibrated columns when calibrated", () => {
    const csv = profileToCsv(profile, {
      imageName: "foo.dm4",
      pixelSize: 0.5,
      pixelUnit: "nm",
      kind: "profile",
      width: 8,
      endpointsPx: [
        { x: 12, y: 40 },
        { x: 220, y: 40 },
      ],
    });
    const lines = csv.trimEnd().split("\n");
    expect(lines[0]).toBe("# fermiviewer profile export");
    expect(csv).toContain("# image: foo.dm4");
    expect(csv).toContain("# kind: profile (box-integrated)");
    expect(csv).toContain("# reduce: sum");
    expect(csv).toContain("# integration_width_px: 8");
    expect(csv).toContain("# endpoints_px: (12,40) -> (220,40)");
    expect(csv).toContain("# pixel_size: 0.5 nm/px");
    expect(csv).toContain("position_px,position_nm,intensity_sum");
    // dist 0.5 nm → 1 px; null intensity → blank cell
    expect(lines).toContain("1,0.5,");
    expect(lines).toContain("0,0,10");
    expect(lines).toContain("2,1,30");
  });

  it("drops the calibrated column when uncalibrated", () => {
    const csv = profileToCsv(
      { ...profile, unit: "px", reduce: "mean" },
      { imageName: "bar", pixelSize: null, pixelUnit: "px", kind: "profile" },
    );
    expect(csv).toContain("# pixel_size: uncalibrated");
    expect(csv).toContain("position_px,intensity");
    expect(csv).not.toContain("position_px,position_");
  });
});

const box: BoxProfileResult = {
  x_pos: [0, 1, 2],
  x_intensity: [100, 110, 120],
  y_pos: [0, 1],
  y_intensity: [50, 60],
  pixel_size: 0.5,
  unit: "nm",
  reduce: "sum",
  rect: [40, 12, 120, 220],
};

describe("boxProfileToCsv", () => {
  it("writes both axes side by side and blank-pads the shorter one", () => {
    const csv = boxProfileToCsv(box, {
      imageName: "foo.dm4",
      pixelUnit: "nm",
      kind: "roi",
    });
    const lines = csv.trimEnd().split("\n");
    expect(csv).toContain("# kind: roi (box integration, both axes)");
    expect(csv).toContain("# box_px: rows 40-120, cols 12-220");
    expect(lines).toContain("x_px,x_nm,x_intensity_sum,y_px,y_nm,y_intensity_sum");
    // first data row: x col 0 (0 nm) → 100, y row 0 (0 nm) → 50
    expect(lines).toContain("0,0,100,0,0,50");
    // third row: x has a sample, y is exhausted → blank-padded
    expect(lines).toContain("2,1,120,,,");
  });

  it("drops calibrated columns when uncalibrated", () => {
    const csv = boxProfileToCsv(
      { ...box, pixel_size: null, unit: "px", reduce: "mean" },
      { imageName: "bar", pixelUnit: "px", kind: "roi" },
    );
    expect(csv).toContain("x_px,x_intensity,y_px,y_intensity");
    expect(csv).toContain("0,100,0,50");
    expect(csv).toContain("2,120,,");
  });
});

describe("csvBaseName", () => {
  it("strips a trailing extension", () => {
    expect(csvBaseName("scan.dm4")).toBe("scan");
    expect(csvBaseName("a.b.tif")).toBe("a.b");
    expect(csvBaseName("noext")).toBe("noext");
    expect(csvBaseName(undefined)).toBe("image");
  });
});

// ADR 0008 / 5a-C: an anisotropic image (0.5 nm rows × 2 nm columns) must
// not divide a calibrated path length by the column scale to recover
// pixels, and a box's y axis must take the row extent.
describe("anisotropic pixel_spacing", () => {
  const AFM: [number, number] = [0.5, 2];

  it("profileToCsv recovers position_px from the line geometry, per axis", () => {
    // a vertical 10-px line is 5 nm long; dist samples at 0, 2.5, 5 nm
    const csv = profileToCsv(
      { dist: [0, 2.5, 5], intensity: [1, 2, 3], length: 5, unit: "nm", reduce: "mean" },
      {
        imageName: "afm",
        pixelSize: 2,
        pixelSpacing: AFM,
        pixelUnit: "nm",
        kind: "profile",
        endpointsPx: [
          { x: 4, y: 0 },
          { x: 4, y: 10 },
        ],
      },
    );
    const lines = csv.trimEnd().split("\n");
    expect(csv).toContain("# pixel_size: 2 nm/px");
    expect(csv).toContain("# pixel_spacing: rows 0.5 nm/px, columns 2 nm/px");
    expect(lines).toContain("position_px,position_nm,intensity");
    // dist / pixel_size would have said 1.25 px for the 2.5 nm sample
    expect(lines).toContain("5,2.5,2");
    expect(lines).toContain("10,5,3");
  });

  it("profileToCsv keeps position_px on the drawn line under tilt correction", () => {
    // the backend's dist for a two-point line carries the stage-tilt
    // stretch: a vertical 10 px line (5 nm at 0.5 nm rows) under a 60°
    // surface tilt comes back 10 nm long. Mapping by spacing alone would
    // put the last sample at 20 px; the drawn line is 10 px.
    const csv = profileToCsv(
      { dist: [0, 5, 10], intensity: [1, 2, 3], length: 10, unit: "nm", reduce: "mean" },
      {
        imageName: "afm",
        pixelSize: 2,
        pixelSpacing: AFM,
        pixelUnit: "nm",
        kind: "profile",
        endpointsPx: [
          { x: 4, y: 0 },
          { x: 4, y: 10 },
        ],
      },
    );
    const lines = csv.trimEnd().split("\n");
    expect(lines).toContain("0,0,1");
    expect(lines).toContain("5,5,2");
    expect(lines).toContain("10,10,3");
    expect(lines.at(-1)).toBe("10,10,3");
  });

  it("profileToCsv maps a polyline segment by segment", () => {
    // 10 columns (20 nm) then 10 rows (5 nm): total 25 nm over 20 px
    const csv = profileToCsv(
      { dist: [0, 20, 22.5, 25], intensity: [0, 0, 0, 0], length: 25, unit: "nm", reduce: "mean" },
      {
        imageName: "afm",
        pixelSize: 2,
        pixelSpacing: AFM,
        pixelUnit: "nm",
        kind: "polyline",
        endpointsPx: [
          { x: 0, y: 0 },
          { x: 10, y: 0 },
          { x: 10, y: 10 },
        ],
      },
    );
    const lines = csv.trimEnd().split("\n");
    expect(lines).toContain("10,20,0");
    expect(lines).toContain("15,22.5,0");
    expect(lines).toContain("20,25,0");
  });

  it("profileToCsv drops the px column rather than guess when the geometry is unknown", () => {
    const csv = profileToCsv(
      { dist: [0, 2.5], intensity: [1, 2], length: 2.5, unit: "nm", reduce: "mean" },
      { imageName: "afm", pixelSize: 2, pixelSpacing: AFM, pixelUnit: "nm", kind: "profile" },
    );
    expect(csv).toContain("position_nm,intensity");
    expect(csv).not.toContain("position_px");
  });

  it("a square pair leaves the CSV byte-identical", () => {
    const ctx = {
      imageName: "foo.dm4",
      pixelSize: 0.5,
      pixelUnit: "nm",
      kind: "profile",
      endpointsPx: [
        { x: 12, y: 40 },
        { x: 220, y: 40 },
      ],
    };
    expect(profileToCsv(profile, { ...ctx, pixelSpacing: [0.5, 0.5] })).toBe(
      profileToCsv(profile, ctx),
    );
    const bctx = { imageName: "foo.dm4", pixelUnit: "nm", kind: "roi" };
    expect(boxProfileToCsv(box, { ...bctx, pixelSpacing: [0.5, 0.5] })).toBe(
      boxProfileToCsv(box, bctx),
    );
  });

  it("boxProfileToCsv calibrates x with the column extent and y with the row extent", () => {
    const csv = boxProfileToCsv(
      { ...box, pixel_size: 2 },
      { imageName: "afm", pixelUnit: "nm", pixelSpacing: AFM, kind: "roi" },
    );
    const lines = csv.trimEnd().split("\n");
    expect(csv).toContain("# pixel_spacing: rows 0.5 nm/px, columns 2 nm/px");
    // x col 1 → 2 nm; y row 1 → 0.5 nm (was 2 nm with the column scale)
    expect(lines).toContain("1,2,110,1,0.5,60");
  });
});
