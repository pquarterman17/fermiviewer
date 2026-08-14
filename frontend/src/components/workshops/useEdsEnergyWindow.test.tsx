import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Spectrum } from "../../lib/api";
import { fanoFwhmKev } from "../../lib/eds/resolution";
import { edsSpecies } from "../../lib/spectrum/species";
import { selectedSpeciesOf, useSpecies } from "../../store/species";
import { useEdsEnergyWindow } from "./useEdsEnergyWindow";

const IMG = "cube";
const FE_KA = 6.404;

afterEach(() => {
  useSpecies.setState({ byImage: {}, selectedByImage: {}, edsSettingsByImage: {} });
});

/** Mirrors how EdsSpectrumImage actually calls this hook: `species` is
 *  reselected from the store on every render, not a snapshot frozen at
 *  setup time — a commit's store write must be visible on the very next
 *  render, exactly as it is for the real component. */
function setup(imageId: string) {
  const recomputeMap = vi.fn();
  const onStatus = vi.fn();
  const view = renderHook(() => {
    const byImage = useSpecies((s) => s.byImage);
    const selectedByImage = useSpecies((s) => s.selectedByImage);
    const species = selectedSpeciesOf({ byImage, selectedByImage }, imageId);
    return useEdsEnergyWindow({
      imageId,
      species,
      bgMode: "linear",
      recomputeMap,
      onStatus,
    });
  });
  return { view, recomputeMap, onStatus };
}

function windowOf(id: string) {
  const list = useSpecies.getState().byImage[IMG] ?? [];
  return list.find((s) => s.id === id)?.windows.signal;
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
  it("re-centres a committed window on the species' anchor instead of letting it drift", () => {
    const fe = edsSpecies("Fe", "K", FE_KA);
    useSpecies.getState().addSpecies(IMG, fe);
    useSpecies.getState().selectSpecies(IMG, fe.id);
    const { view } = setup(IMG);
    // A body drag that would slide the window 0.2 keV off the peak.
    act(() => view.result.current.commit(FE_KA + 0.115, FE_KA + 0.285));
    const { eLo, eHi } = view.result.current;
    expect((eLo + eHi) / 2).toBeCloseTo(FE_KA, 12);
    expect(eHi - eLo).toBeCloseTo(0.17, 12); // width preserved
    expect(windowOf(fe.id)).toEqual({ lo: eLo, hi: eHi });
  });

  it("commits exactly where dragged when unlocked", () => {
    const fe = edsSpecies("Fe", "K", FE_KA);
    useSpecies.getState().addSpecies(IMG, fe);
    useSpecies.getState().selectSpecies(IMG, fe.id);
    const { view } = setup(IMG);
    act(() => view.result.current.setLocked(false));
    act(() => view.result.current.commit(6.3, 6.6));
    expect(view.result.current.eLo).toBe(6.3);
    expect(view.result.current.eHi).toBe(6.6);
    expect(windowOf(fe.id)).toEqual({ lo: 6.3, hi: 6.6 });
  });

  it("orders an inverted window either way round", () => {
    const fe = edsSpecies("Fe", "K", FE_KA);
    useSpecies.getState().addSpecies(IMG, fe);
    useSpecies.getState().selectSpecies(IMG, fe.id);
    const { view } = setup(IMG);
    act(() => view.result.current.setLocked(false));
    act(() => view.result.current.commit(6.6, 6.3));
    expect(view.result.current.eLo).toBe(6.3);
    expect(view.result.current.eHi).toBe(6.6);
  });

  it("refetches the element map exactly once per commit, never per live frame", () => {
    const fe = edsSpecies("Fe", "K", FE_KA);
    useSpecies.getState().addSpecies(IMG, fe);
    useSpecies.getState().selectSpecies(IMG, fe.id);
    const { view, recomputeMap } = setup(IMG);
    act(() => view.result.current.live(6.3, 6.4));
    act(() => view.result.current.live(6.3, 6.5));
    expect(recomputeMap).not.toHaveBeenCalled();
    // A live frame must not have written the store either.
    expect(windowOf(fe.id)).toEqual(fe.windows.signal);
    act(() => view.result.current.commit(6.3, 6.5));
    expect(recomputeMap).toHaveBeenCalledTimes(1);
  });

  it("does nothing — no store write, no recompute — without a selected species", () => {
    const { view, recomputeMap } = setup(IMG);
    act(() => view.result.current.commit(6.3, 6.5));
    expect(recomputeMap).not.toHaveBeenCalled();
    expect(useSpecies.getState().byImage[IMG]).toBeUndefined();
  });

  it("drops a stale live preview when the selection changes to another species", () => {
    const fe = edsSpecies("Fe", "K", FE_KA);
    const si = edsSpecies("Si", "K", 1.74);
    useSpecies.getState().addSpecies(IMG, fe);
    useSpecies.getState().addSpecies(IMG, si);
    useSpecies.getState().selectSpecies(IMG, fe.id);
    const { view } = setup(IMG);
    act(() => view.result.current.live(6.9, 7.1)); // dragging Fe's window
    act(() => useSpecies.getState().selectSpecies(IMG, si.id)); // user clicked the Si chip mid-drag
    // Si's own committed window shows, not Fe's half-finished drag.
    expect(view.result.current.eLo).toBeCloseTo(si.windows.signal.lo, 12);
    expect(view.result.current.eHi).toBeCloseTo(si.windows.signal.hi, 12);
  });
});

