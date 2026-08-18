// MeasurePanel's per-measure row honors Measure.displayUnit — the same
// owner example pinned end-to-end on the stage (MeasureOverlay
// .displayUnit.test.tsx) and in the Log/CSV builder
// (measurePanelUtils.displayUnit.test.ts), so all three surfaces agree.

import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ImageMeta } from "../../lib/api";
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
