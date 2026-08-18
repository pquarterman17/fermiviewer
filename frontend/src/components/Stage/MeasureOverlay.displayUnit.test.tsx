// Measure display-unit feature — end-to-end through the stage label
// (measureGlyphs.tsx) and the right-click "Units" menu (MeasureCtxMenu
// .tsx). The pure conversion math is pinned in lib/lengthUnits.test.ts;
// this file pins that a measure's `displayUnit` actually reaches the
// on-screen label, and that the menu offers/gates the right controls.

import { fireEvent, render } from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it } from "vitest";

import { fitView } from "../../lib/geometry";
import { useViewer, type Measure } from "../../store/viewer";
import MeasureOverlay from "./MeasureOverlay";

beforeAll(() => {
  Element.prototype.setPointerCapture = () => {};
  Element.prototype.releasePointerCapture = () => {};
});

const VP = { w: 400, h: 400 };

const renderOverlay = (
  img: { w: number; h: number },
  pixelSize: number | null,
  pixelUnit = "nm",
) =>
  render(
    <MeasureOverlay
      imageId="img1"
      pixelSize={pixelSize}
      pixelUnit={pixelUnit}
      view={fitView(img, VP)}
      img={img}
      vp={VP}
      pending={null}
    />,
  );

const seed = (measures: Measure[]) =>
  useViewer.setState({
    measures: { img1: measures },
    selectedMeasure: null,
    selectedMulti: [],
  });

describe("stage label honors Measure.displayUnit — owner examples", () => {
  it("850 nm distance + Auto -> '0.85 µm'", () => {
    // IMG chosen so the two points are exactly 850 image-px apart at
    // pixelSize 1 nm/px -> 850 nm calibrated, matching the owner spec's
    // literal length example verbatim.
    const IMG = { w: 1000, h: 1000 };
    seed([
      {
        id: "m1",
        kind: "distance",
        pts: [{ x: 0, y: 0 }, { x: 0.85, y: 0 }],
        displayUnit: "auto",
      },
    ]);
    const { container } = renderOverlay(IMG, 1, "nm");
    const label = [...container.querySelectorAll("text")].find((t) =>
      t.textContent?.includes("µm"),
    );
    expect(label?.textContent).toBe("0.85 µm");
  });

  it("37990 nm² area + Auto -> '0.038 µm²'", () => {
    // 3799 x 10 image-px rectangle -> exactly 37990 px² at pixelSize 1
    // nm/px -> 37990 nm² calibrated, matching the owner spec's literal
    // area example verbatim (also pins the squared-factor conversion end
    // to end, not just in the pure lib).
    const IMG = { w: 3799, h: 10 };
    seed([
      {
        id: "m1",
        kind: "polygon",
        pts: [
          { x: 0, y: 0 },
          { x: 1, y: 0 },
          { x: 1, y: 1 },
          { x: 0, y: 1 },
        ],
        displayUnit: "auto",
      },
    ]);
    const { container } = renderOverlay(IMG, 1, "nm");
    const label = [...container.querySelectorAll("text")].find((t) =>
      t.textContent?.includes("µm²"),
    );
    expect(label?.textContent).toBe("0.038 µm²");
  });

  it("no displayUnit override renders exactly as before this feature (image default)", () => {
    const IMG = { w: 1000, h: 1000 };
    seed([{ id: "m1", kind: "distance", pts: [{ x: 0, y: 0 }, { x: 0.85, y: 0 }] }]);
    const { container } = renderOverlay(IMG, 1, "nm");
    const label = [...container.querySelectorAll("text")].find((t) =>
      t.textContent?.includes("nm"),
    );
    expect(label?.textContent).toBe("850 nm");
  });
});

