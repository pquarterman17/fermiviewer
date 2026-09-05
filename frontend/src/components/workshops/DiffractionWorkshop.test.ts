// matchedSpotIndices — maps each matched spot back to its posted-spot index
// for the indexing overlay labels + report (Diffraction #4).

import { describe, expect, it } from "vitest";

import type { PhaseCandidate } from "../../lib/api";
import { matchedSpotIndices } from "./DiffractionWorkshop";
import {
  dSpacingToEllipsePx,
  matchedRingSvg,
} from "./diffraction/diffractionGeometry";

function candidate(extra: Partial<PhaseCandidate>): PhaseCandidate {
  return {
    phase: "Si",
    formula: "Si",
    score: 1,
    n_matched: 0,
    matched_hkl: [],
    matched_d: [],
    ref_d: [],
    matched_idx: [],
    zone_axis: [0, 0, 1],
    ...extra,
  };
}

describe("matchedSpotIndices", () => {
  it("uses the exact matched_idx when present", () => {
    const c = candidate({
      matched_d: [2.0, 1.5, 1.2],
      matched_idx: [3, 0, 1],
    });
    // measuredR is irrelevant when matched_idx is provided
    expect(matchedSpotIndices(c, [10, 20, 30, 40], 512, 0.05)).toEqual([3, 0, 1]);
  });

  it("falls back to greedy radius matching when matched_idx is absent", () => {
    // d = W*px/R → with W=512, px=0.05: R=128→d=0.2, R=64→d=0.4, R=256→d=0.1
    // matched_d picks the spots in a scrambled order; greedy must recover them
    const measuredR = [128, 64, 256]; // d = 0.2, 0.4, 0.1
    const c = candidate({
      matched_d: [0.4, 0.1, 0.2],
      matched_idx: [], // force the fallback
    });
    expect(matchedSpotIndices(c, measuredR, 512, 0.05)).toEqual([1, 2, 0]);
  });

  it("falls back when matched_idx length disagrees with matched_d", () => {
    const c = candidate({
      matched_d: [0.2, 0.4],
      matched_idx: [0], // wrong length → ignored
    });
    expect(matchedSpotIndices(c, [128, 64], 512, 0.05)).toEqual([0, 1]);
  });

  it("does not reuse a spot in the greedy fallback", () => {
    const c = candidate({ matched_d: [0.2, 0.2], matched_idx: [] });
    const out = matchedSpotIndices(c, [128, 130], 512, 0.05);
    expect(new Set(out).size).toBe(2); // two distinct spots, no double-use
  });
});

describe("anisotropic constant-d geometry", () => {
  it("is circular for a square real-space field", () => {
    expect(dSpacingToEllipsePx(2, 128, 128, 1, null, 200, 1, [1, 1], "nm"))
      .toEqual({ rx: 64, ry: 64 });
  });

  it("uses both real-space extents in FFT mode", () => {
    expect(dSpacingToEllipsePx(2, 128, 128, 1, null, 200, 1, [2, 1], "nm"))
      .toEqual({ rx: 64, ry: 128 });
  });

  it("inverts a generated FFT's reciprocal axes back to the source aspect", () => {
    // q steps from a 128² source with (row, col) extents (2, 1).
    const q: [number, number] = [1 / 256, 1 / 128];
    expect(dSpacingToEllipsePx(2, 128, 128, 1, null, 200, 1, q, "1/nm"))
      .toEqual({ rx: 64, ry: 128 });
  });

  it("keeps a rectangular uncalibrated FFT physically circular", () => {
    expect(dSpacingToEllipsePx(2, 64, 128, 1, null, 200, 1))
      .toEqual({ rx: 64, ry: 32 });
  });

  it("renders matched rings with both ellipse radii", () => {
    const c = candidate({ matched_d: [2], matched_idx: [0], matched_hkl: [[2, 0, 0]] });
    const nodes = matchedRingSvg(
      c, [10], [65, 65], 1, 128, 1, [[65, 75]], true, false,
      () => ({ rx: 32, ry: 64 }),
    );
    const ring = nodes[0] as { type: string; props: { rx: number; ry: number } };
    expect(ring.type).toBe("ellipse");
    expect(ring.props).toMatchObject({ rx: 32, ry: 64 });
  });

  it("uses per-axis detector extents in camera mode", () => {
    const ring = dSpacingToEllipsePx(2, 128, 128, 0.01, 200, 200, 1, [0.02, 0.01], "mm");
    expect(ring).not.toBeNull();
    expect(ring!.rx / ring!.ry).toBeCloseTo(2);
  });
});
