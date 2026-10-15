import { describe, expect, it } from "vitest";

import type { ImageMeta } from "../../../lib/api";
import { roughnessToolFor } from "./analysisMenu";

function meta(parser: string, valueUnit = "nm", channel = "Height"): ImageMeta {
  return {
    id: "i", name: "image", kind: "image", shape: [8, 8], dtype: "float64",
    pixel_size: 1, pixel_unit: "nm", value_unit: valueUnit, n_channels: null,
    energy_first: null, energy_last: null, energy_units: "", stage_tilt_deg: null,
    meta: { parser, channel },
  };
}

describe("roughnessToolFor", () => {
  it("uses the ISO areal workflow for AFM/SPM height maps", () => {
    expect(roughnessToolFor(meta("nanoscope"))).toBe("afmsurface");
  });

  it("keeps the generic roughness workflow for other images", () => {
    expect(roughnessToolFor(meta("dm4"))).toBe("roughness");
  });

  it.each(["V", "deg", "nN", "MPa"])(
    "does not treat an SPM %s channel as a height map",
    (unit) => expect(roughnessToolFor(meta("nanoscope", unit))).toBe("roughness"),
  );

  it.each(["Deformation", "Indentation"])(
    "keeps length-valued %s channels out of ISO surface analysis",
    (channel) => expect(roughnessToolFor(meta("nanoscope", "nm", channel))).toBe("roughness"),
  );
});
