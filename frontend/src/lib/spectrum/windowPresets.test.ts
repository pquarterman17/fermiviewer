import { describe, expect, it } from "vitest";

import { fanoFwhmKev } from "../eds/resolution";
import { EELS_SIGNAL_WIDTH_EV } from "./species";
import {
  activePreset,
  EELS_PRESET_WIDTH_EV,
  fitPeakWindow,
  measurePeakFwhm,
  presetWidth,
  presetWindows,
} from "./windowPresets";

/** Gaussian peak of the given FWHM on a sloping baseline. */
function gaussian(
  centre: number,
  fwhm: number,
  height: number,
  opts: { n?: number; span?: number; base?: (e: number) => number } = {},
) {
  const { n = 401, span = 1.0, base = () => 0 } = opts;
  const sigma = fwhm / (2 * Math.sqrt(2 * Math.LN2));
  const energy: number[] = [];
  const counts: number[] = [];
  for (let i = 0; i < n; i++) {
    const e = centre - span / 2 + (span * i) / (n - 1);
    energy.push(e);
    counts.push(base(e) + height * Math.exp(-((e - centre) ** 2) / (2 * sigma ** 2)));
  }
  return { energy, counts };
}

describe("presetWindows — EDS", () => {
  it("scales the window with the detector resolution at that line", () => {
    // The point of the feature: a fixed ±85 eV means different things at
    // different energies, a FWHM multiple does not.
    const soft = presetWindows("eds", 0.277, "standard");
    const hard = presetWindows("eds", 8.048, "standard");
    const softWidth = soft.signal.hi - soft.signal.lo;
    const hardWidth = hard.signal.hi - hard.signal.lo;
    expect(hardWidth).toBeGreaterThan(softWidth);
    expect(softWidth).toBeCloseTo(fanoFwhmKev(0.277) * 1.5, 12);
    expect(hardWidth).toBeCloseTo(fanoFwhmKev(8.048) * 1.5, 12);
  });

  it("centres every preset on the line", () => {
    for (const preset of ["narrow", "standard", "wide"] as const) {
      const w = presetWindows("eds", 6.404, preset).signal;
      expect((w.lo + w.hi) / 2).toBeCloseTo(6.404, 12);
    }
  });

  it("orders narrow < standard < wide", () => {
    const width = (p: "narrow" | "standard" | "wide") =>
      presetWidth("eds", 6.404, p);
    expect(width("narrow")).toBeLessThan(width("standard"));
    expect(width("standard")).toBeLessThan(width("wide"));
  });

  it("carries no background window — EDS infers its own", () => {
    expect(presetWindows("eds", 6.404, "wide").background).toBeUndefined();
  });
});

describe("presetWindows — EELS", () => {
  it("runs from the onset upward, not centred on it", () => {
    const w = presetWindows("eels", 532, "standard").signal;
    expect(w.lo).toBe(532);
    expect(w.hi).toBe(532 + EELS_SIGNAL_WIDTH_EV);
  });

  it("uses absolute widths, unchanged by where the edge sits", () => {
    for (const onset of [99, 532, 1560]) {
      expect(presetWidth("eels", onset, "narrow")).toBe(EELS_PRESET_WIDTH_EV.narrow);
    }
  });

  it("re-places the pre-edge background below the onset for every preset", () => {
    const w = presetWindows("eels", 532, "wide");
    expect(w.background).toBeDefined();
    expect(w.background!.hi).toBeLessThan(532);
    expect(w.background!.lo).toBeLessThan(w.background!.hi);
  });

  it("keeps `standard` tied to the species default, not a copy of 50", () => {
    expect(EELS_PRESET_WIDTH_EV.standard).toBe(EELS_SIGNAL_WIDTH_EV);
  });
});

describe("activePreset", () => {
  it("recognises a window a preset produced, in either modality", () => {
    const eds = presetWindows("eds", 6.404, "narrow").signal;
    expect(activePreset("eds", 6.404, eds.hi - eds.lo)).toBe("narrow");
    const eels = presetWindows("eels", 532, "wide").signal;
    expect(activePreset("eels", 532, eels.hi - eels.lo)).toBe("wide");
  });

  it("lights up nothing for a hand-tuned width", () => {
    expect(activePreset("eds", 6.404, 0.211)).toBeNull();
    expect(activePreset("eels", 532, 47)).toBeNull();
  });
});