describe("stage label — non-finite measurement value (PR #159 review fix 2)", () => {
  it("a NaN distance value renders the existing '—' fallback, never a fabricated '0 <unit>'", () => {
    // pixelSize itself NaN (a broken/malformed calibration) makes
    // tiltDist's calibrated value NaN — displayLength(NaN, ...) must
    // return null (fix 2) so the label falls through to fmt()'s existing
    // Number.isFinite guard, not round3's old "NaN -> 0" behaviour.
    const IMG = { w: 1000, h: 1000 };
    seed([
      {
        id: "m1",
        kind: "distance",
        pts: [{ x: 0, y: 0 }, { x: 0.85, y: 0 }],
        displayUnit: "um",
      },
    ]);
    const { container } = renderOverlay(IMG, NaN, "nm");
    const label = [...container.querySelectorAll("text")].find((t) =>
      t.textContent?.includes("nm"),
    );
    expect(label?.textContent).toBe("— nm");
    expect(label?.textContent).not.toContain("0 ");
    expect(label?.textContent).not.toContain("µm");
  });
});

describe("MeasureCtxMenu — Units group", () => {
  const IMG = { w: 1000, h: 1000 };
  const DIST: Measure = { id: "m1", kind: "distance", pts: [{ x: 0, y: 0 }, { x: 0.85, y: 0 }] };

  beforeEach(() => seed([DIST]));

  it("lists Image default / Auto / Å / nm / µm / mm and marks the current choice", () => {
    seed([{ ...DIST, displayUnit: "nm" }]);
    const { container } = renderOverlay(IMG, 1, "nm");
    fireEvent.contextMenu(container.querySelector("line")!);
    const labels = [...container.querySelectorAll(".fvd-ctx-label")].map((l) => l.textContent);
    expect(labels).toContain("Units");
    // the six option buttons directly follow the "Units" label
    const optionTexts = [...container.querySelectorAll(".fvd-ctx-item")]
      .map((b) => b.textContent)
      .filter((t): t is string => !!t && /^(Image default|Auto|Å|nm|um|µm|mm)( ✓)?$/.test(t));
    expect(optionTexts).toEqual(["Image default", "Auto", "Å", "nm ✓", "µm", "mm"]);
  });

  it("picking a unit sets ONLY that measure's override (per-measure set)", () => {
    seed([DIST, { id: "m2", kind: "distance", pts: [{ x: 0, y: 0.2 }, { x: 0.5, y: 0.2 }] }]);
    const { container, getByText } = renderOverlay(IMG, 1, "nm");
    fireEvent.contextMenu(container.querySelectorAll("line")[0]);
    fireEvent.click(getByText("µm"));
    const measures = useViewer.getState().measures["img1"]!;
    expect(measures.find((m) => m.id === "m1")?.displayUnit).toBe("um");
    expect(measures.find((m) => m.id === "m2")?.displayUnit).toBeUndefined();
  });

  it('"Apply to all measures on this image" propagates the current choice to every measure — other images untouched', () => {
    seed([
      { ...DIST, displayUnit: "mm" },
      { id: "m2", kind: "distance", pts: [{ x: 0, y: 0.2 }, { x: 0.5, y: 0.2 }] },
    ]);
    useViewer.setState((s) => ({
      measures: {
        ...s.measures,
        img1: s.measures["img1"],
        imgOther: [{ id: "o1", kind: "distance", pts: [{ x: 0, y: 0 }, { x: 1, y: 1 }] }],
      },
    }));
    const { container, getByText } = renderOverlay(IMG, 1, "nm");
    fireEvent.contextMenu(container.querySelectorAll("line")[0]); // m1, displayUnit "mm"
    fireEvent.click(getByText("Apply to all measures on this image"));
    const state = useViewer.getState();
    expect(state.measures["img1"]!.every((m) => m.displayUnit === "mm")).toBe(true);
    expect(state.measures["imgOther"]![0].displayUnit).toBeUndefined();
  });

  it('"Image default" clears the override back to undefined', () => {
    seed([{ ...DIST, displayUnit: "nm" }]);
    const { container, getByText } = renderOverlay(IMG, 1, "nm");
    fireEvent.contextMenu(container.querySelector("line")!);
    fireEvent.click(getByText("Image default"));
    expect(useViewer.getState().measures["img1"]![0].displayUnit).toBeUndefined();
  });

  it("disables the group (with an explanatory title) when the image is uncalibrated", () => {
    const { container, getByText } = renderOverlay(IMG, null, "px");
    fireEvent.contextMenu(container.querySelector("line")!);
    const auto = getByText("Auto") as HTMLButtonElement;
    expect(auto.disabled).toBe(true);
    expect(auto.title.toLowerCase()).toContain("uncalibrated");
  });

  it("disables the group (with an explanatory title) for a reciprocal calibration unit", () => {
    const { container, getByText } = renderOverlay(IMG, 1, "1/nm");
    fireEvent.contextMenu(container.querySelector("line")!);
    const auto = getByText("Auto") as HTMLButtonElement;
    expect(auto.disabled).toBe(true);
    expect(auto.title).toContain("1/nm");
  });

  it("clicking a disabled unit button leaves the label unchanged (reciprocal unit)", () => {
    const { container, getByText } = renderOverlay(IMG, 1, "1/nm");
    fireEvent.contextMenu(container.querySelector("line")!);
    fireEvent.click(getByText("Auto"));
    expect(useViewer.getState().measures["img1"]![0].displayUnit).toBeUndefined();
  });

  it("angle measures do not offer a Units group (degrees, not a length/area)", () => {
    seed([
      {
        id: "ang",
        kind: "angle",
        pts: [{ x: 0.5, y: 0.5 }, { x: 0, y: 0 }, { x: 1, y: 0 }],
      },
    ]);
    const { container, queryByText } = renderOverlay(IMG, 1, "nm");
    // angle renders as one connected <polyline> (both legs) — right-click it
    fireEvent.contextMenu(container.querySelector("polyline")!);
    expect(queryByText("Units")).toBeNull();
  });

  // PR #159 critical-review fix 4: roi/ellipse stage labels only ever show
  // μ/σ (measureLabel's "roi"/"ellipse" case never reads displayUnit — see
  // measureGlyphs.tsx) and showLog has no roi/ellipse area column either,
  // so offering the Units menu on those kinds visibly did nothing —
  // removed from UNIT_DISPLAY_KINDS (store/viewerTypes.ts), the single
  // source both this menu and the "apply to all" action read.
  it("roi measures do not offer a Units group (menu would visibly do nothing)", () => {
    seed([{ id: "r1", kind: "roi", pts: [{ x: 0.1, y: 0.1 }, { x: 0.4, y: 0.4 }] }]);
    const { container, queryByText } = renderOverlay(IMG, 1, "nm");
    fireEvent.contextMenu(container.querySelector("rect")!);
    expect(queryByText("Units")).toBeNull();
  });

  it("ellipse measures do not offer a Units group (menu would visibly do nothing)", () => {
    seed([{ id: "e1", kind: "ellipse", pts: [{ x: 0.1, y: 0.1 }, { x: 0.4, y: 0.4 }] }]);
    const { container, queryByText } = renderOverlay(IMG, 1, "nm");
    fireEvent.contextMenu(container.querySelector("ellipse")!);
    expect(queryByText("Units")).toBeNull();
  });

  it("polygon measures still offer a Units group (has an area label the menu can retarget)", () => {
    seed([
      {
        id: "p1",
        kind: "polygon",
        pts: [
          { x: 0.1, y: 0.1 },
          { x: 0.4, y: 0.1 },
          { x: 0.4, y: 0.4 },
          { x: 0.1, y: 0.4 },
        ],
      },
    ]);
    const { container, queryByText } = renderOverlay(IMG, 1, "nm");
    fireEvent.contextMenu(container.querySelector("polygon")!);
    expect(queryByText("Units")).not.toBeNull();
  });
});
