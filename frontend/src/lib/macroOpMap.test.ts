import { describe, expect, it } from "vitest";

import { wireToOp } from "./macroOpMap";

// A trimmed mirror of GET /api/batch/operations' real shape (see
// src/fermiviewer/ops/catalogue.py + catalogue_spectral.py) — just the
// param NAMES each op declares, enough to assert wireToOp never invents a
// param the server schema wouldn't accept.
const OP_PARAM_NAMES: Record<string, string[]> = {
  gaussian: ["sigma"],
  median: ["window_size"],
  unsharp: ["sigma", "amount"],
  butterworth: ["low_cutoff", "high_cutoff", "order"],
  clahe: ["clip_limit", "num_bins"],
  bin: ["bin_size", "mode"],
  plane_level: ["order"],
  morph: ["operation", "radius", "shape"],
  multiotsu: ["n_classes"],
  rotate90: [], rotate180: [], rotate270: [], fliph: [], flipv: [],
  eels_map: ["signal_lo", "signal_hi", "bg_lo", "bg_hi", "method"],
  eels_quantify: [
    "elements", "shells", "z", "onset_ev",
    "signal_windows", "bg_windows", "e0_kv", "beta_mrad", "method",
  ],
  eds_quantify: [
    "elements", "method", "half_window_kev", "thickness_nm", "take_off_angle_deg",
  ],
};

function assertKnownParams(op: string, params: Record<string, unknown>): void {
  const known = OP_PARAM_NAMES[op];
  expect(known).toBeDefined();
  for (const key of Object.keys(params)) {
    expect(known).toContain(key);
  }
}

describe("wireToOp", () => {
  it("maps a POST /api/filter body to its filter op verbatim", () => {
    const step = wireToOp("/api/filter", {
      kind: "gaussian",
      params: { sigma: 2.5 },
    });
    expect(step).toEqual({ op: "gaussian", params: { sigma: 2.5 } });
    assertKnownParams(step!.op, step!.params);
  });

  it("maps a geometry kind with no params", () => {
    const step = wireToOp("/api/filter", { kind: "rotate90", params: {} });
    expect(step).toEqual({ op: "rotate90", params: {} });
  });

  it("has no op for crop or arbitrary-angle rotate", () => {
    expect(wireToOp("/api/filter", { kind: "crop", params: { row0: 1 } })).toBeNull();
    expect(wireToOp("/api/filter", { kind: "rotate", params: { angle: 12 } })).toBeNull();
    expect(wireToOp("/api/filter", { kind: "unknown_kind", params: {} })).toBeNull();
  });

  it("maps /api/eels/map, translating window tuples and omitting an unset background", () => {
    const step = wireToOp("/api/eels/map", {
      signal_window: [708, 758],
      background_window: null,
      method: "powerlaw",
    });
    expect(step).toEqual({
      op: "eels_map",
      params: { signal_lo: 708, signal_hi: 758, method: "powerlaw" },
    });
    assertKnownParams(step!.op, step!.params);
  });

  it("maps /api/eels/map with a background window present", () => {
    const step = wireToOp("/api/eels/map", {
      signal_window: [708, 758],
      background_window: [650, 700],
      method: "powerlaw",
    });
    expect(step!.params).toEqual({
      signal_lo: 708, signal_hi: 758, bg_lo: 650, bg_hi: 700, method: "powerlaw",
    });
  });

  it("maps /api/eels/quantify edges into the op's delimited-string params", () => {
    const step = wireToOp("/api/eels/quantify", {
      edges: [
        {
          element: "Fe", shell: "L", z: 26, onset_ev: 708,
          signal_window: [708, 758], bg_window: [650, 700],
        },
        {
          element: "O", shell: "K", z: 8, onset_ev: 532,
          signal_window: [532, 582], bg_window: [490, 520],
        },
      ],
      e0_kv: 200, beta_mrad: 10, method: "powerlaw",
    });
    expect(step).toEqual({
      op: "eels_quantify",
      params: {
        elements: "Fe,O",
        shells: "L,K",
        z: "26,8",
        onset_ev: "708,532",
        signal_windows: "708:758,532:582",
        bg_windows: "650:700,490:520",
        e0_kv: 200,
        beta_mrad: 10,
        method: "powerlaw",
      },
    });
    assertKnownParams(step!.op, step!.params);
  });

  it("rejects malformed eels/quantify edges (falls back to legacy)", () => {
    expect(
      wireToOp("/api/eels/quantify", { edges: [{ element: "Fe" }] }),
    ).toBeNull();
    expect(wireToOp("/api/eels/quantify", { edges: [] })).toBeNull();
  });

  it("maps /api/eds/quantify elements into a csv string with op defaults", () => {
    const step = wireToOp("/api/eds/quantify", {
      elements: ["Fe", "O"],
      method: "cliff-lorimer",
      thickness_nm: 100,
      take_off_angle_deg: 20,
    });
    expect(step).toEqual({
      op: "eds_quantify",
      params: {
        elements: "Fe,O",
        method: "cliff-lorimer",
        thickness_nm: 100,
        take_off_angle_deg: 20,
      },
    });
    // half_window_kev is intentionally omitted — the op's own default
    // (0.085) applies, matching what the wire endpoint actually ran with.
    assertKnownParams(step!.op, step!.params);
  });

  it("has no op for analyze/eels/eds endpoints outside the catalogue", () => {
    // /analyze/radial uses azimuthal_integrate (sector-masked), a DIFFERENT
    // function from the radial_profile op (centre+n_bins) — not the same
    // operation despite the similar name, so it must not be mapped.
    expect(wireToOp("/api/analyze/radial", { azimuthal: false })).toBeNull();
    expect(wireToOp("/api/analyze/vdf", {})).toBeNull();
    expect(wireToOp("/api/analyze/gpa", {})).toBeNull();
    expect(wireToOp("/api/analyze/particles", {})).toBeNull();
    expect(wireToOp("/api/eels/background", {})).toBeNull();
    expect(wireToOp("/api/eels/thickness", {})).toBeNull();
    expect(wireToOp("/api/eels/kk", {})).toBeNull();
    expect(wireToOp("/api/eels/svd", {})).toBeNull();
    expect(wireToOp("/api/eels/quantify-map", { edges: [] })).toBeNull();
    expect(wireToOp("/api/eds/continuum", {})).toBeNull();
    expect(wireToOp("/api/eds/peakfit", {})).toBeNull();
  });
});
