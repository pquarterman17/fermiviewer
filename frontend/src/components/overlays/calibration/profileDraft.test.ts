import { describe, expect, it } from "vitest";

import type { CalibrationProfile, ImageMeta } from "../../../lib/api";
import { spatialCalibrationImpact } from "./profileDraft";

const profile = {
  id: "acq", schema: 1, name: "scan", kind: "acquisition", version: 1,
  created_at: "", updated_at: "",
  fields: {
    pixel_size_row: { value: 500, unit: "pm" },
    pixel_size_column: { value: 2, unit: "nm" },
  },
  text: {},
  validity: { valid_from: null, valid_to: null, beam_energy_kev: null, magnification: null, camera_length_mm: null, note: "" },
  provenance: { source: "", date: null, operator: "", note: "" },
} satisfies CalibrationProfile;

const image = {
  id: "im", name: "im", kind: "image", shape: [2, 2], dtype: "float32",
  pixel_size: 2, pixel_spacing: [0.5, 2], pixel_unit: "nm", value_unit: "",
  n_channels: null, energy_first: null, energy_last: null, energy_units: "",
  stage_tilt_deg: null, meta: {},
} satisfies ImageMeta;

describe("spatialCalibrationImpact", () => {
  it("requires the profile pair to share a unit", () => {
    expect(spatialCalibrationImpact(profile, image)).toBeNull();
  });

  it("compares equivalent length units before claiming a replacement", () => {
    const sameUnitPair = {
      ...profile,
      fields: {
        pixel_size_row: { value: 500, unit: "pm" },
        pixel_size_column: { value: 2000, unit: "pm" },
      },
    };
    expect(spatialCalibrationImpact(sameUnitPair, image)).toMatchObject({
      target: "rows 500 · columns 2000 pm/px",
      current: "rows 0.5 · columns 2 nm/px",
      changes: false,
    });
  });
});
