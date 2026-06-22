// matchedSpotIndices — maps each matched spot back to its posted-spot index
// for the indexing overlay labels + report (Diffraction #4).

import { describe, expect, it } from "vitest";

import type { PhaseCandidate } from "../../lib/api";
import { matchedSpotIndices } from "./DiffractionWorkshop";

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
