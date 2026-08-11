import { describe, expect, it } from "vitest";

import {
  EDS_HALF_WINDOW_KEV,
  EELS_SIGNAL_WIDTH_EV,
  edsDefaultWindows,
  edsSpecies,
  eelsDefaultWindows,
  eelsSpecies,
  orderWindow,
  speciesUnit,
  splitEdgeLabel,
} from "./species";

describe("default windows", () => {
  it("centres the EDS window on the line", () => {
    const { signal } = edsDefaultWindows(6.404);
    expect(signal.lo).toBeCloseTo(6.404 - EDS_HALF_WINDOW_KEV, 10);
    expect(signal.hi).toBeCloseTo(6.404 + EDS_HALF_WINDOW_KEV, 10);
    // the midpoint IS the line — what makes a species and a server-side map
    // agree without being told
    expect((signal.lo + signal.hi) / 2).toBeCloseTo(6.404, 10);
  });

  it("matches the backend's own default half-window", () => {
    // extract_element_maps / /eds/element-maps default to 0.085 keV; a
    // different default here would cut client and server windows differently
    // for the same species.
    expect(EDS_HALF_WINDOW_KEV).toBe(0.085);
  });

  it("runs the EELS window from the onset upward, not centred on it", () => {
    const { signal } = eelsDefaultWindows(708);
    // an edge is a step, not a peak: integrating symmetrically about the
    // onset would put half the window in the pre-edge background
    expect(signal.lo).toBe(708);
    expect(signal.hi).toBe(708 + EELS_SIGNAL_WIDTH_EV);
  });

  it("leaves the EELS background window unset (item 16 is an owner gate)", () => {
    expect(eelsDefaultWindows(532).background).toBeUndefined();
  });

  it("treats a negative width as its magnitude", () => {
    expect(edsDefaultWindows(6.4, -0.1).signal).toEqual(
      edsDefaultWindows(6.4, 0.1).signal,
    );
    expect(eelsDefaultWindows(500, -30).signal.hi).toBe(530);
  });
});

describe("species construction", () => {
  it("gives every species a distinct id", () => {
    const a = edsSpecies("Fe", "K", 6.404);
    const b = edsSpecies("Fe", "K", 6.404);
    expect(a.id).not.toBe(b.id);
  });

  it("carries no colour field — colour resolves from the symbol registry", () => {
    // Pinned deliberately: a colour stored here would be a second source of
    // truth for it, which this repo has already been bitten by once.
    expect(edsSpecies("Fe", "K", 6.404)).not.toHaveProperty("color");
    expect(eelsSpecies("Fe", "L2,3", 708)).not.toHaveProperty("color");
  });

  it("defaults to visible and records its modality", () => {
    expect(edsSpecies("Si", "K", 1.74).visible).toBe(true);
    expect(edsSpecies("Si", "K", 1.74).modality).toBe("eds");
    expect(eelsSpecies("O", "K", 532).modality).toBe("eels");
    expect(eelsSpecies("O", "K", 532, { visible: false }).visible).toBe(false);
  });
});

describe("units", () => {
  it("derives the unit from the modality", () => {
    // EDS surfaces and /eds/element-map(s) speak keV; the EELS edge table and
    // routes speak eV. Deriving rather than storing is what stops a species
    // claiming eV while holding keV numbers.
    expect(speciesUnit("eds")).toBe("keV");
    expect(speciesUnit("eels")).toBe("eV");
  });

  it("keeps the two modalities on their own scales", () => {
    expect(edsSpecies("Fe", "K", 6.404).windows.signal.hi).toBeLessThan(10);
    expect(eelsSpecies("Fe", "L2,3", 708).windows.signal.hi).toBeGreaterThan(700);
  });
});

describe("orderWindow", () => {
  it("sorts an inverted window and leaves a good one alone", () => {
    expect(orderWindow({ lo: 9, hi: 2 })).toEqual({ lo: 2, hi: 9 });
    expect(orderWindow({ lo: 2, hi: 9 })).toEqual({ lo: 2, hi: 9 });
    expect(orderWindow({ lo: 5, hi: 5 })).toEqual({ lo: 5, hi: 5 });
  });
});

describe("splitEdgeLabel", () => {
  it("splits symbol from transition so colour keys on the element alone", () => {
    // "Fe-L2,3" and "Fe-K" must reach elementColor() as "Fe" both times, or
    // one iron gets two colours across the montage and the legend.
    expect(splitEdgeLabel("Fe-L2,3")).toEqual({ symbol: "Fe", transition: "L2,3" });
    expect(splitEdgeLabel("La-M4,5")).toEqual({ symbol: "La", transition: "M4,5" });
    expect(splitEdgeLabel("O-K")).toEqual({ symbol: "O", transition: "K" });
  });

  it("survives a label with no dash", () => {
    expect(splitEdgeLabel("Fe")).toEqual({ symbol: "Fe", transition: "" });
  });

  it("splits on the FIRST dash only, keeping the transition intact", () => {
    expect(splitEdgeLabel("Si-L2,3").transition).toBe("L2,3");
  });
});
