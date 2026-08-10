// The grain-map click gesture (MAIN_PLAN item 1): split acts on one click,
// merge needs two, and every click must land on a valid 0-based pixel index
// — a click at the exact w/h edge used to be a real 422 from the server.

import { describe, expect, it } from "vitest";

import { grainClickAction } from "./stageGrainEdit";

const IMG = { w: 100, h: 50 };

describe("grainClickAction", () => {
  it("split acts immediately on the grain under the cursor", () => {
    const act = grainClickAction({ x: 10.7, y: 20.2 }, IMG, "split", null);
    expect(act).toEqual({ kind: "edit", op: "split", points: [[10, 20]] });
  });

  it("split ignores any remembered pick (that belongs to merge)", () => {
    const act = grainClickAction({ x: 1.5, y: 2.5 }, IMG, "split", {
      x: 9,
      y: 9,
    });
    expect(act).toEqual({ kind: "edit", op: "split", points: [[1, 2]] });
  });

  it("merge's first click only remembers the pick", () => {
    const act = grainClickAction({ x: 10.7, y: 20.2 }, IMG, "merge", null);
    expect(act).toEqual({ kind: "pick", at: { x: 10, y: 20 } });
  });

  it("merge's second click edits both grains, remembered pick first", () => {
    const act = grainClickAction({ x: 10.7, y: 20.2 }, IMG, "merge", {
      x: 3,
      y: 4,
    });
    expect(act).toEqual({
      kind: "edit",
      op: "merge",
      points: [
        [3, 4],
        [10, 20],
      ],
    });
  });

  it("snaps a click on the exact w/h edge to the last valid pixel index", () => {
    const act = grainClickAction({ x: 100, y: 50 }, IMG, "split", null);
    expect(act).toEqual({ kind: "edit", op: "split", points: [[99, 49]] });
  });

  it("clamps a click dragged off the top-left to pixel 0,0", () => {
    const act = grainClickAction({ x: -4, y: -9 }, IMG, "merge", null);
    expect(act).toEqual({ kind: "pick", at: { x: 0, y: 0 } });
  });
});
