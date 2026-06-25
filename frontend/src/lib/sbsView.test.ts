import { describe, expect, it } from "vitest";

import { nextGridViews } from "./sbsView";
import type { View } from "../store/viewer";

const v = (z: number, px = 0.5, py = 0.5): View => ({ z, px, py });

describe("nextGridViews (compare-grid zoom coupling)", () => {
  it("zoom-linked: zooming a pane matches every other pane's magnification, keeps their pan", () => {
    const acted = v(4, 0.2, 0.2); // pane 0's new zoomed view
    const other1 = v(1, 0.8, 0.8); // pane 1 currently panned bottom-right
    const other2 = v(1, 0.1, 0.9);
    const out = nextGridViews(0, acted, "zoom", [v(1), other1, other2], true);
    expect(out[0]).toEqual(acted); // acted-on pane takes the full view
    expect(out[1]).toEqual({ z: 4, px: 0.8, py: 0.8 }); // z follows, pan kept
    expect(out[2]).toEqual({ z: 4, px: 0.1, py: 0.9 });
  });

  it("zoom-linked: zooming a non-zero index propagates to the rest", () => {
    const acted = v(3, 0.1, 0.1);
    const out = nextGridViews(1, acted, "zoom", [v(1, 0.6, 0.4), v(1)], true);
    expect(out[1]).toEqual(acted);
    expect(out[0]).toEqual({ z: 3, px: 0.6, py: 0.4 });
  });

  it("zoom-unlinked: zoom affects only the acted-on pane", () => {
    const acted = v(4);
    const other = v(1, 0.8, 0.8);
    const out = nextGridViews(0, acted, "zoom", [v(1), other], false);
    expect(out[0]).toEqual(acted);
    expect(out[1]).toEqual(other); // untouched
  });

  it("pan never propagates, even when zoom is linked", () => {
    const acted = v(2, 0.3, 0.3);
    const other = v(2, 0.7, 0.7);
    const out = nextGridViews(0, acted, "pan", [v(2, 0.5, 0.5), other], true);
    expect(out[0]).toEqual(acted);
    expect(out[1]).toEqual(other); // pan stays per-pane
  });

  it("fit never propagates", () => {
    const acted = v(1.5);
    const other = v(2, 0.7, 0.7);
    const out = nextGridViews(0, acted, "fit", [v(3), other], true);
    expect(out[0]).toEqual(acted);
    expect(out[1]).toEqual(other);
  });

  it("falls back to the acted-on view when another pane has no view yet", () => {
    const acted = v(4, 0.2, 0.2);
    const out = nextGridViews(0, acted, "zoom", [null, null], true);
    // the empty pane adopts z + the only center available (first-zoom aligns)
    expect(out[1]).toEqual({ z: 4, px: 0.2, py: 0.2 });
  });

  it("returns a fresh array (does not mutate the input)", () => {
    const input = [v(1), v(1)];
    const out = nextGridViews(0, v(2), "zoom", input, true);
    expect(out).not.toBe(input);
    expect(input[1]).toEqual(v(1)); // original untouched
  });
});
