import { describe, expect, it } from "vitest";

import type { RegionPreviewResponse } from "./api/regions";
import { areaLabel, formatRegionPreview, fractionLabel } from "./regionPreviewFormat";

const base: RegionPreviewResponse = {
  pixel_count: 1234,
  image_pixels: 10000,
  fraction: 0.1234,
  rect: [1, 1, 40, 40],
  bbox_pixels: 1600,
  exact_mask: true,
  area_calibrated: 4.567,
  unit: "nm",
  provenance: {},
  mask_png: null,
};

describe("formatRegionPreview", () => {
  it("reads as pixels, share, area and the box an exact mask sits in", () => {
    expect(formatRegionPreview(base)).toBe(
      "1,234 px · 12.3 % of image · 4.57 nm² · exact mask in a 1,600 px box",
    );
  });

  it("says whole image instead of 100 %, and omits an unknown area", () => {
    expect(
      formatRegionPreview({ ...base, fraction: 1, exact_mask: false, area_calibrated: null }),
    ).toBe("1,234 px · whole image");
  });

  it("keeps two figures for tiny shares", () => {
    expect(fractionLabel(0.00123)).toBe("0.12 % of image");
    expect(fractionLabel(0.5)).toBe("50.0 % of image");
  });

  it("trims trailing zeros from areas", () => {
    expect(areaLabel(1234.5, "µm")).toBe("1230 µm²");
    expect(areaLabel(0.04567, "nm")).toBe("0.0457 nm²");
  });
});
