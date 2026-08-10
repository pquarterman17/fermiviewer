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

  it("omitting pixelSizes reproduces the pre-#9 raw-z matching", () => {
    const acted = v(4, 0.2, 0.2);
    const other = v(1, 0.8, 0.8);
    const out = nextGridViews(0, acted, "zoom", [v(1), other], true);
    expect(out[1]).toEqual({ z: 4, px: 0.8, py: 0.8 });
  });
});

describe("nextGridViews — #9 physical-scale linking across calibrations", () => {
  it("two panes at different pixel sizes: zoom-linking matches PHYSICAL scale, not raw z, so a feature keeps the same screen width", () => {
    // pane 0: pixel_size 2 (coarse); pane 1: pixel_size 5 (fine) — same
    // physical feature must occupy the same screen width in both once linked
    const acted = v(4, 0.5, 0.5); // pane 0 zoomed to z=4
    const other = v(1, 0.3, 0.7); // pane 1's own pan, pre-link
    const out = nextGridViews(0, acted, "zoom", [v(1), other], true, [2, 5]);

    expect(out[0]).toEqual(acted); // acted-on pane unchanged
    expect(out[1]?.px).toBeCloseTo(0.3, 10); // pan preserved
    expect(out[1]?.py).toBeCloseTo(0.7, 10);

    // physicalScale = pixelSize / z must now match across panes
    const scale0 = 2 / out[0]!.z;
    const scale1 = 5 / out[1]!.z;
    expect(scale1).toBeCloseTo(scale0, 10);

    // a 100-unit feature occupies the same screen width in both panes
    const featureUnits = 100;
    const screenWidth0 = (featureUnits / 2) * out[0]!.z;
    const screenWidth1 = (featureUnits / 5) * out[1]!.z;
    expect(screenWidth1).toBeCloseTo(screenWidth0, 10);
  });

  it("acted-on pane uncalibrated → every other pane falls back to raw-z matching", () => {
    const acted = v(3, 0.4, 0.4);
    const out = nextGridViews(0, acted, "zoom", [v(1), v(1)], true, [null, 5]);
    expect(out[1]?.z).toBe(3); // raw z, not a physical-scale computation
  });

  it("acted-on pane calibrated but a specific other pane is not → that pane still falls back to raw z", () => {
    const acted = v(3, 0.4, 0.4);
    const out = nextGridViews(0, acted, "zoom", [v(1), v(1), v(1)], true, [
      2,
      null,
      4,
    ]);
    expect(out[1]?.z).toBe(3); // uncalibrated pane 1 → raw z
    expect(out[2]?.z).toBeCloseTo((4 / (2 / 3)) as number, 10); // pane 2 matches physical scale
  });

  it("zoom-unlinked or a non-zoom kind ignores pixelSizes entirely", () => {
    const acted = v(4, 0.2, 0.2);
    const other = v(1, 0.8, 0.8);
    expect(
      nextGridViews(0, acted, "zoom", [v(1), other], false, [2, 5])[1],
    ).toEqual(other);
    expect(
      nextGridViews(0, acted, "pan", [v(1), other], true, [2, 5])[1],
    ).toEqual(other);
  });
});
