import { describe, expect, it } from "vitest";

import { formatCountTick, normalizeEdsSpectrum } from "./edsSpectrumDisplay";

describe("EDS spectrum display", () => {
  it("normalizes eV calibrations to the keV used by EDS controls", () => {
    const source = {
      energy: [490, 540, 590],
      counts: [1, 2, 3],
      units: "eV",
    };

    expect(normalizeEdsSpectrum(source)).toEqual({
      energy: [0.49, 0.54, 0.59],
      counts: [1, 2, 3],
      units: "keV",
    });
    expect(source.energy).toEqual([490, 540, 590]);
  });

  it("leaves canonical keV spectra unchanged", () => {
    const source = { energy: [0, 10], counts: [2, 4], units: "keV" };
    expect(normalizeEdsSpectrum(source)).toBe(source);
  });

  it("formats large whole-cube totals without clipped digit strings", () => {
    expect(formatCountTick(0)).toBe("0");
    expect(formatCountTick(125_000)).toBe("125k");
    expect(formatCountTick(1_250_000)).toBe("1.25M");
    expect(formatCountTick(2_500_000_000)).toBe("2.5G");
  });
});
