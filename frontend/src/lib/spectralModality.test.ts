import { beforeEach, describe, expect, it } from "vitest";

import type { ImageMeta } from "./api";
import {
  classifySpectralModality,
  resolveSpectralModality,
  saveSpectralModality,
} from "./spectralModality";

function cube(extra: Partial<ImageMeta> = {}): ImageMeta {
  return {
    id: "cube",
    name: "spectrum.dm4",
    kind: "spectrum_image",
    shape: [16, 16, 1024],
    dtype: "float32",
    pixel_size: 1,
    pixel_unit: "nm",
    value_unit: "counts",
    n_channels: 1024,
    energy_first: null,
    energy_last: null,
    energy_units: "",
    stage_tilt_deg: null,
    meta: {},
    ...extra,
  };
}

describe("spectral modality classification", () => {
  beforeEach(() => localStorage.clear());

  it("recognizes BCF and broad X-ray spectra as EDS", () => {
    expect(
      classifySpectralModality(cube({ meta: { parser: "bcf" } })).modality,
    ).toBe("eds");
    expect(
      classifySpectralModality(
        cube({
          energy_first: 0,
          energy_last: 10.24,
          energy_units: "keV",
        }),
      ).modality,
    ).toBe("eds");
  });

  it("recognizes a narrow core-loss cube as EELS", () => {
    const result = classifySpectralModality(
      cube({ energy_first: 490, energy_last: 590, energy_units: "eV" }),
    );
    expect(result).toEqual({ modality: "eels", reason: "loss-energy range" });
  });

  it("leaves genuinely ambiguous spectra unclassified", () => {
    expect(
      classifySpectralModality(
        cube({ energy_first: 0, energy_last: 2000, energy_units: "eV" }),
      ).modality,
    ).toBeNull();
  });

  it("persists an explicit user choice over inference", () => {
    const meta = cube({
      name: "sample_EELS.dm4",
      energy_first: 200,
      energy_last: 800,
      energy_units: "eV",
    });
    saveSpectralModality(meta, "eds");
    expect(resolveSpectralModality(meta)).toEqual({
      modality: "eds",
      reason: "saved choice",
    });
  });
});
