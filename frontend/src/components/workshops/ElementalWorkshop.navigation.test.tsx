import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  eelsQuantifyMapAsync,
  runJob,
  type EelsQuantMapResult,
  type ImageMeta,
} from "../../lib/api";
import { useViewer } from "../../store/viewer";

vi.mock("uplot", () => ({
  default: class {
    destroy() {}
  },
}));

vi.mock("../../lib/api", async (importActual) => {
  const actual = await importActual<typeof import("../../lib/api")>();
  return {
    ...actual,
    fetchSpectrum: vi.fn().mockResolvedValue({
      energy: [100, 200, 300, 400],
      counts: [1, 3, 2, 1],
      units: "eV",
    }),
    eelsQuantifyMapAsync: vi.fn(),
    runJob: vi.fn(),
    // ElementalWorkshop opens on the Maps tab, which mounts the real
    // EelsMapsTab and auto-identifies immediately — without this, every test
    // here would fire a real, unmocked fetch to /api/eels/auto-assign.
    eelsAutoAssign: vi.fn().mockResolvedValue({ edges: [] }),
  };
});

import ElementalWorkshop from "./ElementalWorkshop";

function spectrumMeta(): ImageMeta {
  return {
    id: "eels",
    name: "eels.dm4",
    kind: "spectrum",
    shape: [4],
    dtype: "float32",
    pixel_size: null,
    pixel_unit: "",
    value_unit: "counts",
    n_channels: 4,
    energy_first: 100,
    energy_last: 400,
    energy_units: "eV",
    stage_tilt_deg: null,
    meta: {},
  };
}

afterEach(() => {
  useViewer.setState({ images: {}, order: [], activeId: null, selected: [] });
});

describe("EELS navigation through the Elemental Analysis shell", () => {
  it("keeps configured edges while moving between workflow tabs", async () => {
    useViewer.getState().ingest([spectrumMeta()]);
    useViewer.getState().setActive("eels");
    render(<ElementalWorkshop />);

    // one strip, shared with EDS — the merge removed the nested EELS one
    expect(
      screen.getByRole("tablist", { name: "Elemental Analysis" }),
    ).toBeVisible();
    expect(screen.queryByRole("tablist", { name: "EELS workflow" })).toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: "Quantify" }));
    await waitFor(() => expect(screen.getByText("+ edge")).toBeVisible());
    fireEvent.click(screen.getByText("+ edge"));
    fireEvent.change(screen.getByPlaceholderText("El"), {
      target: { value: "O" },
    });

    fireEvent.click(screen.getByRole("tab", { name: "Model fit" }));
    expect(screen.getByDisplayValue("O")).toBeVisible();
    expect(screen.getByRole("button", { name: "Fit spectrum" })).toBeVisible();

    fireEvent.click(screen.getByRole("tab", { name: "Quantify" }));
    expect(screen.getByDisplayValue("O")).toBeVisible();
    expect(screen.getByRole("button", { name: "Quantify" })).toBeVisible();

    fireEvent.click(screen.getByRole("tab", { name: "Explore" }));
    expect(screen.getByText("Edge IDs")).toBeVisible();

    fireEvent.click(screen.getByRole("tab", { name: "Advanced" }));
    fireEvent.change(screen.getByDisplayValue("-5"), {
      target: { value: "-8" },
    });
    fireEvent.click(screen.getByRole("tab", { name: "Explore" }));
    fireEvent.click(screen.getByRole("tab", { name: "Advanced" }));
    expect(screen.getByDisplayValue("-8")).toBeVisible();
  });

  it("queues composition maps and shows real job progress", async () => {
    const cube = { ...spectrumMeta(), kind: "spectrum_image" as const };
    useViewer.getState().ingest([cube]);
    useViewer.getState().setActive("eels");

    let finish!: (result: EelsQuantMapResult) => void;
    vi.mocked(eelsQuantifyMapAsync).mockResolvedValue({ job_id: "job-1" });
    vi.mocked(runJob).mockImplementation(async (start, onProgress) => {
      await start();
      onProgress(0.5, "quantified C (1/2)");
      return new Promise((resolve) => {
        finish = resolve as (result: EelsQuantMapResult) => void;
      });
    });

    render(<ElementalWorkshop />);
    fireEvent.click(screen.getByRole("tab", { name: "Quantify" }));
    fireEvent.click(await screen.findByText("+ edge"));
    fireEvent.change(screen.getByPlaceholderText("El"), {
      target: { value: "C" },
    });
    fireEvent.change(screen.getByPlaceholderText("Z"), {
      target: { value: "6" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Maps" }));

    await waitFor(() => expect(runJob).toHaveBeenCalledOnce());
    expect(eelsQuantifyMapAsync).toHaveBeenCalledWith(
      "eels", [expect.objectContaining({ element: "C", z: 6 })],
      200, 10, "powerlaw",
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "50% quantified C (1/2)",
    );
    expect(screen.getByRole("button", { name: "Mapping…" })).toBeDisabled();

    const map = { ...cube, id: "c-map", name: "C at% (EELS)", kind: "image" as const };
    await act(async () => {
      finish({
        elements: ["C"],
        sigma: [1],
        mean_atomic_percent: [100],
        maps: [map],
      });
    });
    await waitFor(() =>
      expect(useViewer.getState().images["c-map"]).toBeDefined(),
    );
    expect(screen.queryByRole("status")).toBeNull();
  });
});
