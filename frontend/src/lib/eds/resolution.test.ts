// LOCKSTEP: the sample values below are the same ones
// tests/test_eds_calib.py::test_fano_fwhm_matches_frontend_port asserts on the
// Python side. If you change a constant in resolution.ts or eds_calib.py, both
// suites go red — which is the point. Do not update one table alone.

import { describe, expect, it } from "vitest";

import { fanoFwhmEv, fanoFwhmKev, MN_KA_FWHM_EV, MN_KA_KEV } from "./resolution";

/** keV → FWHM eV, from calc.eds_calib.fano_fwhm. */
const REFERENCE: [number, number][] = [
  [0.277, 49.971549], // C-Kα
  [1.0, 65.949899],
  [5.899, 130.0], // the Mn-Kα anchor, exact by construction
  [8.048, 149.684545], // Cu-Kα
  [15.0, 200.538268],
];

describe("fanoFwhmEv", () => {
  it("matches calc/eds_calib.py to 6 decimal places", () => {
    for (const [kev, ev] of REFERENCE) {
      expect(fanoFwhmEv(kev)).toBeCloseTo(ev, 6);
    }
  });

  it("passes exactly through the Mn-Kα anchor it is back-solved from", () => {
    expect(fanoFwhmEv(MN_KA_KEV)).toBeCloseTo(MN_KA_FWHM_EV, 9);
  });

  it("rises monotonically with energy", () => {
    const widths = REFERENCE.map(([kev]) => fanoFwhmEv(kev));
    for (let i = 1; i < widths.length; i++) {
      expect(widths[i]).toBeGreaterThan(widths[i - 1]);
    }
  });

  it("clamps to a real width below the noise floor instead of returning NaN", () => {
    // The variance goes negative far below the anchor; Python clamps at 0 and
    // so must this, or a low-energy line would resize a window to NaN.
    expect(fanoFwhmEv(-100)).toBe(0);
    expect(Number.isNaN(fanoFwhmEv(-100))).toBe(false);
  });

  it("fanoFwhmKev is the same curve in the unit EDS windows use", () => {
    expect(fanoFwhmKev(5.899)).toBeCloseTo(0.13, 12);
  });
});
