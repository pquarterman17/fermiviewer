import { describe, expect, it } from "vitest";

import type { ImageMeta } from "./api";
import { isSpmImage } from "./spm";

function meta(parser: string): ImageMeta {
  return {
    id: "i", name: "image", kind: "image", shape: [8, 8], dtype: "float64",
    pixel_size: 1, pixel_unit: "nm", value_unit: "nm", n_channels: null,
    energy_first: null, energy_last: null, energy_units: "", stage_tilt_deg: null,
    meta: { parser },
  };
}

describe("isSpmImage", () => {
  it.each(["nanoscope", "gwyddion", "asylum", "jpk", "wsxm", "nanosurf", "ntmdt", "nanonis"])(
    "recognizes the %s parser",
    (parser) => expect(isSpmImage(meta(parser))).toBe(true),
  );

  it("does not classify unrelated or absent parser metadata as SPM", () => {
    expect(isSpmImage(meta("dm4"))).toBe(false);
    expect(isSpmImage(null)).toBe(false);
  });
});
