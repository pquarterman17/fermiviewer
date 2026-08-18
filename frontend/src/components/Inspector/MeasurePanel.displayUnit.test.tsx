// MeasurePanel's per-measure row honors Measure.displayUnit — the same
// owner example pinned end-to-end on the stage (MeasureOverlay
// .displayUnit.test.tsx) and in the Log/CSV builder
// (measurePanelUtils.displayUnit.test.ts), so all three surfaces agree.

import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ImageMeta } from "../../lib/api";
import { measureLabel } from "../Stage/measureGlyphs";
import { useViewer } from "../../store/viewer";
import MeasurePanel from "./MeasurePanel";

function meta(id: string, extra: Partial<ImageMeta> = {}): ImageMeta {
  return {
    id,
    name: `${id}.dm4`,
    kind: "image",
    shape: [1000, 1000],
    dtype: "float64",
    pixel_size: 1,
    pixel_unit: "nm",
    n_channels: null,
    energy_first: null,
    energy_last: null,
    energy_units: "",
    stage_tilt_deg: null,
    meta: {},
    ...extra,
  } as ImageMeta;
}

describe("MeasurePanel row honors Measure.displayUnit", () => {
  it("850 nm distance + Auto renders '0.85 µm' in the measurement row", () => {
    useViewer.setState(useViewer.getInitialState(), true);
    const s = useViewer.getState();
    s.ingest([meta("a")]);
    const mid = s.addMeasure("a", {
      kind: "distance",
      pts: [{ x: 0, y: 0 }, { x: 0.85, y: 0 }],
    });
    useViewer.getState().setActive("a");
    useViewer.getState().setMeasureDisplayUnit("a", mid, "auto");

    const { container } = render(<MeasurePanel />);
    const val = container.querySelector(".fvd-measure-row .val");
    expect(val?.textContent).toBe("0.85 µm");
  });

  it("no override renders the calibration unit verbatim, exactly as before this feature", () => {
    useViewer.setState(useViewer.getInitialState(), true);
    const s = useViewer.getState();
    s.ingest([meta("a")]);
    s.addMeasure("a", { kind: "distance", pts: [{ x: 0, y: 0 }, { x: 0.85, y: 0 }] });
    useViewer.getState().setActive("a");

    const { container } = render(<MeasurePanel />);
    const val = container.querySelector(".fvd-measure-row .val");
    expect(val?.textContent).toBe("850 nm");
  });
});

describe("MeasurePanel row — polyline (PR #159 review fix 5)", () => {
  it("a 3-point polyline shows its converted length, matching the stage label", () => {
    // valueOf had no polyline branch at all — the row rendered "" while
    // the stage (measureGlyphs.tsx) already showed the total length.
    // Points chosen so the two-segment total is exactly the owner
    // example's 850 nm (500 + 350), reusing that literal on purpose.
    useViewer.setState(useViewer.getInitialState(), true);
    const s = useViewer.getState();
    s.ingest([meta("a")]);
    const pts = [{ x: 0, y: 0 }, { x: 0.5, y: 0 }, { x: 0.85, y: 0 }];
    const mid = s.addMeasure("a", { kind: "polyline", pts });
    useViewer.getState().setActive("a");
    useViewer.getState().setMeasureDisplayUnit("a", mid, "auto");

    const img = { w: 1000, h: 1000 };
    const stageLabel = measureLabel(
      { id: mid, kind: "polyline", pts, displayUnit: "auto" },
      { img, pixelSize: 1, pixelUnit: "nm", tilt: null, roiStats: {} },
    );
    expect(stageLabel).toBe("0.85 µm");

    const { container } = render(<MeasurePanel />);
    const val = container.querySelector(".fvd-measure-row .val");
    expect(val?.textContent).not.toBe("");
    expect(val?.textContent).toBe(stageLabel);
  });
});

