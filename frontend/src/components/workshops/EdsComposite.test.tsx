import { describe, expect, it } from "vitest";

import { EDS_PALETTE, mergeCompositeChannel, type Channel } from "./EdsComposite";

describe("mergeCompositeChannel (picker → composite direct-feed)", () => {
  it("appends a new element with the next palette colour", () => {
    const out = mergeCompositeChannel([], "img-fe", "Fe");
    expect(out).toEqual([
      {
        id: "img-fe",
        el: "Fe",
        color: EDS_PALETTE[0],
        intensity: 1,
        visible: true,
      },
    ]);
  });

  it("assigns palette colours in add order", () => {
    let chs: Channel[] = [];
    chs = mergeCompositeChannel(chs, "img-fe", "Fe");
    chs = mergeCompositeChannel(chs, "img-o", "O");
    chs = mergeCompositeChannel(chs, "img-si", "Si");
    expect(chs.map((c) => c.el)).toEqual(["Fe", "O", "Si"]);
    expect(chs.map((c) => c.color)).toEqual([
      EDS_PALETTE[0],
      EDS_PALETTE[1],
      EDS_PALETTE[2],
    ]);
  });

  it("re-adding an element re-points its map id but keeps user styling", () => {
    const prev: Channel[] = [
      {
        id: "old-fe",
        el: "Fe",
        color: "#123456", // user recoloured
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
      color: "#123456",
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
