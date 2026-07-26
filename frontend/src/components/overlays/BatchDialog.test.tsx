import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  BatchOperation,
  BatchRunResult,
  ImageMeta,
} from "../../lib/api";

const fetchBatchOperations = vi.fn();
const runBatchRecipe = vi.fn();
vi.mock("../../lib/api", () => ({
  fetchBatchOperations: (...args: unknown[]) => fetchBatchOperations(...args),
  runBatchRecipe: (...args: unknown[]) => runBatchRecipe(...args),
}));

const askParams = vi.fn();
vi.mock("../../store/params", () => ({
  askParams: (...args: unknown[]) => askParams(...args),
}));

vi.mock("../../lib/resultsExport", () => ({
  downloadCsv: vi.fn(),
  downloadJson: vi.fn(),
  downloadText: vi.fn(),
  tableToCsv: vi.fn(() => "csv"),
  tableToJson: vi.fn(() => ({ rows: [] })),
}));

const state = {
  batchOpen: true,
  setBatchOpen: vi.fn(),
  selected: ["a", "b"],
  order: ["a", "b"],
  images: { a: { name: "a.dm4" }, b: { name: "b.dm4" } },
  ingestDerived: vi.fn(),
  setStatus: vi.fn(),
};
vi.mock("../../store/viewer", () => ({
  useViewer: Object.assign((selector: (value: typeof state) => unknown) =>
    selector(state), { getState: () => state }),
}));

import BatchDialog, { batchResultTable } from "./BatchDialog";

const operations: BatchOperation[] = [
  {
    name: "plane_level",
    category: "filter",
    summary: "Remove a fitted plane",
    produces: "image",
    params: [],
  },
  {
    name: "noise",
    category: "analysis",
    summary: "Noise, SNR, and type estimate",
    produces: "analysis",
    params: [
      {
        name: "method",
        type: "str",
        default: "mad",
        required: false,
        minimum: null,
        maximum: null,
        choices: ["mad", "localvar", "both"],
        doc: "",
      },
    ],
  },
];

function derived(id: string): ImageMeta {
  return {
    id,
    name: `batch(${id}.dm4)`,
    kind: "image",
    shape: [10, 10],
    dtype: "float64",
    pixel_size: 1,
    pixel_unit: "px",
    value_unit: "",
    n_channels: null,
    energy_first: null,
    energy_last: null,
    energy_units: "",
    stage_tilt_deg: null,
    meta: {},
  };
}

const result: BatchRunResult = {
  version: 1,
  steps: [
    { op: "plane_level", params: {} },
    { op: "noise", params: { method: "both" } },
  ],
  outputs: [
    {
      image_id: "a",
      name: "a.dm4",
      status: "done",
      derived: derived("a-result"),
      values: [{
        op: "noise",
        label: "noise estimate",
        params: { method: "both" },
        value: { sigma: 1.25, noise_type: "gaussian" },
      }],
    },
    {
      image_id: "b",
      name: "b.dm4",
      status: "error",
      error: "bad input",
      derived: null,
      values: [],
    },
  ],
  succeeded: 1,
  failed: 1,
};

describe("BatchDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    fetchBatchOperations.mockResolvedValue(operations);
    askParams.mockResolvedValue({ method: "both" });
    runBatchRecipe.mockImplementation(
      async (
        _ids: string[],
        _steps: unknown[],
        progress: (fraction: number, message: string) => void,
      ) => {
        progress(0.5, "a.dm4: noise estimate (2/2)");
        return result;
      },
    );
  });

  it("builds a server-schema recipe and retains partial results", async () => {
    render(<BatchDialog />);
    fireEvent.click(await screen.findByText("+ Remove a fitted plane"));
    fireEvent.click(screen.getByText("+ Noise, SNR, and type estimate"));
    await waitFor(() => expect(askParams).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("button", { name: "Run batch (2)" }));
    await waitFor(() => expect(runBatchRecipe).toHaveBeenCalled());
    expect(runBatchRecipe.mock.calls[0][0]).toEqual(["a", "b"]);
    expect(runBatchRecipe.mock.calls[0][1]).toEqual([
      { op: "plane_level", params: {} },
      { op: "noise", params: { method: "both" } },
    ]);
    expect(await screen.findByText("gaussian")).toBeVisible();
    expect(screen.getByText("bad input")).toBeVisible();
    expect(state.ingestDerived).toHaveBeenCalledWith([result.outputs[0].derived]);
    expect(screen.getByRole("status")).toHaveTextContent("1 succeeded");
  });

  it("removing a step drops it from the recipe", async () => {
    render(<BatchDialog />);
    fireEvent.click(await screen.findByText("+ Remove a fitted plane"));
    expect(screen.getByText("Remove a fitted plane")).toBeVisible();
    fireEvent.click(screen.getByTitle("Remove step"));
    expect(screen.queryByText("Remove a fitted plane")).toBeNull();
  });

  it("saves and restores the current recipe as a named preset", async () => {
    render(<BatchDialog />);
    fireEvent.click(await screen.findByText("+ Remove a fitted plane"));
    fireEvent.change(screen.getByLabelText("Preset name"), {
      target: { value: "Level first" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save new" }));
    expect(screen.getByRole("status")).toHaveTextContent("Saved “Level first”");

    fireEvent.click(screen.getByTitle("Remove step"));
    expect(screen.queryByText("Remove a fitted plane")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Load" }));
    expect(screen.getByText("Remove a fitted plane")).toBeVisible();
    expect(localStorage.getItem("fermiviewer.batchRecipePresets.v1")).toContain(
      "Level first",
    );
  });

  it("imports a portable preset and loads its server-backed operation", async () => {
    render(<BatchDialog />);
    await screen.findByText("+ Remove a fitted plane");
    const file = {
      name: "noise.fvbatch.json",
      text: async () =>
        JSON.stringify({
          format: "fermiviewer-batch-preset",
          version: 1,
          preset: {
            version: 1,
            id: "elsewhere",
            name: "Noise check",
            steps: [{ op: "noise", params: { method: "both" } }],
            createdAt: "2026-07-26T12:00:00Z",
            updatedAt: "2026-07-26T12:00:00Z",
          },
        }),
    } as File;
    fireEvent.change(screen.getByLabelText("Import recipe preset file"), {
      target: { files: [file] },
    });
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Imported “Noise check”",
    );
    fireEvent.click(screen.getByRole("button", { name: "Load" }));
    expect(screen.getByText("Noise, SNR, and type estimate")).toBeVisible();
  });

  it("flattens heterogeneous analysis values into export columns", () => {
    expect(batchResultTable(result)).toEqual({
      columns: [
        "input", "status", "error", "derived",
        "noise.noise_type", "noise.sigma",
      ],
      rows: [
        [
          "a.dm4", "done", "", "batch(a-result.dm4)",
          "gaussian", 1.25,
        ],
        ["b.dm4", "error", "bad input", "", null, null],
      ],
    });
  });
});
