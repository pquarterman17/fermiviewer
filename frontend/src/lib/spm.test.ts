import { describe, expect, it } from "vitest";

import type { ImageMeta } from "./api";
import { isSpmHeightImage, isSpmImage, supportsSpmChannels } from "./spm";

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

  it("keeps TIFF-backed Park data in SPM UI without promising sibling channels", () => {
    const park = meta("park", "", "AFM image");
    expect(isSpmImage(park)).toBe(true);
    expect(isSpmHeightImage(park)).toBe(false);
    expect(supportsSpmChannels(park)).toBe(false);
    expect(supportsSpmChannels(meta("nanoscope"))).toBe(true);
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

  it("does not mistake a height-error signal for topography", () => {
    expect(isSpmHeightImage(meta("nanoscope", "nm", "Height Error"))).toBe(false);
  });

  it("recognizes structured height provenance on a derived image", () => {
    const derived = meta("derived", "nm", "Height");
    derived.meta = {
      parser: "derived",
      channel: "Height",
      spm_source_parser: "nanoscope",
      spm_channel_kind: "height",
    };
    expect(isSpmImage(derived)).toBe(true);
    expect(isSpmHeightImage(derived)).toBe(true);
  });

  it("rejects structured non-height SPM channels even when their unit is length", () => {
    const error = meta("derived", "nm", "Height");
    error.meta = { parser: "derived", spm_channel_kind: "other" };
    expect(isSpmImage(error)).toBe(true);
    expect(isSpmHeightImage(error)).toBe(false);
  });
});
