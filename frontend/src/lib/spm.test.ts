import { describe, expect, it } from "vitest";

import type { ImageMeta } from "./api";
import { isSpmHeightImage, isSpmImage } from "./spm";

function meta(parser: string, valueUnit = "nm", channel = "Height"): ImageMeta {
  return {
    id: "i", name: "image", kind: "image", shape: [8, 8], dtype: "float64",
    pixel_size: 1, pixel_unit: "nm", value_unit: valueUnit, n_channels: null,
    energy_first: null, energy_last: null, energy_units: "", stage_tilt_deg: null,
    meta: { parser, channel },
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

  it("distinguishes height channels from other measurements in an SPM file", () => {
    expect(isSpmHeightImage(meta("nanoscope", "nm"))).toBe(true);
    expect(isSpmHeightImage(meta("nanoscope", "V"))).toBe(false);
    expect(isSpmHeightImage(meta("nanoscope", "MPa"))).toBe(false);
    expect(isSpmHeightImage(meta("nanoscope", "nN"))).toBe(false);
  });

  it.each(["Height Sensor", "Topography", "Z-Axis", "ZSensor"])(
    "recognizes the %s topography channel",
    (channel) => expect(isSpmHeightImage(meta("nanoscope", "nm", channel))).toBe(true),
  );

  it.each(["Deformation", "Indentation", "Adhesion"])(
    "does not classify the length-valued %s channel as topography",
    (channel) => expect(isSpmHeightImage(meta("nanoscope", "nm", channel))).toBe(false),
  );
});
