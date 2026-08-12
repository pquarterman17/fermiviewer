import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Spectrum } from "../../lib/api";
import { fanoFwhmKev } from "../../lib/eds/resolution";
import { useEdsEnergyWindow } from "./useEdsEnergyWindow";

const FE_KA = 6.404;

function setup() {
  const recomputeMap = vi.fn();
  const onUnbind = vi.fn();
  const onStatus = vi.fn();
  const view = renderHook(() =>
    useEdsEnergyWindow({ bgMode: "linear", recomputeMap, onUnbind, onStatus }),
  );
  return { view, recomputeMap, onUnbind, onStatus };
}

/** A Gaussian peak of `fwhm` at `centre`, on a flat background. */
function peakAt(centre: number, fwhm: number): Spectrum {
  const sigma = fwhm / (2 * Math.sqrt(2 * Math.LN2));
  const energy: number[] = [];
  const counts: number[] = [];
  for (let i = 0; i < 601; i++) {
    const e = centre - 0.6 + (1.2 * i) / 600;
    energy.push(e);
    counts.push(20 + 4000 * Math.exp(-((e - centre) ** 2) / (2 * sigma ** 2)));
  }
  return { energy, counts, units: "keV" };
}

describe("lock to line", () => {
  it("re-centres a committed window on the line instead of letting it drift", () => {
    const { view } = setup();
    act(() => view.result.current.anchor(FE_KA, FE_KA - 0.085, FE_KA + 0.085));
    // A body drag that would slide the window 0.2 keV off the peak.
    act(() => view.result.current.commit(FE_KA + 0.115, FE_KA + 0.285));
    const { eLo, eHi } = view.result.current;
    expect((eLo + eHi) / 2).toBeCloseTo(FE_KA, 12);
    expect(eHi - eLo).toBeCloseTo(0.17, 12); // width preserved
  });

  it("keeps the element bound while locked, and releases it when unlocked", () => {
    const { view, onUnbind } = setup();
    act(() => view.result.current.anchor(FE_KA, FE_KA - 0.085, FE_KA + 0.085));
    act(() => view.result.current.commit(6.3, 6.6));
    expect(onUnbind).not.toHaveBeenCalled();
    expect(view.result.current.lineKev).toBe(FE_KA);

    act(() => view.result.current.setLocked(false));
    act(() => view.result.current.commit(6.3, 6.6));
    expect(onUnbind).toHaveBeenCalledTimes(1);
    expect(view.result.current.lineKev).toBeNull();
    expect(view.result.current.eLo).toBe(6.3);
    expect(view.result.current.eHi).toBe(6.6);
  });

  it("orders an inverted window either way round", () => {
    const { view } = setup();
    act(() => view.result.current.setLocked(false));
    act(() => view.result.current.commit(6.6, 6.3));
    expect(view.result.current.eLo).toBe(6.3);
    expect(view.result.current.eHi).toBe(6.6);
  });

  it("has nothing to lock to on a free window, and says so with a null line", () => {
    const { view, onUnbind } = setup();
    act(() => view.result.current.release(6.3, 6.6));
    expect(view.result.current.lineKev).toBeNull();
    act(() => view.result.current.commit(1.0, 1.4));
    // No anchor ⇒ locked or not, the edit lands where it was put...
    expect(view.result.current.eLo).toBe(1.0);
    // ...and cannot "unbind" an element that was never bound.
    expect(onUnbind).toHaveBeenCalledTimes(1);
  });

  it("refetches the element map exactly once per commit, never per live frame", () => {
    const { view, recomputeMap } = setup();
    act(() => view.result.current.live(6.3, 6.4));
    act(() => view.result.current.live(6.3, 6.5));
    expect(recomputeMap).not.toHaveBeenCalled();
    act(() => view.result.current.commit(6.3, 6.5));
    expect(recomputeMap).toHaveBeenCalledTimes(1);
    expect(recomputeMap).toHaveBeenCalledWith(6.3, 6.5, "linear");
  });
});

describe("width presets", () => {
  it("measures the preset at the line while locked to one", () => {
    const { view } = setup();
    act(() => view.result.current.anchor(FE_KA, FE_KA - 0.085, FE_KA + 0.085));
    act(() => view.result.current.applyPreset("narrow"));
    const { eLo, eHi } = view.result.current;
    expect(eHi - eLo).toBeCloseTo(fanoFwhmKev(FE_KA), 9); // narrow = 1.0 × FWHM
    expect((eLo + eHi) / 2).toBeCloseTo(FE_KA, 12);
  });

  it("falls back to the window's own centre when nothing is anchored", () => {
    const { view } = setup();
    act(() => view.result.current.release(1.4, 1.6));
    expect(view.result.current.anchorKev).toBeCloseTo(1.5, 12);
    act(() => view.result.current.applyPreset("wide"));
    const { eLo, eHi } = view.result.current;
    expect(eHi - eLo).toBeCloseTo(fanoFwhmKev(1.5) * 2, 9); // wide = 2.0 × FWHM
    expect((eLo + eHi) / 2).toBeCloseTo(1.5, 12);
  });
});

describe("fit width", () => {
  it("sets the window from the measured peak and re-anchors on it", () => {
    const { view, onStatus } = setup();
    // The peak sits 30 eV above the tabulated line and is 1.5× wider than the
    // detector model — exactly the case the preset alone gets wrong.
    const measuredFwhm = fanoFwhmKev(FE_KA) * 1.5;
    act(() => view.result.current.anchor(FE_KA, FE_KA - 0.085, FE_KA + 0.085));
    act(() => view.result.current.applyFit(peakAt(FE_KA + 0.03, measuredFwhm)));
    const { eLo, eHi } = view.result.current;
    expect((eLo + eHi) / 2).toBeCloseTo(FE_KA + 0.03, 3);
    expect(eHi - eLo).toBeCloseTo(measuredFwhm * 1.5, 3); // standard = 1.5 × FWHM
    expect(view.result.current.lineKev).toBeCloseTo(FE_KA + 0.03, 3);
    expect(onStatus.mock.calls[0][0]).toMatch(/measured FWHM/);
  });

  it("leaves the window untouched and says why when there is no peak", () => {
    const { view, onStatus, recomputeMap } = setup();
    act(() => view.result.current.anchor(FE_KA, FE_KA - 0.085, FE_KA + 0.085));
    recomputeMap.mockClear();
    const flat: Spectrum = {
      energy: [6.3, 6.35, 6.4, 6.45, 6.5],
      counts: [10, 10, 10, 10, 10],
      units: "keV",
    };
    act(() => view.result.current.applyFit(flat));
    expect(view.result.current.eLo).toBeCloseTo(FE_KA - 0.085, 12);
    expect(view.result.current.eHi).toBeCloseTo(FE_KA + 0.085, 12);
    expect(recomputeMap).not.toHaveBeenCalled();
    expect(onStatus.mock.calls[0][0]).toMatch(/no resolved peak/);
  });

  it("does nothing at all without a spectrum", () => {
    const { view, onStatus, recomputeMap } = setup();
    act(() => view.result.current.applyFit(null));
    expect(recomputeMap).not.toHaveBeenCalled();
    expect(onStatus).not.toHaveBeenCalled();
  });
});