describe("MeasurePanel row — holed polygon uses NET area, matching the stage (PR #159 review fix 3)", () => {
  // 100x100 image, pixel_size 1 nm/px: outer full-image square is 10000
  // nm² gross, a 50x50 hole subtracts 2500 nm², net 7500 nm² — the
  // review's own example numbers. valueOf used to call plain
  // polygonStats (gross only), disagreeing with the stage's holes-aware
  // stats everywhere the PR promised it couldn't.
  const OUTER = [
    { x: 0, y: 0 },
    { x: 1, y: 0 },
    { x: 1, y: 1 },
    { x: 0, y: 1 },
  ];
  const HOLE = [
    { x: 0.25, y: 0.25 },
    { x: 0.75, y: 0.25 },
    { x: 0.75, y: 0.75 },
    { x: 0.25, y: 0.75 },
  ];

  function seedHoledPolygon(displayUnit?: "auto" | "um") {
    useViewer.setState(useViewer.getInitialState(), true);
    const s = useViewer.getState();
    s.ingest([meta("a", { shape: [100, 100] })]);
    const hostId = s.addMeasure("a", { kind: "polygon", pts: OUTER });
    const childId = s.addMeasure("a", { kind: "polygon", pts: HOLE });
    useViewer.getState().addHole("a", hostId, childId);
    if (displayUnit) useViewer.getState().setMeasureDisplayUnit("a", hostId, displayUnit);
    useViewer.getState().setActive("a");
    return hostId;
  }

  it("without a unit override: panel row shows the same net value as the stage", () => {
    seedHoledPolygon();
    const img = { w: 100, h: 100 };
    const stageLabel = measureLabel(
      { id: "host", kind: "polygon", pts: OUTER, holes: [HOLE] },
      { img, pixelSize: 1, pixelUnit: "nm", tilt: null, roiStats: {} },
    );
    expect(stageLabel).toBe("7500 nm² (1 hole)"); // sanity: net, not the 10000 gross

    const { container } = render(<MeasurePanel />);
    const val = container.querySelector(".fvd-measure-row .val");
    expect(val?.textContent).toBe("7500 nm²");
  });

  it("with a unit override: panel row shows the same converted net value as the stage", () => {
    seedHoledPolygon("um");
    const img = { w: 100, h: 100 };
    const stageLabel = measureLabel(
      { id: "host", kind: "polygon", pts: OUTER, holes: [HOLE], displayUnit: "um" },
      { img, pixelSize: 1, pixelUnit: "nm", tilt: null, roiStats: {} },
    );
    expect(stageLabel).toBe("0.0075 µm² (1 hole)");

    const { container } = render(<MeasurePanel />);
    const val = container.querySelector(".fvd-measure-row .val");
    expect(val?.textContent).toBe("0.0075 µm²");
  });
});

describe("MeasurePanel ROI-stats area row — image default only (PR #159 review fix 4)", () => {
  it("ignores the measure's displayUnit override — roi/ellipse never offer the Units menu that would set it", () => {
    useViewer.setState(useViewer.getInitialState(), true);
    const s = useViewer.getState();
    s.ingest([meta("a")]);
    const mid = s.addMeasure("a", {
      kind: "roi",
      pts: [{ x: 0.1, y: 0.1 }, { x: 0.4, y: 0.4 }],
    });
    // fix 4 removed roi/ellipse from the menu's kind gate, but the field
    // itself could still be present on old/hand-edited data — the row
    // must render the image-default unit regardless.
    useViewer.getState().setMeasureDisplayUnit("a", mid, "um");
    useViewer.getState().setRoiStats(mid, { mean: 1, std: 0.5, min: 0, max: 2, area: 20000, unit: "nm" });
    useViewer.getState().setActive("a");
    useViewer.getState().setSelectedMeasure(mid);

    const { container, getByText } = render(<MeasurePanel />);
    void container;
    const areaLabel = getByText("area (nm²)");
    const row = areaLabel.closest(".fvd-meta-row");
    expect(row?.querySelector(".v")?.textContent).toBe("20000");
    expect(row?.textContent).not.toContain("µm");
  });
});
