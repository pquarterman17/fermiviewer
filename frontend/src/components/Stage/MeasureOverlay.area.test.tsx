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
