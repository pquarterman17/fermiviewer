import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ImageMeta } from "../../lib/api";
import { useViewer } from "../../store/viewer";

vi.mock("../../lib/api", async (importActual) => {
  const actual = await importActual<typeof import("../../lib/api")>();
  return {
    ...actual,
    listDiffractionPhases: vi.fn().mockResolvedValue([
      { name: "Si", formula: "Si", custom: false },
    ]),
  };
});

import DiffractionWorkshop from "./DiffractionWorkshop";

function patternMeta(): ImageMeta {
  return {
    id: "pattern",
    name: "pattern.dm4",
    kind: "image",
    shape: [256, 256],
    dtype: "float32",
    pixel_size: null,
    pixel_unit: "",
    value_unit: "counts",
    n_channels: null,
    energy_first: null,
    energy_last: null,
    energy_units: "",
    stage_tilt_deg: null,
    meta: {},
  };
}

afterEach(() => {
  useViewer.setState({ images: {}, order: [], activeId: null, selected: [] });
});

describe("DiffractionWorkshop navigation", () => {
  it("keeps each task's configured values while switching tabs", async () => {
    useViewer.getState().ingest([patternMeta()]);
    useViewer.getState().setActive("pattern");
    render(<DiffractionWorkshop />);

    const tabs = screen.getByRole("tablist", { name: "Diffraction tasks" });
    expect(tabs).toBeVisible();
    fireEvent.change(screen.getByDisplayValue("10"), { target: { value: "14" } });

    fireEvent.click(screen.getByRole("tab", { name: "Calibrate" }));
    expect(screen.getByRole("button", { name: "Fit ellipse" })).toBeVisible();
    fireEvent.change(screen.getByPlaceholderText("auto"), { target: { value: "2.35" } });

    fireEvent.click(screen.getByRole("tab", { name: "Simulate" }));
    expect(screen.getByRole("button", { name: "Simulate" })).toBeVisible();

    fireEvent.click(screen.getByRole("tab", { name: "Index" }));
    expect(screen.getByDisplayValue("14")).toBeVisible();
    fireEvent.click(screen.getByRole("tab", { name: "Calibrate" }));
    expect(screen.getByDisplayValue("2.35")).toBeVisible();
  });
});
