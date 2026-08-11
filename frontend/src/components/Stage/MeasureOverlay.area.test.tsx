// Polygon/lasso measure kinds (plan item 14): closed-shape rendering + area
// label. A known-answer normalized square pins the arithmetic against
// polygonStatsNormalized x pixelSize² (calibrated) and against the raw px²
// fallback (uncalibrated), so neither path can silently regress to NaN or a
// fabricated physical number.

import { render } from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it } from "vitest";

import { fitView } from "../../lib/geometry";
import { useViewer, type Measure } from "../../store/viewer";
import MeasureOverlay from "./MeasureOverlay";

beforeAll(() => {
  Element.prototype.setPointerCapture = () => {};
  Element.prototype.releasePointerCapture = () => {};
});

const IMG = { w: 100, h: 100 };
const VP = { w: 400, h: 400 };

// normalized 60x60 image-px square (0.2-0.8 both axes) -> exactly 3600 px²
const SQUARE: Measure["pts"] = [
  { x: 0.2, y: 0.2 },
  { x: 0.8, y: 0.2 },
  { x: 0.8, y: 0.8 },
  { x: 0.2, y: 0.8 },
];

const renderOverlay = (pixelSize: number | null, pixelUnit = "nm") =>
  render(
    <MeasureOverlay
      imageId="img1"
      pixelSize={pixelSize}
      pixelUnit={pixelUnit}
      view={fitView(IMG, VP)}
      img={IMG}
      vp={VP}
      pending={null}
    />,
  );

const setMeasure = (kind: "polygon" | "lasso") => {
  const m: Measure = { id: "m1", kind, pts: SQUARE };
  useViewer.setState({
    measures: { img1: [m] },
    selectedMeasure: null,
    selectedMulti: [],
  });
};

describe("MeasureOverlay polygon/lasso area", () => {
  beforeEach(() => setMeasure("polygon"));

  it("renders a closed <polygon> for a finalized polygon measure", () => {
    const { container } = renderOverlay(0.5);
    expect(container.querySelector("polygon")).toBeTruthy();
  });

  it("labels area as polygonStatsNormalized area x pixelSize² when calibrated", () => {
    // 3600 px² * 0.5² = 900 nm² — same shoelace math as lib/geometry
    const { container } = renderOverlay(0.5, "nm");
    const label = [...container.querySelectorAll("text")].find((t) =>
      t.textContent?.includes("nm²"),
    );
    expect(label?.textContent).toBe("900 nm²");
  });

  it("reports px² (never NaN, never a fabricated physical unit) uncalibrated", () => {
    const { container } = renderOverlay(null);
    const label = [...container.querySelectorAll("text")].find((t) =>
      t.textContent?.includes("px²"),
    );
    expect(label?.textContent).toBe("3600 px²");
    expect(label?.textContent).not.toMatch(/NaN/);
  });

  it("renders a lasso measure the same way as polygon", () => {
    setMeasure("lasso");
    const { container } = renderOverlay(0.5, "nm");
    expect(container.querySelector("polygon")).toBeTruthy();
    const label = [...container.querySelectorAll("text")].find((t) =>
      t.textContent?.includes("nm²"),
    );
    expect(label?.textContent).toBe("900 nm²");
  });
});

// 20x20 image-px hole punched in the centre of SQUARE (3600 px^2) -> a net
// 3200 px^2 = 800 nm^2 at pixelSize 0.5 — the same math regionTable.test.ts
// pins for the standalone helper, exercised here through the ON-SCREEN
// label and glyph (plan item 4: the label used to call plain polygonStats
// unconditionally, so a holed region's gross area leaked onto the canvas
// even though the region table/CSV already netted it out via item 19).
const HOLE: Measure["pts"] = [
  { x: 0.4, y: 0.4 },
  { x: 0.6, y: 0.4 },
  { x: 0.6, y: 0.6 },
  { x: 0.4, y: 0.6 },
];

describe("MeasureOverlay polygon/lasso holes (plan item 4)", () => {
  beforeEach(() => {
    const m: Measure = { id: "m1", kind: "polygon", pts: SQUARE, holes: [HOLE] };
    useViewer.setState({
      measures: { img1: [m] },
      selectedMeasure: null,
      selectedMulti: [],
    });
  });

  it("renders the outer ring + hole as one evenodd <path>, not a plain <polygon>", () => {
    const { container } = renderOverlay(0.5);
    expect(container.querySelector("path[fill-rule='evenodd']")).toBeTruthy();
  });

  it("nets the hole out of the area label instead of showing the gross area", () => {
    const { container } = renderOverlay(0.5, "nm");
    const label = [...container.querySelectorAll("text")].find((t) =>
      t.textContent?.includes("nm²"),
    );
    // gross would be 900 nm² (the pre-existing no-holes test above) —
    // net is 800 nm² once the 20x20 hole (400 px² * 0.5² = 100 nm²) is
    // subtracted
    expect(label?.textContent).toContain("800");
    expect(label?.textContent).not.toContain("900");
  });

  it("marks the label so a holed region can't be mistaken for a plain one of the same net area", () => {
    const { container } = renderOverlay(0.5, "nm");
    const label = [...container.querySelectorAll("text")].find((t) =>
      t.textContent?.includes("nm²"),
    );
    expect(label?.textContent).toMatch(/hole/i);
  });

  it("a region with an EMPTY holes array renders identically to the pre-item-4 no-holes case", () => {
    const m: Measure = { id: "m1", kind: "polygon", pts: SQUARE, holes: [] };
    useViewer.setState({ measures: { img1: [m] } });
    const { container } = renderOverlay(0.5, "nm");
    expect(container.querySelector("polygon")).toBeTruthy();
    expect(container.querySelector("path[fill-rule='evenodd']")).toBeNull();
    const label = [...container.querySelectorAll("text")].find((t) =>
      t.textContent?.includes("nm²"),
    );
    expect(label?.textContent).toBe("900 nm²");
  });
});