describe("measurePeakFwhm", () => {
  it("recovers a known Gaussian width", () => {
    const { energy, counts } = gaussian(6.4, 0.15, 1000);
    const fit = measurePeakFwhm(energy, counts, 6.4, 0.3);
    expect(fit?.fwhm).toBeCloseTo(0.15, 3);
    expect(fit?.center).toBeCloseTo(6.4, 4);
  });

  it("measures above a sloping baseline, not from zero", () => {
    // A peak on the bremsstrahlung continuum: half-max taken from zero would
    // read a width far wider than the peak's own.
    const withBase = gaussian(6.4, 0.15, 1000, { base: (e) => 400 - 30 * e });
    const fit = measurePeakFwhm(withBase.energy, withBase.counts, 6.4, 0.3);
    expect(fit?.fwhm).toBeCloseTo(0.15, 2);
  });

  it("finds the peak even when the axis calibration has drifted off it", () => {
    const { energy, counts } = gaussian(6.44, 0.15, 1000, { span: 1.2 });
    const fit = measurePeakFwhm(energy, counts, 6.4, 0.3);
    expect(fit?.center).toBeCloseTo(6.44, 3);
  });

  it("returns null rather than a guess when there is no resolved peak", () => {
    const flat = { energy: [1, 2, 3, 4, 5], counts: [7, 7, 7, 7, 7] };
    expect(measurePeakFwhm(flat.energy, flat.counts, 3, 2)).toBeNull();
    // a monotone ramp maxes out on the span edge — a shoulder, not a peak
    const ramp = { energy: [1, 2, 3, 4, 5], counts: [1, 2, 3, 4, 5] };
    expect(measurePeakFwhm(ramp.energy, ramp.counts, 3, 2)).toBeNull();
    // too few channels to have an interior maximum at all
    expect(measurePeakFwhm([1, 2], [1, 9], 1.5, 1)).toBeNull();
    // a search span that selects nothing
    const { energy, counts } = gaussian(6.4, 0.15, 1000);
    expect(measurePeakFwhm(energy, counts, 6.4, 0)).toBeNull();
    expect(measurePeakFwhm(energy, counts, 99, 0.3)).toBeNull();
  });

  it("returns null when the peak is far wider than the span it is measured in", () => {
    // The trap this guards: with the span sitting entirely on the flanks of a
    // very broad peak, the endpoint baseline is nearly at the apex, so the
    // half-maximum crossings land ~0.14 apart — a tenth of the true 2.0 width.
    // A silently TOO-NARROW window is worse than no fit at all.
    const { energy, counts } = gaussian(6.4, 2.0, 1000, { span: 0.2 });
    expect(measurePeakFwhm(energy, counts, 6.4, 0.1)).toBeNull();
  });

  it("still measures a weak peak that genuinely stands above its background", () => {
    const weak = gaussian(6.4, 0.15, 60, { base: () => 500 });
    expect(measurePeakFwhm(weak.energy, weak.counts, 6.4, 0.3)?.fwhm).toBeCloseTo(
      0.15,
      2,
    );
  });
});

describe("fitPeakWindow", () => {
  it("sets the window from the MEASURED width, not the modelled one", () => {
    // A real peak twice as wide as the detector model predicts (poor
    // resolution, or two unresolved lines) must widen the window to match.
    const modelled = fanoFwhmKev(6.4);
    const { energy, counts } = gaussian(6.4, modelled * 2, 1000);
    const got = fitPeakWindow(energy, counts, 6.4, "narrow");
    expect(got).not.toBeNull();
    expect(got!.fit.fwhm).toBeCloseTo(modelled * 2, 3);
    // narrow = 1.0 x FWHM total
    expect(got!.windows.signal.hi - got!.windows.signal.lo).toBeCloseTo(
      modelled * 2,
      3,
    );
  });

  it("re-centres on the measured peak, not the tabulated line", () => {
    const { energy, counts } = gaussian(6.43, 0.14, 1000, { span: 1.0 });
    const got = fitPeakWindow(energy, counts, 6.4);
    const w = got!.windows.signal;
    expect((w.lo + w.hi) / 2).toBeCloseTo(6.43, 3);
  });

  it("leaves the window alone when there is nothing to fit", () => {
    const flat = { energy: [6.3, 6.4, 6.5], counts: [5, 5, 5] };
    expect(fitPeakWindow(flat.energy, flat.counts, 6.4)).toBeNull();
  });
});
