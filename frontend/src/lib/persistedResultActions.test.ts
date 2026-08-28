import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", async (importActual) => {
  const actual = await importActual<typeof import("./api")>();
  return {
    ...actual,
    diffractionIndex: vi.fn(),
    listPersistedResults: vi.fn(),
  };
});

import { diffractionIndex, listPersistedResults, type ImageMeta, type PersistedResultRecord } from "./api";
import { openPersistedResult, rerunPersistedResult } from "./persistedResultActions";
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
  vi.clearAllMocks();
  useViewer.setState(initialViewer, true);
  useViewer.setState({ images: { source: image }, order: ["source"], activeId: null });
  useResultWorkflow.setState({ request: null });
  useWorkshop.setState({ structureMode: "Atoms" });
  vi.mocked(listPersistedResults).mockResolvedValue([]);
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

  it("reuses an exact live profile on reopen but creates a copy for duplicate", () => {
    const saved = record("measure.profile", { a: [11, 21], b: [51, 101], width: 5 });
    openPersistedResult(saved, "reopen");
    openPersistedResult(saved, "reopen");
    expect(useViewer.getState().measures.source).toHaveLength(1);
    openPersistedResult(saved, "duplicate");
    expect(useViewer.getState().measures.source).toHaveLength(2);
  });

  it("validates the analysis before publishing a handoff", () => {
    expect(() => openPersistedResult(record("unknown.analysis"), "reopen")).toThrow(
      "does not yet have a reopenable workshop",
    );
    expect(useResultWorkflow.getState().request).toBeNull();
  });
});

describe("rerunPersistedResult", () => {
  it("preserves diffraction tolerance and result count exactly", async () => {
    vi.mocked(diffractionIndex).mockResolvedValue({ center: [1, 1], measured_r: [], candidates: [] });
    await rerunPersistedResult(record("diffraction.index", {
      spots: [[10, 12]], pixel_size_mm: 0.014, camera_length_mm: 200,
      acc_voltage_kv: 300, tolerance: 0.1, top_n: 9,
    }));
    expect(diffractionIndex).toHaveBeenCalledWith("source", [[10, 12]], expect.objectContaining({
      tolerance: 0.1, topN: 9, record: true,
    }));
  });

  it("reports incomplete saved profile geometry clearly", async () => {
    await expect(rerunPersistedResult(record("measure.profile", { width: 2 }))).rejects.toThrow(
      "The saved profile geometry is incomplete.",
    );
  });
});
