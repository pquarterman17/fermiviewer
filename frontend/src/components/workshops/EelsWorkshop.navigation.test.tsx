import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ImageMeta } from "../../lib/api";
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
  };
});

import EelsWorkshop from "./EelsWorkshop";

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

describe("EelsWorkshop navigation", () => {
  it("keeps configured edges while moving between workflow tabs", async () => {
    useViewer.getState().ingest([spectrumMeta()]);
    useViewer.getState().setActive("eels");
    render(<EelsWorkshop />);

    const tabs = screen.getByRole("tablist", { name: "EELS workflow" });
    expect(tabs).toBeVisible();
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
});
