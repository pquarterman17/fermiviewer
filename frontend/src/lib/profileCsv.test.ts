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
