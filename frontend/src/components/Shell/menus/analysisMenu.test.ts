import { describe, expect, it } from "vitest";

import type { ImageMeta } from "../../../lib/api";
import { roughnessToolFor } from "./analysisMenu";

function meta(parser: string): ImageMeta {
  return {
    id: "i", name: "image", kind: "image", shape: [8, 8], dtype: "float64",
    pixel_size: 1, pixel_unit: "nm", value_unit: "nm", n_channels: null,
    energy_first: null, energy_last: null, energy_units: "", stage_tilt_deg: null,
    meta: { parser },
  };
}

describe("roughnessToolFor", () => {
  it("uses the ISO areal workflow for AFM/SPM height maps", () => {
    expect(roughnessToolFor(meta("nanoscope"))).toBe("afmsurface");
  });

  it("keeps the generic roughness workflow for other images", () => {
    expect(roughnessToolFor(meta("dm4"))).toBe("roughness");
  });
});
