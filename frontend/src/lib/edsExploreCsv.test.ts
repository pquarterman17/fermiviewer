import { describe, expect, it } from "vitest";

import { elementMapCsv, spectrumCsv } from "./edsExploreCsv";
import type { EdsElementMapResult, Spectrum } from "./api";

describe("elementMapCsv", () => {
  it("writes a window/background comment header then the counts grid", () => {
    const m = {
      map: [
        [1, 2],
        [3, 4],
      ],
      shape: [2, 2],
      e_lo: 6.4,
      e_hi: 6.5,
      bg: "linear",
      total_counts: 10,
      map_meta: null,
    } as EdsElementMapResult;
    expect(elementMapCsv(m)).toBe(
      "# EDS element map 6.400-6.500 keV (linear bg)\n" +
        "1.0000,2.0000\n" +
        "3.0000,4.0000",
    );
  });
});

describe("spectrumCsv", () => {
  it("writes an energy_<units>,counts header then paired rows", () => {
    const s = {
      energy: [0, 0.01],
      counts: [5, 7],
      units: "keV",
    } as Spectrum;
    expect(spectrumCsv(s)).toBe(
      "energy_keV,counts\n0.000000,5.000000\n0.010000,7.000000",
    );
  });
});
