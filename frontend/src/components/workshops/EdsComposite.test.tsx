import { describe, expect, it } from "vitest";

import { elementColor } from "../../lib/eds/elementColors";
import { mergeCompositeChannel, type Channel } from "./EdsComposite";

describe("mergeCompositeChannel (picker → composite direct-feed)", () => {
  it("appends a new element with no stored colour", () => {
    // Colour is resolved from the element-colour registry at blend time, so a
    // channel must not carry one — storing it is what made the same element
    // change colour depending on the order it was added.
    const out = mergeCompositeChannel([], "img-fe", "Fe");
    expect(out).toEqual([
      { id: "img-fe", el: "Fe", intensity: 1, visible: true },
    ]);
  });

  it("resolves a stable per-element colour regardless of add order", () => {
    let forward: Channel[] = [];
    forward = mergeCompositeChannel(forward, "img-fe", "Fe");
    forward = mergeCompositeChannel(forward, "img-o", "O");
    forward = mergeCompositeChannel(forward, "img-si", "Si");
    expect(forward.map((c) => c.el)).toEqual(["Fe", "O", "Si"]);
    expect(new Set(forward.map((c) => elementColor(c.el))).size).toBe(3);

    let reversed: Channel[] = [];
    reversed = mergeCompositeChannel(reversed, "img-si", "Si");
    reversed = mergeCompositeChannel(reversed, "img-o", "O");
    reversed = mergeCompositeChannel(reversed, "img-fe", "Fe");
    expect(reversed.map((c) => elementColor(c.el))).toEqual(
      ["Si", "O", "Fe"].map(elementColor),
    );
  });

  it("re-adding an element re-points its map id but keeps user styling", () => {
    const prev: Channel[] = [
      {
        id: "old-fe",
        el: "Fe",
        intensity: 1.7, // user tweaked
        visible: false, // user hid it
        cmap: "viridis", // user chose a ramp
      },
    ];
    const out = mergeCompositeChannel(prev, "new-fe", "Fe");
    expect(out).toHaveLength(1); // no duplicate row
    expect(out[0]).toEqual({
      id: "new-fe", // pointed at the fresh map
      el: "Fe",
      intensity: 1.7,
      visible: false,
      cmap: "viridis",
    });
  });

  it("does not mutate the previous channel array", () => {
    const prev: Channel[] = [];
    const out = mergeCompositeChannel(prev, "img-fe", "Fe");
    expect(prev).toHaveLength(0);
    expect(out).not.toBe(prev);
  });
});
