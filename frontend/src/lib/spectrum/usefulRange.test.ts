import { describe, expect, it } from "vitest";

import type { ImageMeta, Spectrum } from "../api";
import { metadataBeamEnergyKev, usefulSpectrumRange } from "./usefulRange";

function spectrum(counts: number[], start = -0.5, step = 0.1): Spectrum {
  return {
    energy: counts.map((_, index) => start + index * step),
    counts,
    units: "keV",
  };
}

describe("usefulSpectrumRange", () => {
  it("drops negative channels and a long empty detector tail", () => {
    const counts = Array.from({ length: 405 }, (_, index) => {
      const energy = -0.5 + index * 0.1;
      return energy < 0 ? 0 : energy < 8 ? 30 + 500 * Math.exp(-((energy - 6.4) ** 2) / 0.03) : 2;
    });
    const range = usefulSpectrumRange(spectrum(counts));
    expect(range).not.toBeNull();
    expect(range![0]).toBe(0);
    expect(range![1]).toBeGreaterThan(6.4);
    expect(range![1]).toBeLessThan(12);
  });

  it("does not hide a small isolated high-energy peak", () => {
    const counts = Array.from({ length: 301 }, (_, index) =>
      2 + 1000 * Math.exp(-((index - 20) ** 2) / 8) + 20 * Math.exp(-((index - 180) ** 2) / 2),
    );
    expect(usefulSpectrumRange(spectrum(counts, 0, 0.1))![1]).toBeGreaterThan(18);
  });

  it("uses beam metadata as a physical upper bound", () => {
    const counts = Array.from({ length: 401 }, (_, index) => index < 100 ? 20 : 1);
    expect(usefulSpectrumRange(spectrum(counts, 0, 0.1), 15)![1]).toBeLessThanOrEqual(15);
  });

  it("does not let a beam cap change signal detection below that cap", () => {
    const counts = Array.from({ length: 401 }, (_, index) =>
      index < 80 ? 30 + 500 * Math.exp(-((index - 64) ** 2) / 4) : 2,
    );
    const spec = spectrum(counts, 0, 0.1);
    expect(usefulSpectrumRange(spec, 20)).toEqual(usefulSpectrumRange(spec));
  });

  it("returns the complete axis when no narrower useful range is known", () => {
    expect(usefulSpectrumRange(spectrum(Array(50).fill(5), 0, 0.1))).toBeNull();
  });
});

describe("metadataBeamEnergyKev", () => {
  const meta = (values: ImageMeta["meta"]) => ({ meta: values } as ImageMeta);

  it("recognises parser metadata spellings and converts volts", () => {
    expect(metadataBeamEnergyKev(meta({ beam_energy_kev: 15 }))).toBe(15);
    expect(metadataBeamEnergyKev(meta({ beam_kv: 20 }))).toBe(20);
    expect(metadataBeamEnergyKev(meta({ voltage_kV: 30 }))).toBe(30);
    expect(metadataBeamEnergyKev(meta({ acceleration_voltage_v: 200_000 }))).toBe(200);
  });

  it("does not invent a beam energy when metadata is absent", () => {
    expect(metadataBeamEnergyKev(meta({}))).toBeNull();
  });
});
