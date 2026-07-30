import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ImageMeta } from "../../lib/api";
import { useViewer } from "../../store/viewer";
import Inspector from "./Inspector";

vi.mock("../workshops/EelsWorkshop", () => ({
  default: () => <div>EELS content</div>,
}));
vi.mock("../workshops/DiffractionWorkshop", () => ({
  default: () => <div>Diffraction content</div>,
}));

const cube: ImageMeta = {
  id: "cube",
  name: "cube.dm4",
  kind: "spectrum_image",
  shape: [8, 8, 128],
  dtype: "float32",
  pixel_size: 1,
  pixel_unit: "nm",
  value_unit: "",
  n_channels: 128,
  energy_first: 0,
  energy_last: 12.7,
  energy_units: "keV",
  stage_tilt_deg: null,
  meta: {},
};

beforeEach(() => {
  useViewer.setState({
    images: { cube },
    order: ["cube"],
    activeId: "cube",
    tools: [],
    toolsLayout: "cards",
  });
});

describe("Inspector Elemental launcher", () => {
  it("opens the authoritative workspace instead of mounting a duplicate", () => {
    render(<Inspector />);
    fireEvent.click(screen.getByRole("button", { name: "Elemental" }));
    fireEvent.click(
      screen.getByRole("button", { name: "Open Elemental Analysis" }),
    );
    expect(useViewer.getState().tools).toEqual([
      expect.objectContaining({ kind: "eds" }),
    ]);
    expect(
      screen.getByText(/share one resizable\s+workspace/),
    ).toBeVisible();
  });

  it("launches rather than mounting for EELS too, which used to differ", () => {
    // The EELS inspector tab mounted a full second workshop while EDS only
    // launched one — the asymmetry the merged workspace removes.
    render(<Inspector />);
    fireEvent.click(screen.getByRole("button", { name: "Elemental" }));
    expect(screen.queryByRole("tablist", { name: "EELS workflow" })).toBeNull();
    expect(screen.queryByRole("button", { name: "EELS" })).toBeNull();
  });
});
