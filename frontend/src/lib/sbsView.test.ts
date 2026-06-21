import { describe, expect, it } from "vitest";

import { nextSbsViews } from "./sbsView";
import type { View } from "../store/viewer";

const v = (z: number, px = 0.5, py = 0.5): View => ({ z, px, py });

describe("nextSbsViews (side-by-side zoom coupling)", () => {
  it("zoom-linked: zooming LEFT matches RIGHT's magnification, keeps its pan", () => {
    const left = v(4, 0.2, 0.2); // left's new zoomed view
    const right = v(1, 0.8, 0.8); // right currently panned bottom-right
    const out = nextSbsViews("L", left, "zoom", v(1), right, true);
    expect(out.viewL).toEqual(left); // acted-on pane takes the full view
    expect(out.viewR).toEqual({ z: 4, px: 0.8, py: 0.8 }); // z follows, pan kept
  });

  it("zoom-linked: zooming RIGHT matches LEFT's magnification, keeps its pan", () => {
    const right = v(3, 0.1, 0.1);
    const left = v(1, 0.6, 0.4);
    const out = nextSbsViews("R", right, "zoom", left, v(1), true);
    expect(out.viewR).toEqual(right);
    expect(out.viewL).toEqual({ z: 3, px: 0.6, py: 0.4 });
  });

  it("zoom-unlinked: zoom affects only the acted-on pane", () => {
    const left = v(4);
    const right = v(1, 0.8, 0.8);
    const out = nextSbsViews("L", left, "zoom", v(1), right, false);
    expect(out.viewL).toEqual(left);
    expect(out.viewR).toEqual(right); // untouched
  });

  it("pan never propagates, even when zoom is linked", () => {
    const left = v(2, 0.3, 0.3);
    const right = v(2, 0.7, 0.7);
    const out = nextSbsViews("L", left, "pan", v(2, 0.5, 0.5), right, true);
    expect(out.viewL).toEqual(left);
    expect(out.viewR).toEqual(right); // pan stays per-pane
  });

  it("fit never propagates", () => {
    const left = v(1.5);
    const right = v(2, 0.7, 0.7);
    const out = nextSbsViews("L", left, "fit", v(3), right, true);
    expect(out.viewL).toEqual(left);
    expect(out.viewR).toEqual(right);
  });

  it("falls back to the acted-on view when the other pane has no view yet", () => {
    const left = v(4, 0.2, 0.2);
    const out = nextSbsViews("L", left, "zoom", null, null, true);
    // other pane adopts z + the only center available (first-zoom aligns)
    expect(out.viewR).toEqual({ z: 4, px: 0.2, py: 0.2 });
  });
});
