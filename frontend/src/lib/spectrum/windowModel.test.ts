import { describe, expect, it } from "vitest";

import type { Spectrum } from "../api";
import { integrateWindow } from "../eds/integrate";
import { integrateEdge } from "../eels/integrate";
import type { SpeciesWindows } from "./species";
import {
  applyDrag,
  cursorFor,
  dragTargets,
  hitTest,
  integrateWindows,
  nudge,
} from "./windowModel";

const SPEC: Spectrum = {
  energy: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
  counts: [5, 5, 5, 40, 80, 40, 5, 5, 5, 5, 5],
  units: "keV",
};

const EDS: SpeciesWindows = { signal: { lo: 2.5, hi: 5.5 } };
const EELS: SpeciesWindows = {
  signal: { lo: 2.5, hi: 5.5 },
  background: { lo: 0, hi: 2 },
};

// identity px mapping for hit tests: 1 energy unit = 1 px
const toPx = (v: number) => v;
const toVal = (px: number) => px;

describe("integrateWindows", () => {
  it("dispatches EDS to the EDS port unchanged", () => {
    const via = integrateWindows(SPEC, "eds", EDS, { eds: { bg: "linear" } })!;
    const direct = integrateWindow(SPEC, 2.5, 5.5, "linear")!;
    expect(via.net).toBe(direct.net);
    expect(via.sigma).toBe(direct.sigma);
    expect(via.background).toBe(direct.background);
  });

  it("dispatches EELS to the EELS port unchanged", () => {
    const via = integrateWindows(SPEC, "eels", EELS)!;
    const direct = integrateEdge(SPEC, EELS.signal, EELS.background)!;
    expect(via.net).toBe(direct.net);
    expect(via.background).toBe(direct.background_counts);
  });

  it("returns null for a channel-less signal window in both modalities", () => {
    const empty: SpeciesWindows = { signal: { lo: 90, hi: 95 } };
    expect(integrateWindows(SPEC, "eds", empty)).toBeNull();
    expect(integrateWindows(SPEC, "eels", empty)).toBeNull();
  });

  it("orders an inverted signal window before integrating", () => {
    const inverted: SpeciesWindows = { signal: { lo: 5.5, hi: 2.5 } };
    expect(integrateWindows(SPEC, "eds", inverted)!.net).toBe(
      integrateWindows(SPEC, "eds", EDS)!.net,
    );
  });
});

describe("dragTargets", () => {
  it("gives one window three targets, edges first", () => {
    expect(dragTargets(EDS)).toEqual([
      { window: "signal", part: "lo" },
      { window: "signal", part: "hi" },
      { window: "signal", part: "body" },
    ]);
  });

  it("gives an EELS pair six targets, all edges before any body", () => {
    const targets = dragTargets(EELS);
    expect(targets).toHaveLength(6);
    const firstBody = targets.findIndex((t) => t.part === "body");
    expect(targets.slice(0, firstBody).every((t) => t.part !== "body")).toBe(true);
    expect(targets.filter((t) => t.window === "background")).toHaveLength(3);
  });
});

describe("applyDrag / nudge", () => {
  it("moves one edge and leaves the other", () => {
    const next = applyDrag(EDS, { window: "signal", part: "lo" }, 1.5);
    expect(next.signal).toEqual({ lo: 1.5, hi: 5.5 });
  });

  it("re-orders when an edge is dragged past its partner", () => {
    const next = applyDrag(EDS, { window: "signal", part: "lo" }, 7);
    expect(next.signal).toEqual({ lo: 5.5, hi: 7 });
  });

  it("slides the body preserving the span and the grab point", () => {
    const next = applyDrag(EDS, { window: "signal", part: "body" }, 6, 1);
    expect(next.signal.lo).toBeCloseTo(5, 12);
    expect(next.signal.hi).toBeCloseTo(8, 12);
  });

  it("drags the background window independently of the signal", () => {
    const next = applyDrag(EELS, { window: "background", part: "hi" }, 2.4);
    expect(next.background).toEqual({ lo: 0, hi: 2.4 });
    expect(next.signal).toEqual(EELS.signal);
  });

  it("ignores a background target when no background window exists", () => {
    expect(applyDrag(EDS, { window: "background", part: "lo" }, 1)).toBe(EDS);
  });

  it("nudges a whole window by a delta", () => {
    const next = nudge(EDS, "signal", 0.5);
    expect(next.signal).toEqual({ lo: 3, hi: 6 });
  });
});

describe("hitTest", () => {
  const W: SpeciesWindows = { signal: { lo: 30, hi: 70 } };

  it("hits an edge within the pixel tolerance", () => {
    expect(hitTest(W, 32, toPx, toVal, 5)).toMatchObject({
      window: "signal",
      part: "lo",
    });
    expect(hitTest(W, 68, toPx, toVal, 5)).toMatchObject({ part: "hi" });
  });

  it("prefers the edge over the body inside the tolerance band", () => {
    expect(hitTest(W, 34, toPx, toVal, 5)!.part).toBe("lo");
  });

  it("hits the body between the edges, remembering the grab offset", () => {
    const hit = hitTest(W, 50, toPx, toVal, 5)!;
    expect(hit.part).toBe("body");
    expect(hit.grabOffset).toBe(20);
  });

  it("resolves a thin window to the nearer edge", () => {
    const thin: SpeciesWindows = { signal: { lo: 50, hi: 53 } };
    expect(hitTest(thin, 49, toPx, toVal, 5)!.part).toBe("lo");
    expect(hitTest(thin, 54, toPx, toVal, 5)!.part).toBe("hi");
  });

  it("misses outside the window and tolerance", () => {
    expect(hitTest(W, 10, toPx, toVal, 5)).toBeNull();
  });

  it("hit-tests EELS background edges too", () => {
    const eels: SpeciesWindows = {
      signal: { lo: 30, hi: 70 },
      background: { lo: 5, hi: 20 },
    };
    expect(hitTest(eels, 19, toPx, toVal, 5)).toMatchObject({
      window: "background",
      part: "hi",
    });
    expect(hitTest(eels, 12, toPx, toVal, 5)).toMatchObject({
      window: "background",
      part: "body",
    });
  });

  it("maps hits to cursors", () => {
    expect(cursorFor(hitTest(W, 30, toPx, toVal, 5))).toBe("ew-resize");
    expect(cursorFor(hitTest(W, 50, toPx, toVal, 5))).toBe("grab");
    expect(cursorFor(null)).toBe("");
  });
});
