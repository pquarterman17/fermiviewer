import { beforeEach, describe, expect, it } from "vitest";

import type { ImageMeta, PersistedResultRecord } from "./api";
import { openPersistedResult } from "./persistedResultActions";
import { useResultWorkflow } from "../store/resultWorkflow";
import { useViewer } from "../store/viewer";
import { useWorkshop } from "../store/workshop";

const initialViewer = useViewer.getState();

const image: ImageMeta = {
  id: "source", name: "source.dm4", kind: "image", shape: [100, 200], dtype: "float32",
  pixel_size: 1, pixel_unit: "nm", value_unit: "counts", n_channels: null,
  energy_first: null, energy_last: null, energy_units: "", stage_tilt_deg: null, meta: {},
};
const record = (analysis: string, params: Record<string, unknown> = {}): PersistedResultRecord => ({
  id: "r1", analysis, created_at: "2026-08-27T12:00:00Z", status: "completed",
  source_ids: ["source"], params,
});

beforeEach(() => {
  useViewer.setState(initialViewer, true);
  useViewer.setState({ images: { source: image }, order: ["source"], activeId: null });
  useResultWorkflow.setState({ request: null });
  useWorkshop.setState({ structureMode: "Atoms" });
});

describe("openPersistedResult", () => {
  it("hands an editable EDS reproduction key to the originating workshop", () => {
    const saved = record("eds.quantify", { elements: ["Fe", "O"], method: "zaf" });
    openPersistedResult(saved, "duplicate");
    expect(useViewer.getState().activeId).toBe("source");
    expect(useResultWorkflow.getState().request).toMatchObject({ record: saved, mode: "duplicate" });
  });

  it("selects Particles before opening a particle result", () => {
    openPersistedResult(record("structure.particles"), "reopen");
    expect(useWorkshop.getState().structureMode).toBe("Particles");
  });

  it("reconstructs saved 1-based profile geometry in normalized viewer coordinates", () => {
    openPersistedResult(record("measure.profile", {
      a: [11, 21], b: [51, 101], width: 5, reduce: "sum",
    }), "duplicate");
    const measure = useViewer.getState().measures.source[0];
    expect(measure.kind).toBe("profile");
    expect(measure.pts).toEqual([{ x: 0.1, y: 0.1 }, { x: 0.5, y: 0.5 }]);
    expect(measure.width).toBe(5);
    expect(useViewer.getState().profileReduce).toBe("sum");
  });
});