describe("width presets", () => {
  it("measures the preset at the species' anchor", () => {
    const fe = edsSpecies("Fe", "K", FE_KA);
    useSpecies.getState().addSpecies(IMG, fe);
    useSpecies.getState().selectSpecies(IMG, fe.id);
    const { view } = setup(IMG);
    act(() => view.result.current.applyPreset("narrow"));
    const { eLo, eHi } = view.result.current;
    expect(eHi - eLo).toBeCloseTo(fanoFwhmKev(FE_KA), 9); // narrow = 1.0 × FWHM
    expect((eLo + eHi) / 2).toBeCloseTo(FE_KA, 12);
  });
});

describe("fit width", () => {
  it("sets the window from the measured peak without moving the anchor", () => {
    const fe = edsSpecies("Fe", "K", FE_KA);
    useSpecies.getState().addSpecies(IMG, fe);
    useSpecies.getState().selectSpecies(IMG, fe.id);
    const { view, onStatus } = setup(IMG);
    // The peak sits 30 eV above the tabulated line and is 1.5× wider than the
    // detector model — exactly the case the preset alone gets wrong.
    const measuredFwhm = fanoFwhmKev(FE_KA) * 1.5;
    act(() => view.result.current.applyFit(peakAt(FE_KA + 0.03, measuredFwhm)));
    const { eLo, eHi } = view.result.current;
    expect((eLo + eHi) / 2).toBeCloseTo(FE_KA + 0.03, 3);
    expect(eHi - eLo).toBeCloseTo(measuredFwhm * 1.5, 3); // standard = 1.5 × FWHM
    // The anchor (species.energy) is untouched — a later lock still centres
    // on the tabulated line, not the measured one.
    expect(view.result.current.anchorKev).toBe(FE_KA);
    expect(onStatus.mock.calls[0][0]).toMatch(/measured FWHM/);
    expect(windowOf(fe.id)).toEqual({ lo: eLo, hi: eHi });
  });

  it("leaves the window untouched and says why when there is no peak", () => {
    const fe = edsSpecies("Fe", "K", FE_KA);
    useSpecies.getState().addSpecies(IMG, fe);
    useSpecies.getState().selectSpecies(IMG, fe.id);
    const { view, onStatus, recomputeMap } = setup(IMG);
    const flat: Spectrum = {
      energy: [6.3, 6.35, 6.4, 6.45, 6.5],
      counts: [10, 10, 10, 10, 10],
      units: "keV",
    };
    act(() => view.result.current.applyFit(flat));
    expect(view.result.current.eLo).toBeCloseTo(fe.windows.signal.lo, 12);
    expect(view.result.current.eHi).toBeCloseTo(fe.windows.signal.hi, 12);
    expect(recomputeMap).not.toHaveBeenCalled();
    expect(onStatus.mock.calls[0][0]).toMatch(/no resolved peak/);
  });

  it("does nothing at all without a spectrum, or without a selected species", () => {
    const fe = edsSpecies("Fe", "K", FE_KA);
    useSpecies.getState().addSpecies(IMG, fe);
    useSpecies.getState().selectSpecies(IMG, fe.id);
    const { view, onStatus, recomputeMap } = setup(IMG);
    act(() => view.result.current.applyFit(null));
    expect(recomputeMap).not.toHaveBeenCalled();
    expect(onStatus).not.toHaveBeenCalled();

    act(() => useSpecies.getState().selectSpecies(IMG, null));
    act(() => view.result.current.applyFit(peakAt(FE_KA, fanoFwhmKev(FE_KA))));
    expect(useSpecies.getState().byImage[IMG]).toEqual([fe]);
  });
});
