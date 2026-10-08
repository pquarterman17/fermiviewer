// The scale bar's default position has to clear a vendor-baked databar.
// Thermo Fisher SEM/FIB TIFFs burn an info strip — magnification, HV, and
// their OWN scale bar — into the bottom of the pixel array, and the 92 %
// default landed on top of it: two scale bars overlapping, both unreadable.

import { fireEvent, render } from "@testing-library/react";
import { createRef, type RefObject } from "react";
import { beforeEach, describe, expect, it } from "vitest";

import type { ImageMeta } from "../../lib/api";
import { DEFAULTS, savePrefs } from "../../lib/prefs";
import type { ScaleBarState } from "../../store/viewerTypes";
import { useViewer } from "../../store/viewer";
import ScaleBarOverlay from "./ScaleBarOverlay";

// same cast Stage.tsx uses at its own call site (React 19 ref typing)
const barRef = () => createRef<HTMLDivElement>() as RefObject<HTMLDivElement>;

/** A fully-defaulted bar state with an explicit dragged position. */
const dragged = (x: number, y: number): ScaleBarState => ({
  x,
  y,
  lengthPhys: null,
  thickness: null,
  fontSize: null,
  color: null,
  unitOverride: null,
});

// A Helios frame: 1103 rows on disk, 1024 scanned, 79 of databar.
const IMG = { w: 1536, h: 1103 };
const CONTENT_ROWS = 1024;

function image(contentRows: number | null): ImageMeta {
  return {
    id: "a",
    name: "fib.tif",
    kind: "image",
    shape: [IMG.h, IMG.w],
    dtype: "uint16",
    pixel_size: 3.4,
    pixel_unit: "nm",
    content_rows: contentRows,
    meta: {},
  } as ImageMeta;
}

/** Rendered `top` and rule thickness, in viewport px. The viewport is sized
 *  to the image at z = 1 and centred, so viewport px == image row here —
 *  which is what makes the assertions below comparable to row indices.
 *
 *  `top` alone is not the whole story: the element is anchored at its top
 *  and draws the rule DOWNWARD, with the label below that, so what decides
 *  whether the bar collides with the databar is `top + thickness`. */
function barGeom(contentRows: number | null): { top: number; thickness: number } {
  useViewer.setState({
    activeId: "a",
    images: { a: image(contentRows) },
    scaleBars: {},
    scaleBarVisible: true,
  });
  const { container } = render(
    <ScaleBarOverlay
      imageId="a"
      pixelSize={3.4}
      unit="nm"
      view={{ z: 1, px: 0.5, py: 0.5 }}
      img={IMG}
      vp={{ w: IMG.w, h: IMG.h }}
      barRef={barRef()}
    />,
  );
  const el = container.querySelector<HTMLElement>(".fvd-scalebar");
  if (!el) throw new Error("scale bar did not render");
  const rule = el.querySelector<HTMLElement>(".bar");
  return {
    top: parseFloat(el.style.top),
    thickness: parseFloat(rule?.style.height ?? "0"),
  };
}

beforeEach(() => {
  useViewer.setState({ scaleBars: {}, scaleBarVisible: true });
  // a small label keeps the databar cases below clear of the zoom-chip
  // clearance, which is pinned separately at the end
  savePrefs({ ...DEFAULTS, scaleBarFontSize: 8 });
});

describe("ScaleBarOverlay default position", () => {
  it("keeps the default bar clear of a vendor databar", () => {
    const { top, thickness } = barGeom(CONTENT_ROWS);
    // 92 % of the 1024-row CONTENT region, not of the 1103-row array
    expect(top).toBeCloseTo(0.92 * CONTENT_ROWS, 5);
    // the point of the whole exercise: the drawn rule clears the strip
    expect(top + thickness).toBeLessThan(CONTENT_ROWS);
  });

  it("overlaps the databar without the content-row hint (the old bug)", () => {
    // Pins WHY the fix is needed. The anchor lands at 92 % of the full
    // array — 1014.8, only ~9 rows above the strip — so the rule itself
    // crosses into the databar and the label below it sits fully inside.
    const { top, thickness } = barGeom(null);
    expect(top).toBeCloseTo(0.92 * IMG.h, 5);
    expect(top).toBeLessThan(CONTENT_ROWS);          // anchor just clears…
    expect(top + thickness).toBeGreaterThan(CONTENT_ROWS); // …the rule does not
  });

  it("is unchanged for images with no databar", () => {
    // content_rows == the array height means "no bar" — the 92 % default
    // must be identical to the legacy behaviour, not shifted by a row.
    expect(barGeom(IMG.h).top).toBeCloseTo(0.92 * IMG.h, 5);
  });

  it("still honours a user-dragged position over the databar default", () => {
    // An explicit drag is the user's call, including onto the strip.
    useViewer.setState({
      activeId: "a",
      images: { a: image(CONTENT_ROWS) },
      scaleBars: { a: dragged(0.1, 0.97) },
      scaleBarVisible: true,
    });
    const { container } = render(
      <ScaleBarOverlay
        imageId="a"
        pixelSize={3.4}
        unit="nm"
        view={{ z: 1, px: 0.5, py: 0.5 }}
        img={IMG}
        vp={{ w: IMG.w, h: IMG.h }}
        barRef={barRef()}
      />,
    );
    const el = container.querySelector<HTMLElement>(".fvd-scalebar");
    expect(parseFloat(el!.style.top)).toBeCloseTo(0.97 * IMG.h, 5);
  });

  it("keeps the default bar + label above the bottom-left zoom chip", () => {
    // a 40 px label at 92 % ran down over the zoom chip (bottom: 10px)
    savePrefs({ ...DEFAULTS, scaleBarFontSize: 40 });
    const { top, thickness } = barGeom(IMG.h);
    const bottom = top + thickness + 3 + Math.ceil(40 * 1.25);
    expect(bottom).toBeLessThanOrEqual(IMG.h - 44);
  });
});

describe("ScaleBarOverlay drag", () => {
  it("cannot be dragged off the stage", () => {
    useViewer.setState({
      activeId: "a",
      images: { a: image(null) },
      scaleBars: {},
      scaleBarVisible: true,
    });
    const { container } = render(
      <ScaleBarOverlay
        imageId="a"
        pixelSize={3.4}
        unit="nm"
        view={{ z: 1, px: 0.5, py: 0.5 }}
        img={IMG}
        vp={{ w: IMG.w, h: IMG.h }}
        barRef={barRef()}
      />,
    );
    const el = container.querySelector<HTMLElement>(".fvd-scalebar")!;
    el.setPointerCapture = () => {};
    el.releasePointerCapture = () => {};
    fireEvent.pointerDown(el, { clientX: 0, clientY: 0, pointerId: 1 });
    fireEvent.pointerMove(el, { clientX: 99999, clientY: 99999, pointerId: 1 });
    const sb = useViewer.getState().scaleBars.a!;
    const widthPx = parseFloat((el.querySelector(".bar") as HTMLElement).style.width);
    // the whole bar stays inside the viewport (used to stop at x = 0.98)
    expect(sb.x * IMG.w + widthPx).toBeLessThanOrEqual(IMG.w + 1e-6);
    expect(sb.y).toBeLessThan(1);
  });
});
